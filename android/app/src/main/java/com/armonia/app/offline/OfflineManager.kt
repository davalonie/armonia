package com.armonia.app.offline

import android.content.Context
import android.util.AtomicFile
import android.net.Uri
import androidx.media3.common.util.UnstableApi
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.datasource.cache.ContentMetadata
import androidx.media3.datasource.cache.NoOpCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import androidx.media3.exoplayer.offline.Download
import androidx.media3.exoplayer.offline.DownloadManager
import androidx.media3.exoplayer.offline.DownloadRequest
import androidx.media3.exoplayer.offline.DownloadService
import androidx.media3.exoplayer.scheduler.Requirements
import com.google.gson.Gson
import com.armonia.app.data.api.Song
import com.armonia.app.data.repository.LibraryRepository
import com.armonia.app.data.repository.PreferencesRepository
import com.armonia.app.security.AccountScope
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.distinctUntilChanged
import com.armonia.app.playback.StreamCacheKeys
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.util.concurrent.Executors
import javax.inject.Inject
import javax.inject.Singleton

/** Download state of one pinned collection. */
data class OfflineProgress(val done: Int, val total: Int, val failed: Int, val running: Boolean) {
    val complete: Boolean get() = !running && done == total
}

/**
 * Keeps albums and playlists on the phone. Pinned audio lives in its own
 * never-evicted cache (separate from the play-through LRU cache in
 * [com.armonia.app.playback.StreamCache]), filled by Media3's [DownloadManager]
 * through [OfflineDownloadService], so downloads keep going in the background
 * and survive restarts. The list of what is pinned is a JSON catalog in app
 * storage so it can be browsed without the server.
 */
@UnstableApi
@Singleton
class OfflineManager @Inject constructor(
    @ApplicationContext private val context: Context,
    private val repository: LibraryRepository,
    private val gson: Gson,
    private val prefs: PreferencesRepository,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    @Volatile private var loadedAccount = ""
    private var catalogWritable = false
    private val _persistenceProblem = MutableStateFlow<String?>(null)
    val persistenceProblem = _persistenceProblem.asStateFlow()
    private val catalogFile get() = File(context.filesDir, "offline_catalog_${loadedAccount}.json")

    // One database provider for everything Media3 stores in SQLite (both caches'
    // indexes and the download index share the file). Separate SQLiteOpenHelper
    // instances on the same file can fail with "database is locked".
    val databaseProvider: StandaloneDatabaseProvider by lazy { StandaloneDatabaseProvider(context) }

    val cache: SimpleCache by lazy {
        SimpleCache(File(context.filesDir, "offline_media"), NoOpCacheEvictor(), databaseProvider)
    }

    private val httpFactory: DataSource.Factory = com.armonia.app.security.AuthenticatedMedia.factory(prefs, download = true)

    val downloadManager: DownloadManager by lazy {
        DownloadManager(context, databaseProvider, cache, httpFactory, Executors.newFixedThreadPool(2)).apply {
            maxParallelDownloads = 2
            minRetryCount = 2
            // Only on Wi-Fi (or another unmetered network): a download is many songs at once (0.5.3).
            requirements = Requirements(Requirements.NETWORK_UNMETERED)
            addListener(object : DownloadManager.Listener {
                override fun onDownloadChanged(dm: DownloadManager, download: Download, finalException: Exception?) = scheduleProgress()
                override fun onDownloadRemoved(dm: DownloadManager, download: Download) = scheduleProgress()
                override fun onIdle(dm: DownloadManager) = scheduleProgress()
                override fun onInitialized(dm: DownloadManager) = scheduleProgress()
            })
        }
    }

    private val _catalog = MutableStateFlow(OfflineCatalog())
    val catalog: StateFlow<OfflineCatalog> = _catalog.asStateFlow()

    private fun ownsCatalog(account: String) =
        account.isNotBlank() && loadedAccount == account && prefs.accountNamespace == account

    fun songStatesFor(account: String): Map<String, OfflineSongState> =
        if (ownsCatalog(account)) songStates.value else emptyMap()

    fun collectionsFor(account: String): List<OfflineCollection> =
        if (ownsCatalog(account))
            catalog.value.collections else emptyList()

    private val _progress = MutableStateFlow<Map<String, OfflineProgress>>(emptyMap())
    val progress: StateFlow<Map<String, OfflineProgress>> = _progress.asStateFlow()

    private var progressJob: Job? = null

    private val _songStates = MutableStateFlow<Map<String, OfflineSongState>>(emptyMap())
    /** songId -> how it's kept on the phone (absent = not on the phone). */
    val songStates: StateFlow<Map<String, OfflineSongState>> = _songStates.asStateFlow()

    init {
        scope.launch { _catalog.collect { refreshSongStates() } }
        scope.launch { _progress.collect { refreshSongStates() } }
        scope.launch(Dispatchers.Main) {
            prefs.authState.map { auth ->
                if (auth.sessionId.isBlank() || auth.userId.isBlank()) "" else auth.namespace
            }.distinctUntilChanged().collect { account ->
                downloadManager.pauseDownloads()
                progressJob?.cancel()
                loadedAccount = account
                catalogWritable = false
                _persistenceProblem.value = null
                _catalog.value = if (account.isBlank()) OfflineCatalog() else try {
                    val file = AtomicFile(catalogFile)
                    val value = if (!file.baseFile.exists() && !File(file.baseFile.path + ".bak").exists()) OfflineCatalog()
                        else OfflineCatalog.parseStored(file.readFully().toString(Charsets.UTF_8), gson)
                    catalogWritable = true
                    value
                } catch (_:Exception) {
                    _persistenceProblem.value = "No se puede leer el catalogo offline. Se conserva el archivo y se bloquean cambios para evitar perdida de datos."
                    OfflineCatalog()
                }
                _progress.value = emptyMap()
                // Persist stop reasons before resuming: other accounts stay paused.
                downloadManager.downloadIndex.getDownloads().use { cursor ->
                    while (cursor.moveToNext()) {
                        val id = cursor.download.request.id
                        downloadManager.setStopReason(id, if (account.isNotBlank() && id.startsWith(account + ":")) 0 else 1)
                    }
                }
                if (account.isNotBlank()) downloadManager.resumeDownloads()
                scheduleProgress()
            }
        }
    }

    /** A read-only data source over the offline cache, to sit in front of the playback chain. */
    fun readOnlyDataSourceFactory(upstream: DataSource.Factory): DataSource.Factory =
        CacheDataSource.Factory()
            .setCache(cache)
            .setUpstreamDataSourceFactory(upstream)
            .setCacheKeyFactory { StreamCacheKeys.keyFor(it.uri.toString(), prefs.accountNamespace) }
            .setCacheWriteDataSinkFactory(null)
            .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)

    fun isPinned(key: String): Boolean = _catalog.value.find(key) != null

    private fun cacheKey(songId: String) = StreamCacheKeys.keyFor(repository.getStreamUrl(songId), prefs.accountNamespace)

    /** Disk-backed check — call off the main thread. */
    fun isSongCached(songId: String): Boolean = isKeyCached(cacheKey(songId))

    /** Same check for the address a queue item streams from. Off the main thread. */
    fun isUriCached(uri: String): Boolean = isKeyCached(StreamCacheKeys.keyFor(uri, prefs.accountNamespace))

    private fun isKeyCached(key: String): Boolean {
        val length = ContentMetadata.getContentLength(cache.getContentMetadata(key))
        return length > 0 && cache.getCachedBytes(key, 0, length) == length
    }

    suspend fun cachedSongIds(songs: List<Song>): Set<String> = withContext(Dispatchers.IO) {
        songs.map { it.id }.filter { isSongCached(it) }.toSet()
    }

    suspend fun sizeBytes(): Long = withContext(Dispatchers.IO) { cache.cacheSpace }

    private fun refreshSongStates() {
        _songStates.value = offlineSongStates(_catalog.value, _progress.value)
    }

    fun pinSong(song: Song) = pin(OfflineCollection.forSong(song))

    fun unpinSong(songId: String) = unpin(OfflineCollection.songKey(songId))

    fun pin(collection: OfflineCollection) {
        if (loadedAccount.isBlank() || loadedAccount != prefs.accountNamespace) return
        if (!publishCatalog(_catalog.value.upsert(collection))) return
        downloadManager.resumeDownloads()
        _progress.update { it + (collection.key to OfflineProgress(0, collection.songs.size, 0, running = true)) }
        collection.songs.forEach { song ->
            val url = repository.getStreamUrl(song.id) + if (song.id.contains("|")) "?purpose=offline" else ""
            val request = DownloadRequest.Builder(cacheKey(song.id), Uri.parse(url))
                .setCustomCacheKey(cacheKey(song.id))
                .build()
            // Download ids are the cache keys, so a song shared by two pinned
            // collections is fetched once.
            DownloadService.sendAddDownload(context, OfflineDownloadService::class.java, request, /* foreground= */ true)
        }
        scheduleProgress()
    }

    fun unpin(key: String) {
        if (loadedAccount.isBlank() || loadedAccount != prefs.accountNamespace) return
        val evictable = _catalog.value.songsOnlyIn(key)
        if (!publishCatalog(_catalog.value.remove(key))) return
        _progress.update { it - key }
        // Removing a download also deletes its bytes from the cache.
        evictable.forEach { id ->
            DownloadService.sendRemoveDownload(context, OfflineDownloadService::class.java, cacheKey(id), /* foreground= */ false)
        }
    }

    suspend fun removeAll() {
        val account = loadedAccount
        if (account.isBlank() || account != prefs.accountNamespace) return
        if (!publishCatalog(OfflineCatalog())) return
        _progress.value = emptyMap()
        // Never remove another account's downloads.
        withContext(Dispatchers.IO) {
            downloadManager.downloadIndex.getDownloads().use { cursor ->
                while (cursor.moveToNext()) {
                    val id = cursor.download.request.id
                    if (id.startsWith(account + ":")) {
                        DownloadService.sendRemoveDownload(context, OfflineDownloadService::class.java, id, false)
                    }
                }
            }
        }
        withContext(Dispatchers.IO) { cache.keys.filter { it.startsWith(account + ":") }.forEach { runCatching { cache.removeResource(it) } } }
    }

    /** Recomputes per-collection progress from the download index; coalesces bursts of events. */
    private fun scheduleProgress() {
        progressJob?.cancel()
        progressJob = scope.launch {
            val account = loadedAccount
            delay(250)
            val states = HashMap<String, Int>()
            runCatching {
                downloadManager.downloadIndex.getDownloads().use { cursor ->
                    while (cursor.moveToNext()) {
                        val d = cursor.download
                        states[d.request.id] = d.state
                    }
                }
            }
            val catalog = _catalog.value
            val cachedKeys = catalog.allSongs().map { cacheKey(it.id) }.filter { isKeyCached(it) }.toSet()
            if (account != loadedAccount) return@launch
            _progress.value = catalog.collections.associate { c ->
                c.key to collectionProgress(c.songs.map { cacheKey(it.id) }, states, cachedKeys)
            }
        }
    }

    private fun publishCatalog(next: OfflineCatalog): Boolean {
        if (loadedAccount.isBlank() || !catalogWritable) return false
        return try {
            commitCatalog(next, { value ->
                val file = AtomicFile(catalogFile)
                val stream = file.startWrite()
                try {
                    stream.write(value.toJson(gson).toByteArray(Charsets.UTF_8))
                    file.finishWrite(stream)
                } catch (e:Exception) { file.failWrite(stream); throw e }
            }, { _catalog.value = it })
            _persistenceProblem.value = null
            true
        } catch (_:Exception) {
            _persistenceProblem.value = "No se pudo guardar el catalogo offline. Comprueba el almacenamiento; no se han eliminado descargas."
            false
        }
    }
}
