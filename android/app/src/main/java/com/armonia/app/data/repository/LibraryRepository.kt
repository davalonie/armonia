package com.armonia.app.data.repository

import com.armonia.app.data.api.ArmoniaApi
import com.armonia.app.data.api.Song
import com.armonia.app.data.api.SubsonicResponse
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class LibraryRepository @Inject constructor(
    private val api: ArmoniaApi,
    private val prefs: PreferencesRepository,
    private val playlistCache: com.armonia.app.data.cache.PlaylistCache,
) {
    private val cachedServerUrl: String get() = prefs.cachedAuth.serverUrl

    private val _libraryChanged = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val libraryChanged: SharedFlow<Unit> = _libraryChanged.asSharedFlow()

    fun notifyLibraryChanged() {
        invalidateCaches()
        _libraryChanged.tryEmit(Unit)
    }

    val membershipRevision = kotlinx.coroutines.flow.MutableStateFlow(0L)
    private val savedSongs = SessionSavedSongs()

    // Library ids of the songs from outside the library that «Descargar y guardar» downloaded. The queue keeps
    // playing the preview, so the player's ✓ and the playlist sheet look up its library copy here. Kept on the phone,
    // so a preview still in the queue after the app restarts keeps its ✓ (PreviewCopies).
    @Volatile private var copies = PreviewCopies.decode(null, "")
    private val copiesLock = Mutex()

    /** The library id [song] is saved under: itself, the downloaded copy of a preview, or null (not in the library). */
    fun localCopy(song: String): String? = when {
        // [copies] is read again whenever the account changes, so it always holds the current account's.
        song.startsWith("preview|") -> copies[song]
        song.startsWith("external|") -> null
        else -> song
    }

    private suspend fun rememberCopy(preview: String, local: String, account: AuthSnapshot) = copiesLock.withLock {
        if (copies.namespace != account.namespace || account != prefs.cachedAuth) return@withLock
        copies = copies.with(preview, local)
        prefs.savePreviewCopies(copies.encode())
    }

    /**
     * True, and the copy forgotten, when the library copy of [preview] was deleted since (from the phone or the web):
     * saving the song again downloads it again. Navidrome keeps a deleted file's song as "missing", so asking for it
     * by id still answers; like the server (navidrome_client.song_is_unlisted), what counts is that searching no
     * longer lists it. A failed search keeps the copy.
     */
    private suspend fun forgetIfGone(preview: Song, local: String): Boolean {
        val found = runCatching {
            api.getLibrary("search3", mapOf("query" to preview.title, "songCount" to "100", "albumCount" to "0",
                "artistCount" to "0")).body()?.response?.takeIf { it.status == "ok" }?.searchResult3
        }.getOrNull() ?: return false
        if (found.song.orEmpty().any { it.id == local }) return false
        copiesLock.withLock {
            if (copies[preview.id] == local) {
                copies = copies.without(preview.id)
                prefs.savePreviewCopies(copies.encode())
            }
        }
        invalidateMembership()
        return true
    }

    suspend fun isSaved(song: String): Boolean {
        // A song not downloaded yet is in no playlist, and asking would cost a request per song change.
        val id = localCopy(song) ?: return false
        val account = prefs.cachedAuth
        val result = savedSongs.get(account, membershipRevision.value, id) {
            checkNotNull(api.membership(id, true, account.userId).body()).saved
        }
        check(account == prefs.cachedAuth)
        return result
    }

    suspend fun membership(song: String, account: AuthSnapshot) =
        checkNotNull(api.membership(song, false, account.userId).body())

    /** The lists and favourite of [song]'s library copy, or null when it has none (anymore). */
    suspend fun copyMembership(song: Song, account: AuthSnapshot): com.armonia.app.data.api.Membership? {
        val id = localCopy(song.id) ?: return null
        // Checked when the sheet opens, not on every song change: one search, only for a downloaded preview.
        if (id != song.id && forgetIfGone(song, id)) return null
        return membership(id, account)
    }

    /**
     * «Descargar y guardar»: downloads a song found outside the library and returns its library id, the
     * only kind a playlist can hold. Only called when the user confirms saving that song in a playlist.
     */
    suspend fun downloadForPlaylist(song: Song, account: AuthSnapshot): String {
        check(account == prefs.cachedAuth)
        val result = api.download(com.armonia.app.data.api.DownloadRequest(song.id.removePrefix("preview|"),
            song.title, song.artist, album = song.album.orEmpty()), account.userId)
        val job = result.body()?.jobId
        check(job != null || result.code() == 409) { "No se pudo iniciar la descarga" }
        if (job != null) check(kotlinx.coroutines.withTimeoutOrNull(180_000) {
            while (true) {
                check(account == prefs.cachedAuth)
                val state = api.jobStatus(job).body()?.status
                if (state == "done") break
                check(state != "error" && state != "cancelled") { "No se pudo descargar «${song.title}». No se ha guardado." }
                check(state in setOf("pending", "downloading", "tagging", "scanning")) { "La descarga no ha terminado" }
                kotlinx.coroutines.delay(1500)
            }
            true
        } == true) { "La descarga sigue pendiente. Reintenta al terminar." }
        check(account == prefs.cachedAuth)
        val response = api.getLibrary("search3", mapOf("query" to song.title, "songCount" to "100",
            "albumCount" to "0", "artistCount" to "0"))
        val exact = response.body()?.response?.searchResult3?.song.orEmpty().filter {
            it.title.equals(song.title, true) && it.artist.equals(song.artist, true) &&
                (song.duration == 0 || kotlin.math.abs(it.duration - song.duration) <= 3)
        }
        val id = checkNotNull(exact.singleOrNull()?.id) { "No se pudo identificar una unica grabacion en la biblioteca" }
        check(account == prefs.cachedAuth)
        rememberCopy(song.id, id, account)
        // A new song in the library, as after any other download: Canciones and Buscar show it.
        notifyLibraryChanged()
        return id
    }

    suspend fun setMembership(id: String, song: String, included: Boolean, account: AuthSnapshot) {
        check(account == prefs.cachedAuth)
        check(api.setMembership(id, account.userId, com.armonia.app.data.api.MembershipSelection(song, included)).isSuccessful)
        invalidateMembership()
    }
    private fun invalidateMembership() { membershipRevision.value += 1 }

    // The full song list is what Android Auto browses and searches against and
    // what the Library tab shows. Fetching it is one paginated pass over the whole
    // library, so keep the result briefly instead of repeating that per request.
    private val songsMutex = Mutex()
    private data class SongsCache(val owner:String,val at:Long,val songs:List<Song>)
    @Volatile private var songsCache: SongsCache? = null

    fun invalidateCaches() { songsCache = null }

    // App-lifetime scope: work started here (e.g. a delete) survives the screen
    // that started it being closed.
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val _messages = MutableSharedFlow<String>(extraBufferCapacity = 8)
    /** Errors from background library work, for the app-wide snackbar. */
    val messages: SharedFlow<String> = _messages.asSharedFlow()

    // songId -> when it was deleted. Hidden from listings for RECENTLY_DELETED_MS.
    private val recentlyDeleted = java.util.concurrent.ConcurrentHashMap<String, Long>()

    init {
        scope.launch { prefs.authState.collect { invalidateCaches(); recentlyDeleted.clear() } }
        // The copies of the account in use, read again when the account or session changes (logging out clears them).
        scope.launch {
            prefs.authState.map { it.namespace to it.sessionId.isNotBlank() }.distinctUntilChanged().collect { (namespace, _) ->
                copiesLock.withLock { copies = PreviewCopies.decode(prefs.previewCopies(), namespace) }
                invalidateMembership()  // A ✓ asked before they were read is asked again.
            }
        }
    }

    /**
     * Deletes a track without making the caller wait: callers remove it from their
     * list first, the server delete runs in the app scope, and on failure [restore]
     * puts it back (on the main thread) and the reason goes to the snackbar.
     */
    fun deleteInBackground(song: Song, restore: () -> Unit = {}) {
        val account = prefs.cachedAuth
        songsCache = songsCache?.let { it.copy(songs=it.songs.filter { s -> s.id != song.id }) }
        scope.launch {
            val result = deleteTrack(song.id, account)
            if (account != prefs.cachedAuth) return@launch
            if (result.isSuccess) {
                // Keep it hidden for a while even if Navidrome is slow to drop it, so
                // the refresh below can't bring a deleted song back.
                recentlyDeleted[song.id] = System.currentTimeMillis()
                // The server only answers once Navidrome has dropped the track, so
                // this refresh comes back without it.
                notifyLibraryChanged()
            } else {
                invalidateCaches()
                withContext(Dispatchers.Main) { restore() }
                _messages.tryEmit("No se pudo eliminar «${song.title}»: ${result.exceptionOrNull()?.message ?: "error desconocido"}")
            }
        }
    }

    private suspend fun <T> handleResponse(call: suspend () -> retrofit2.Response<com.armonia.app.data.api.SubsonicResponseWrapper>): Result<SubsonicResponse> {
        return try {
            val account = prefs.cachedAuth
            val response = call()
            check(account == prefs.cachedAuth) { "Account changed" }
            if (response.isSuccessful) {
                val wrapper = response.body()
                if (wrapper?.response?.status == "ok") {
                    Result.success(wrapper.response)
                } else {
                    Result.failure(Exception(wrapper?.response?.error?.message ?: "Error desconocido del servidor"))
                }
            } else {
                Result.failure(Exception("HTTP error: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun getArtists(): Result<SubsonicResponse> = handleResponse<SubsonicResponse> { api.getLibrary("armoniaArtists") }

    suspend fun getArtist(id: String): Result<SubsonicResponse> = handleResponse<SubsonicResponse> {
        api.getLibrary("armoniaArtist", mapOf("id" to id))
    }

    suspend fun getAlbum(id: String): Result<SubsonicResponse> = handleResponse<SubsonicResponse> {
        api.getLibrary("getAlbum", mapOf("id" to id))
    }

    /**
     * Loads the entire song library by paginating Subsonic's `search3` endpoint.
     * Mirrors the web app's Library.svelte fetchAll() implementation.
     */
    suspend fun getSongs(pageSize: Int = 500, forceRefresh: Boolean = false): Result<List<Song>> {
        if (!forceRefresh) cachedSongs()?.let { return Result.success(it.withoutRecentlyDeleted { s -> s.id }) }
        return songsMutex.withLock {
            val owner=prefs.accountNamespace
            if (!forceRefresh) cachedSongs()?.let { return Result.success(it.withoutRecentlyDeleted { s -> s.id }) }
            fetchAllSongs(pageSize)
                .map { all -> all.withoutRecentlyDeleted { s -> s.id } }
                .onSuccess { songsCache = SongsCache(owner,System.currentTimeMillis(),it); playlistCache.saveSongs(owner, it) }
        }
    }

    suspend fun savedSongMetadata(account: String) = playlistCache.songs(account)

    private fun cachedSongs(): List<Song>? =
        songsCache?.let { cache -> cache.songs.takeIf {
            cache.owner==prefs.accountNamespace && System.currentTimeMillis()-cache.at<SONGS_CACHE_TTL_MS
        } }

    private suspend fun fetchAllSongs(pageSize: Int): Result<List<Song>> {
        return try {
            val account = prefs.cachedAuth
            val all = mutableListOf<Song>()
            var offset = 0
            while (true) {
                val response = api.getLibrary(
                    "search3",
                    mapOf(
                        "query" to " ",
                        "songCount" to pageSize.toString(),
                        "songOffset" to offset.toString(),
                        "artistCount" to "0",
                        "albumCount" to "0",
                    )
                )
                if (!response.isSuccessful) {
                    return Result.failure(Exception("HTTP error: ${response.code()}"))
                }
                val sr = response.body()?.response
                if (sr?.status != "ok") {
                    return Result.failure(
                        Exception(sr?.error?.message ?: "Error desconocido del servidor")
                    )
                }
                check(account == prefs.cachedAuth) { "Account changed" }
                val batch = sr.searchResult3?.song ?: emptyList()
                all.addAll(batch)
                if (batch.size < pageSize) break
                offset += pageSize
            }
            Result.success(all)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun getFavorites(): Result<SubsonicResponse> = handleResponse<SubsonicResponse> {
        api.getLibrary("getStarred")
    }.map { r ->
        r.starred?.let { st -> r.copy(starred = st.copy(song = st.song.withoutRecentlyDeleted { it.id })) } ?: r
    }

    /**
     * Subsonic getAlbumList2. [type] is e.g. "newest", "recent", "frequent",
     * "alphabeticalByName"; the server caps [size] at 500 per call.
     */
    suspend fun getAlbumList(type: String, size: Int = 100, offset: Int = 0): Result<SubsonicResponse> =
        handleResponse<SubsonicResponse> {
            api.getAlbumPage(
                "getAlbumList2",
                mapOf("type" to type, "size" to size.toString(), "offset" to offset.toString()),
            )
        }

    suspend fun star(id: String): Result<SubsonicResponse> = handleResponse<SubsonicResponse> {
        api.getLibrary("star", mapOf("id" to id))
    }.onSuccess { invalidateMembership() }

    suspend fun unstar(id: String): Result<SubsonicResponse> = handleResponse<SubsonicResponse> {
        api.getLibrary("unstar", mapOf("id" to id))
    }.onSuccess { invalidateMembership() }

    /** Subsonic scrobble: submission=false is "now playing", true records the play. */
    suspend fun scrobble(id: String, submission: Boolean): Result<SubsonicResponse> = handleResponse<SubsonicResponse> {
        api.getLibrary("scrobble", mapOf("id" to id, "submission" to submission.toString()))
    }

    suspend fun deleteTrack(id: String, account: AuthSnapshot = prefs.cachedAuth): Result<Unit> {
        return try {
            check(account == prefs.cachedAuth) { "Account changed" }
            val response = api.deleteTrack(id, account)
            if (response.isSuccessful) Result.success(Unit)
            else Result.failure(Exception(serverMessage(response) ?: "HTTP error: ${response.code()}"))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /** The middleware's `{"detail": "..."}` error text, when there is one. */
    private fun serverMessage(response: retrofit2.Response<*>): String? =
        runCatching {
            com.google.gson.JsonParser.parseString(response.errorBody()?.string().orEmpty())
                .asJsonObject.get("detail")?.asString
        }.getOrNull()

    private fun <T> List<T>.withoutRecentlyDeleted(id: (T) -> String): List<T> {
        if (recentlyDeleted.isEmpty()) return this
        val now = System.currentTimeMillis()
        recentlyDeleted.entries.removeIf { now - it.value > RECENTLY_DELETED_MS }
        return filterNot { recentlyDeleted.containsKey(id(it)) }
    }

    // ── Playlists ────────────────────────────────────────────────────────────

    /** Every answer of the server is kept on the phone: see [cachedPlaylists]. */
    suspend fun getPlaylists(): Result<SubsonicResponse> {
        val owner = prefs.accountNamespace
        return handleResponse<SubsonicResponse> { api.getLibrary("getPlaylists") }
            .onSuccess {
                val playlists = it.playlists?.playlist.orEmpty()
                playlistCache.saveList(owner, playlists)
                keepPlaylistContents(owner, playlists)
            }
    }

    private var contentsJob: kotlinx.coroutines.Job? = null

    /**
     * Keeps the songs of every playlist on the phone too, so a playlist never opened here can
     * still be opened without a connection. Quietly, one at a time, and only those that are
     * missing or have changed since they were saved; stops at the first failure.
     */
    private fun keepPlaylistContents(owner: String, playlists: List<com.armonia.app.data.api.Playlist>) {
        contentsJob?.cancel()
        contentsJob = scope.launch {
            for (playlist in playlists) {
                if (owner != prefs.accountNamespace) return@launch
                val saved = playlistCache.playlist(playlist.id)
                if (saved != null && saved.changed == playlist.changed && saved.songCount == playlist.songCount) continue
                if (getPlaylist(playlist.id).isFailure) return@launch
                kotlinx.coroutines.delay(150)
            }
        }
    }

    suspend fun getPlaylist(id: String): Result<SubsonicResponse> {
        val owner = prefs.accountNamespace
        return handleResponse<SubsonicResponse> { api.getLibrary("getPlaylist", mapOf("id" to id)) }
            .onSuccess { it.playlist?.let { playlist -> playlistCache.savePlaylist(owner, playlist) } }
    }

    /** The playlists as last seen on this phone, to show at once while the server answers. */
    suspend fun cachedPlaylists(): List<com.armonia.app.data.api.Playlist>? = playlistCache.list()

    suspend fun cachedPlaylist(id: String): com.armonia.app.data.api.PlaylistDetail? = playlistCache.playlist(id)

    suspend fun forgetCachedPlaylists() = playlistCache.clear()

    suspend fun setRating(id: String, rating: Int): Result<SubsonicResponse> = handleResponse<SubsonicResponse> {
        require(rating in 0..5)
        api.getLibrary("setRating", mapOf("id" to id, "rating" to rating.toString()))
    }

    /** Picker additions are optimistic and idempotent; intentional repeats already present survive. */
    suspend fun addUniqueToPlaylist(id: String, songId: String): Result<Unit> = runCatching {
        val account = prefs.cachedAuth
        val current = getPlaylist(id).getOrThrow().playlist ?: error("Playlist no disponible")
        val expected = current.entry.orEmpty().map { it.id }
        if (songId !in expected) {
            check(account == prefs.cachedAuth) { "La cuenta ha cambiado" }
            val response = api.editPlaylist(id, account.userId, com.armonia.app.data.api.PlaylistEdit(expected, expected + songId))
            check(response.isSuccessful) { if (response.code() == 409) "La playlist ha cambiado; vuelve a intentarlo" else "No se pudo guardar (${response.code()})" }
        }
    }.onSuccess { invalidateMembership() }

    /** Undo of one addition: drops the last occurrence only, and only if nobody changed the list meanwhile. */
    suspend fun removeLastFromPlaylist(id: String, songId: String): Result<Unit> = runCatching {
        val account = prefs.cachedAuth
        val current = getPlaylist(id).getOrThrow().playlist ?: error("Playlist no disponible")
        val expected = current.entry.orEmpty().map { it.id }
        val at = expected.lastIndexOf(songId)
        if (at >= 0) {
            check(account == prefs.cachedAuth) { "La cuenta ha cambiado" }
            val response = api.editPlaylist(id, account.userId, com.armonia.app.data.api.PlaylistEdit(expected, expected.filterIndexed { i, _ -> i != at }))
            check(response.isSuccessful) { if (response.code() == 409) "La playlist ha cambiado; vuelve a intentarlo" else "No se pudo deshacer (${response.code()})" }
        }
    }.onSuccess { invalidateMembership() }

    suspend fun createPlaylist(name: String): Result<Unit> {
        return try {
            val response = api.createPlaylist(name)
            if (response.isSuccessful) Result.success(Unit)
            else Result.failure(Exception("HTTP error: ${response.code()}"))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun renamePlaylist(id: String, name: String): Result<Unit> {
        return try {
            val response = api.updatePlaylist(playlistId = id, name = name)
            if (response.isSuccessful) Result.success(Unit)
            else Result.failure(Exception("HTTP error: ${response.code()}"))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun deletePlaylist(id: String): Result<Unit> {
        return try {
            val response = api.deletePlaylist(id)
            if (response.isSuccessful) { invalidateMembership(); Result.success(Unit) }
            else Result.failure(Exception("HTTP error: ${response.code()}"))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun addSongsToPlaylist(playlistId: String, songIds: List<String>): Result<Unit> {
        return try {
            val response = api.updatePlaylist(playlistId = playlistId, songIdsToAdd = songIds)
            if (response.isSuccessful) { invalidateMembership(); Result.success(Unit) }
            else Result.failure(Exception("HTTP error: ${response.code()}"))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun removeSongFromPlaylist(playlistId: String, songIndex: Int): Result<Unit> {
        return try {
            val response = api.updatePlaylist(playlistId = playlistId, songIndexToRemove = songIndex)
            if (response.isSuccessful) { invalidateMembership(); Result.success(Unit) }
            else Result.failure(Exception("HTTP error: ${response.code()}"))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    companion object {
        private const val SONGS_CACHE_TTL_MS = 3 * 60_000L
        private const val RECENTLY_DELETED_MS = 2 * 60_000L
    }

    fun getCoverArtUrl(id: String, size: Int = 300): String =
        // Pass full URLs through unchanged (e.g. a YouTube thumbnail on a preview
        // track); only wrap bare Subsonic cover-art ids. Always the size asked for: one name per cover and
        // size, so the phone keeps it and never fetches it again (see CoverSizes).
        prefs.cachedAuth.coverArtUrl(id, size)

    fun getStreamUrl(trackId: String): String = when {
        trackId.startsWith("preview|") -> previewUrl(trackId.removePrefix("preview|"))
        trackId.startsWith("external|") -> "${cachedServerUrl.trimEnd('/')}/api/external/${android.net.Uri.encode(trackId.removePrefix("external|"))}"
        else -> "${cachedServerUrl.trimEnd('/')}/api/stream/${android.net.Uri.encode(trackId)}"
    }

    /** Synchronous preview-stream URL for a YouTube videoId (mirrors getStreamUrl). */
    fun previewUrl(videoId: String): String =
        "${cachedServerUrl.trimEnd('/')}/api/preview/${android.net.Uri.encode(videoId)}"

    suspend fun getPreviewUrl(videoId: String): String {
        val baseUrl = prefs.serverUrl.first() ?: ""
        return "${baseUrl.trimEnd('/')}/api/preview/${android.net.Uri.encode(videoId)}"
    }
}
