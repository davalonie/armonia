package com.armonia.app.playback

import android.content.Context
import androidx.media3.common.C
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.datasource.cache.LeastRecentlyUsedCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import com.armonia.app.data.repository.PreferencesRepository
import com.armonia.app.offline.OfflineManager
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

/**
 * On-device cache for streamed audio, so replaying a song doesn't re-download it.
 * Backed by Media3's [SimpleCache] (least-recently-used eviction at the size chosen
 * in Settings). Only one [SimpleCache] may be open per directory, hence a singleton.
 */
@UnstableApi
@Singleton
class StreamCache @Inject constructor(
    @ApplicationContext private val context: Context,
    private val prefs: PreferencesRepository,
    private val offline: OfflineManager,
) {
    private val dir = File(context.cacheDir, "media")

    // The size limit is read once when the cache is first opened, so a new limit
    // picked in Settings applies the next time the app starts.
    private val cache: SimpleCache by lazy {
        val maxBytes = runBlocking { prefs.cacheMaxMb.first() } * 1024L * 1024L
        SimpleCache(dir, LeastRecentlyUsedCacheEvictor(maxBytes), offline.databaseProvider)
    }

    private val http by lazy { com.armonia.app.security.AuthenticatedMedia.factory(prefs) }

    private val chooser = VariantChooser(
        keptFromStart = { key -> cache.getCachedLength(key, 0, C.LENGTH_UNSET.toLong()).coerceAtLeast(0) },
        lowWanted = { DataSaving.wanted() },
    )

    /** Songs from the server, each under the key of the variant chosen for it (see Variants.kt). */
    private val playback: DataSource.Factory by lazy {
        val lru = CacheDataSource.Factory()
            .setCache(cache)
            .setUpstreamDataSourceFactory(DefaultDataSource.Factory(context, http))
            .setCacheKeyFactory { spec ->
                spec.key?.takeIf { Variant.ofKey(it) != null }
                    ?: StreamCacheKeys.playbackKeyFor(spec.uri.toString(), prefs.accountNamespace)
            }
            .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)
        DataSource.Factory {
            VariantDataSource(lru, chooser, { StreamCacheKeys.keyFor(it, prefs.accountNamespace) },
                forget = { key -> runCatching { cache.removeResource(key) } })
        }
    }

    fun dataSourceFactory(): DataSource.Factory {
        // Pinned (offline) audio is checked first and read-only, so playing it
        // neither touches the network nor duplicates it into the LRU cache.
        return offline.readOnlyDataSourceFactory(DataSource.Factory { SourceRoutingDataSource(playback, http) })
    }

    /**
     * Keeps the first [NextSongPreload.BYTES] of the song behind [uri] (in the variant its playback would
     * use), so it starts at once when its turn comes. Returns how many bytes it read; stops early when
     * [keepGoing] turns false. Blocking: call off the main thread.
     */
    fun preloadStart(uri: String, keepGoing: () -> Boolean): Long {
        if (isOnPhone(uri)) return 0
        val source = playback.createDataSource()
        var read = 0L
        try {
            source.open(DataSpec.Builder().setUri(uri).setPosition(0).setLength(NextSongPreload.BYTES)
                .setHttpRequestHeaders(mapOf(NextSongPreload.HEADER to "1")).build())
            val buffer = ByteArray(16 * 1024)
            while (keepGoing()) {
                val n = source.read(buffer, 0, buffer.size)
                if (n == C.RESULT_END_OF_INPUT) break
                read += n
            }
        } finally {
            source.close()
        }
        return read
    }

    /**
     * Keeps the whole song behind [uri] (in the variant its playback would use now), at the unhurried pace of a
     * preload. Returns how many bytes it read; stops early when [keepGoing] turns false. Blocking.
     */
    fun keepWhole(uri: String, keepGoing: () -> Boolean): Long {
        if (isOnPhone(uri)) return 0
        val source = playback.createDataSource()
        var read = 0L
        try {
            source.open(DataSpec.Builder().setUri(uri).setPosition(0)
                .setHttpRequestHeaders(mapOf(NextSongPreload.HEADER to "1")).build())
            val buffer = ByteArray(32 * 1024)
            while (keepGoing()) {
                val n = source.read(buffer, 0, buffer.size)
                if (n == C.RESULT_END_OF_INPUT) break
                read += n
            }
        } finally {
            source.close()
        }
        return read
    }

    /**
     * Whether the whole song behind [uri] is on the phone: downloaded for offline use, or kept
     * complete in this cache from having been played. Disk-backed; call off the main thread.
     */
    fun isOnPhone(uri: String): Boolean {
        if (offline.isUriCached(uri)) return true
        val base = StreamCacheKeys.keyFor(uri, prefs.accountNamespace)
        return Variant.entries.any { variant ->
            val key = variant.key(base)
            val length = androidx.media3.datasource.cache.ContentMetadata.getContentLength(cache.getContentMetadata(key))
            length > 0 && cache.getCachedBytes(key, 0, length) == length
        }
    }

    suspend fun usedBytes(): Long = withContext(Dispatchers.IO) { cache.cacheSpace }

    suspend fun clear() = withContext(Dispatchers.IO) {
        cache.keys.toList().forEach { cache.removeResource(it) }
    }
}
