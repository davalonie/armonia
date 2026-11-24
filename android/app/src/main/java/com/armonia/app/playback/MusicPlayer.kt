package com.armonia.app.playback

import android.content.ComponentName
import android.content.Context
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.Timeline
import androidx.media3.datasource.HttpDataSource
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import com.google.common.util.concurrent.MoreExecutors
import com.google.gson.Gson
import com.armonia.app.homelab.checked
import com.armonia.app.data.api.Song
import com.armonia.app.homelab.asMusicTrack
import com.armonia.app.data.repository.LibraryRepository
import com.armonia.app.data.repository.PreferencesRepository
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import javax.inject.Inject
import javax.inject.Singleton

enum class RepeatMode { OFF, ONE, ALL }
private const val CONTINUE_BEFORE_END_MS = 25_000L

/** Active sleep timer: pause at [endsAtMs] (epoch), or when the current track ends. */
data class SleepTimer(val endsAtMs: Long? = null, val atTrackEnd: Boolean = false) {
    val isActive: Boolean get() = endsAtMs != null || atTrackEnd
}

data class PlaybackProgress(val positionMs: Long, val durationMs: Long, val bufferedMs: Long = 0L)

@Singleton
class MusicPlayer @Inject constructor(
    @ApplicationContext private val context: Context,
    private val libraryRepo: LibraryRepository,
    private val prefs: PreferencesRepository,
    private val gson: Gson,
    val routeGuard: RoutePauseGuard,
    private val musicApi: com.armonia.app.homelab.MusicApi,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var controller: MediaController? = null
    private var progressJob: Job? = null
    val playingPlaylistKind: String? get() = playlistContext?.kind
    private var playlistContext: com.armonia.app.homelab.PlaylistContext? = null
    private var auditionSnapshot: SavedQueue? = null
    private var auditionAccount: String? = null
    private var auditionShuffle = false
    private var auditionRepeat = Player.REPEAT_MODE_OFF
    private var auditionResume = false
    private var pendingPlay: (() -> Unit)? = null

    // ── State flows ──────────────────────────────────────────────────────────

    private val _queue = MutableStateFlow<List<Song>>(emptyList())
    val queue: StateFlow<List<Song>> = _queue.asStateFlow()

    private val _currentIndex = MutableStateFlow(-1)
    val currentIndex: StateFlow<Int> = _currentIndex.asStateFlow()

    val currentSong: StateFlow<Song?> = combine(_queue, _currentIndex) { q, i ->
        q.getOrNull(i)
    }.stateIn(scope, SharingStarted.Eagerly, null)

    val isCurrentLiked: StateFlow<Boolean> = currentSong
        .map { song -> !song?.starred.isNullOrEmpty() }
        .stateIn(scope, SharingStarted.Eagerly, false)

    private val _isPlaying = MutableStateFlow(false)
    val isPlaying: StateFlow<Boolean> = _isPlaying.asStateFlow()

    private val _shuffleOn = MutableStateFlow(false)
    val shuffleOn: StateFlow<Boolean> = _shuffleOn.asStateFlow()

    private val _repeatMode = MutableStateFlow(RepeatMode.OFF)
    val repeatMode: StateFlow<RepeatMode> = _repeatMode.asStateFlow()

    private val _progress = MutableStateFlow(PlaybackProgress(0L, 0L))
    val progress: StateFlow<PlaybackProgress> = _progress.asStateFlow()

    /** The player is waiting for audio (start, seek or rebuffer), as opposed to paused. */
    private val _buffering = MutableStateFlow(false)
    val buffering: StateFlow<Boolean> = _buffering.asStateFlow()

    /** Id of the song being previewed for ten seconds, or null. One preview at a time. */
    private val _auditionId = MutableStateFlow<String?>(null)
    val auditionId: StateFlow<String?> = _auditionId.asStateFlow()

    /** Where the queue came from ("Playlist · name"), when the screen that started it said so. */
    private val _playingFrom = MutableStateFlow<String?>(null)
    val playingFrom: StateFlow<String?> = _playingFrom.asStateFlow()

    /** Id of the playlist the queue was started from, so its screen can show Pause instead of Play. */
    private val _playingPlaylistId = MutableStateFlow<String?>(null)
    val playingPlaylistId: StateFlow<String?> = _playingPlaylistId.asStateFlow()

    /**
     * Queue indices in the order they will actually play — the linear queue, or the
     * player's shuffle order when shuffle is on. The queue sheet renders this so
     * "up next" is truthful.
     */
    private val _playOrder = MutableStateFlow<List<Int>>(emptyList())
    val playOrder: StateFlow<List<Int>> = _playOrder.asStateFlow()

    /** Queue indices of the songs queued by hand (see HandPickedQueue); read from the player's own queue. */
    private val _handPicked = MutableStateFlow<Set<Int>>(emptySet())
    val handPicked: StateFlow<Set<Int>> = _handPicked.asStateFlow()

    private fun updatePlayOrder() {
        val c = controller ?: return
        val timeline = c.currentTimeline
        if (timeline.isEmpty) {
            _playOrder.value = emptyList()
            return
        }
        _playOrder.value = timeline.playOrder(c.shuffleModeEnabled)
    }

    // ── Sleep timer ─────────────────────────────────────────────────────────

    private val _sleepTimer = MutableStateFlow(SleepTimer())
    val sleepTimer: StateFlow<SleepTimer> = _sleepTimer.asStateFlow()
    private var sleepJob: Job? = null

    fun setSleepTimer(minutes: Int) {
        sleepJob?.cancel()
        val endsAt = System.currentTimeMillis() + minutes * 60_000L
        _sleepTimer.value = SleepTimer(endsAtMs = endsAt)
        sleepJob = scope.launch {
            delay(minutes * 60_000L)
            controller?.pause()
            _sleepTimer.value = SleepTimer()
        }
    }

    fun setSleepAtTrackEnd() {
        sleepJob?.cancel()
        sleepJob = null
        _sleepTimer.value = SleepTimer(atTrackEnd = true)
    }

    fun cancelSleepTimer() {
        sleepJob?.cancel()
        sleepJob = null
        _sleepTimer.value = SleepTimer()
    }

    /** Human-readable reason the last playback attempt failed; null once dismissed. */
    private val _playbackError = MutableStateFlow<String?>(null)
    val playbackError: StateFlow<String?> = _playbackError.asStateFlow()

    fun dismissPlaybackError() { _playbackError.value = null }
    private var reconnecting = false

    // ── «Continuar con musica similar» ───────────────────────────────────────
    // While the last song of the queue plays out (repeat off), a small batch of related songs
    // is appended behind it. Appending ahead keeps the transition seamless in the background,
    // on Bluetooth and in Android Auto. Pause, stop, logout or a lost connection never ask.

    private val _continueSimilar = MutableStateFlow(true)
    val continueSimilar: StateFlow<Boolean> = _continueSimilar.asStateFlow()
    /** Ids of queue entries added automatically; the UI labels them «Musica similar». */
    private val _autoSongs = MutableStateFlow<Set<String>>(emptySet())
    val autoSongs: StateFlow<Set<String>> = _autoSongs.asStateFlow()
    private var continuationEpoch = 0L
    private var continuationAsked: String? = null
    private var continuationJob: Job? = null
    private val heard = ArrayDeque<String>()
    private val dismissed = ArrayDeque<String>()

    private fun trackKey(song: Song) = song.asMusicTrack().let { "${it.source}:${it.sourceId}" }

    private fun resetContinuation(forget: Boolean = false) {
        continuationEpoch++
        continuationAsked = null
        continuationJob?.cancel()
        _autoSongs.value = emptySet()
        if (forget) { heard.clear(); dismissed.clear() }
    }

    fun refreshPlaybackSettings() {
        val owner = prefs.cachedUserId
        if (owner.isBlank()) return
        scope.launch {
            runCatching { musicApi.playbackSettings().checked() }
                .onSuccess { if (owner == prefs.cachedUserId) _continueSimilar.value = it.continueSimilar }
        }
    }

    /** Saves the per-user option. Returns false (and keeps the old value) when the server refuses. */
    suspend fun setContinueSimilar(on: Boolean): Boolean {
        val owner = prefs.cachedUserId
        val saved = runCatching {
            musicApi.savePlaybackSettings(owner, com.armonia.app.homelab.PlaybackSettings(on)).checked()
        }.isSuccess
        if (!saved || owner != prefs.cachedUserId) return false
        _continueSimilar.value = on
        continuationEpoch++
        continuationAsked = null
        continuationJob?.cancel()
        if (!on) dropUpcomingSuggestions()
        return true
    }

    private var lastPrepared = ""

    /**
     * Asks the server to have one external song ready (address resolved and audio in its
     * memory) before the press that is likely to come next; it is not counted as a listen.
     */
    fun prepareSource(videoId: String) {
        if (videoId.isBlank() || videoId == lastPrepared) return
        lastPrepared = videoId
        val owner = prefs.cachedUserId
        scope.launch { runCatching { musicApi.prepare(videoId, owner) } }
    }

    /** Suggestions not yet played leave the queue; the one sounding now is the user's to stop. */
    private fun dropUpcomingSuggestions() {
        val c = controller ?: return
        val auto = _autoSongs.value
        for (i in _queue.value.indices.reversed()) {
            if (i != c.currentMediaItemIndex && _queue.value[i].id in auto) removeFromQueue(i)
        }
        _autoSongs.value = _autoSongs.value.intersect(_queue.value.map { it.id }.toSet())
    }

    private fun maybeContinue(atEnd: Boolean = false) {
        val c = controller ?: return
        if (!_continueSimilar.value || auditionSnapshot != null) return
        if (c.repeatMode != Player.REPEAT_MODE_OFF || c.hasNextMediaItem() || !c.playWhenReady || (!atEnd && !c.isPlaying)) return
        val duration = c.duration
        if (!atEnd && (duration <= 0 || duration - c.currentPosition > CONTINUE_BEFORE_END_MS)) return
        val current = _queue.value.getOrNull(c.currentMediaItemIndex) ?: return
        val situation = "$continuationEpoch:${c.currentMediaItemIndex}:${_queue.value.size}"
        if (continuationAsked == situation) return // Once per end of queue, however many ticks.
        continuationAsked = situation
        val epoch = continuationEpoch
        val owner = prefs.cachedUserId
        val at = c.currentMediaItemIndex
        val artists = (listOf(current) + _queue.value.subList((at - 2).coerceAtLeast(0), at).reversed())
            .map { it.artist }.filter { it.isNotBlank() }.distinct().take(3)
        val known = (_queue.value.map(::trackKey) + heard + dismissed).distinct().takeLast(600)
        continuationJob = scope.launch {
            val batch = runCatching {
                musicApi.continueSimilar(owner, com.armonia.app.homelab.ContinueRequest(artists, known, current.id.takeIf { it.startsWith("preview|") }?.substringAfter('|'))).checked()
            }.getOrNull() ?: return@launch // Any failure: the queue simply ends.
            val now = controller ?: return@launch
            // Whatever the user did while the answer was on its way wins over the suggestion.
            if (epoch != continuationEpoch || owner != prefs.cachedUserId || !batch.enabled) return@launch
            if (!_continueSimilar.value || auditionSnapshot != null) return@launch
            if (now.currentMediaItemIndex != at || _queue.value.getOrNull(at)?.id != current.id) return@launch
            if (now.repeatMode != Player.REPEAT_MODE_OFF || now.hasNextMediaItem()) return@launch
            val queued = (_queue.value.map(::trackKey) + dismissed).toSet()
            val fresh = batch.items.distinctBy { "${it.track.source}:${it.track.sourceId}" }
                .filter { "${it.track.source}:${it.track.sourceId}" !in queued }
                .map { item ->
                    val cover = item.cover ?: when (item.track.source) {
                        "navidrome" -> libraryRepo.getCoverArtUrl(item.track.sourceId, 300)
                        "youtube" -> "https://i.ytimg.com/vi/${item.track.sourceId}/mqdefault.jpg"
                        else -> null
                    }
                    item.track.toSong().copy(coverArt = cover)
                }
            if (fresh.isEmpty()) return@launch
            _autoSongs.value = _autoSongs.value + fresh.map { it.id }
            _queue.value = _queue.value + fresh
            val ended = now.playbackState == Player.STATE_ENDED
            val nextIndex = now.mediaItemCount
            now.addMediaItems(fresh.map { it.toMediaItem() })
            if (ended && now.playWhenReady) { now.seekToDefaultPosition(nextIndex); now.play() }
        }
    }

    // ── Init ─────────────────────────────────────────────────────────────────

    init {
        scope.launch {
            var previous = prefs.accountNamespace
            prefs.authState.collect { auth ->
                if (auth.sessionId.isBlank() || auth.namespace != previous) {
                    // Drop private snapshots before a late screen disposal can restore them.
                    cancelSleepTimer()
                    auditionSnapshot = null
                    auditionAccount = null
                    _auditionId.value = null
                    playlistContext = null
                    _playingFrom.value = null
                    _playingPlaylistId.value = null
                    pendingPlay = null
                    routeGuard.disconnect()
                    resetContinuation(forget = true)
                    _continueSimilar.value = true
                }
                if (auth.sessionId.isNotBlank()) refreshPlaybackSettings()
                previous = auth.namespace
            }
        }
        val token = SessionToken(context, ComponentName(context, PlaybackService::class.java))
        val future = MediaController.Builder(context, token).buildAsync()
        future.addListener({
            controller = future.get()
            wireListeners()
            val pending = pendingPlay
            if (pending != null) {
                pendingPlay = null
                pending.invoke()
            } else {
                restoreLastTrack()
            }
        }, MoreExecutors.directExecutor())
    }

    private fun wireListeners() {
        controller?.addListener(object : Player.Listener {
            override fun onIsPlayingChanged(playing: Boolean) {
                _isPlaying.value = playing
                if (playing && reconnecting) { reconnecting = false; _playbackError.value = null }
                if (playing && auditionSnapshot == null) playlistContext?.let { context ->
                    val owner = prefs.cachedUserId
                    scope.launch { runCatching { musicApi.rememberPlaylist(owner,context) } }
                }
                if (playing) startProgressLoop() else stopProgressLoop()
            }

            override fun onPlaybackStateChanged(playbackState: Int) {
                _buffering.value = playbackState == Player.STATE_BUFFERING
                // A finished preview hands the player back to what was there before it.
                if (playbackState == Player.STATE_ENDED) {
                    when {
                        auditionSnapshot != null -> stopAudition()
                        _sleepTimer.value.atTrackEnd -> {
                            controller?.pause()
                            cancelSleepTimer()
                        }
                        else -> maybeContinue(atEnd = true)
                    }
                }
            }

            override fun onPositionDiscontinuity(
                oldPosition: Player.PositionInfo, newPosition: Player.PositionInfo, reason: Int,
            ) {
                // The progress loop only runs while playing: without this, a seek made while
                // paused (here, from the notification or a headset) left the bar where it was.
                snapshotProgress()
            }

            override fun onTimelineChanged(timeline: Timeline, reason: Int) {
                syncQueueFromController()
                updatePlayOrder()
            }

            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
                if (_sleepTimer.value.atTrackEnd && reason == Player.MEDIA_ITEM_TRANSITION_REASON_AUTO) {
                    controller?.pause()
                    _sleepTimer.value = SleepTimer()
                }
                syncQueueFromController()
                updatePlayOrder()
                saveLastTrack()
                _queue.value.getOrNull(_currentIndex.value)?.let {
                    heard.addLast(trackKey(it)); if (heard.size > 300) heard.removeFirst()
                }
            }

            override fun onShuffleModeEnabledChanged(shuffleModeEnabled: Boolean) {
                _shuffleOn.value = shuffleModeEnabled
                updatePlayOrder()
            }

            override fun onRepeatModeChanged(repeatMode: Int) {
                _repeatMode.value = when (repeatMode) {
                    Player.REPEAT_MODE_ONE -> RepeatMode.ONE
                    Player.REPEAT_MODE_ALL -> RepeatMode.ALL
                    else -> RepeatMode.OFF
                }
            }

            override fun onPlayerError(error: PlaybackException) {
                val status = (error.cause as? HttpDataSource.InvalidResponseCodeException)?.responseCode
                reconnecting = controller?.playWhenReady == true && PlaybackRecovery.retryable(error.errorCode, status)
                // The service resumes a lost connection by itself (PlaybackRecovery); say so
                // instead of reporting the song as failed. Any other failure is shown as is.
                _playbackError.value = if (reconnecting) "Se perdio la conexion con el servidor. Reintentando…"
                    else describePlaybackError(error)
            }
        })
    }

    private fun describePlaybackError(error: PlaybackException): String {
        val song = currentSong.value
        val http = error.cause as? HttpDataSource.InvalidResponseCodeException
        return when {
            http != null && song?.isPreview() == true && http.responseCode == 502 ->
                "El servidor no ha podido obtener esta cancion de la fuente externa"
            http != null && http.responseCode == 401 -> "La sesion ha caducado; vuelve a iniciar sesion"
            http != null && http.responseCode == 404 -> "Esta cancion ya no esta en el servidor"
            http != null -> "No se pudo reproducir (HTTP ${http.responseCode})"
            error.cause is HttpDataSource.HttpDataSourceException -> "Error de red; comprueba la conexion"
            else -> "No se pudo reproducir (${error.errorCodeName})"
        }
    }

    /**
     * Mirrors the controller's timeline into [_queue] / [_currentIndex]. When playback is
     * driven externally — e.g. Android Auto sets a fresh queue directly on the session —
     * our Song list would otherwise be stale, leaving the phone's mini/expanded player
     * blank or wrong. We detect divergence by comparing real track ids and rebuild Songs
     * from each item's metadata + extras only when needed (so phone-initiated playback,
     * which already populated [_queue], is a no-op).
     */
    private fun syncQueueFromController() {
        val c = controller ?: return
        val count = c.mediaItemCount
        if (count == 0) {
            if (_queue.value.isNotEmpty()) _queue.value = emptyList()
            _currentIndex.value = -1
            _handPicked.value = emptySet()
            return
        }
        val controllerIds = (0 until count).map { realTrackId(c.getMediaItemAt(it).mediaId) }
        if (controllerIds != _queue.value.map { it.id }) {
            _queue.value = (0 until count).map { songFromMediaItem(c.getMediaItemAt(it)) }
        }
        _currentIndex.value = c.currentMediaItemIndex
        _handPicked.value = c.handPickedIndices()
    }

    private fun realTrackId(mediaId: String): String =
        if (mediaId.startsWith("track|")) mediaId.split('|', limit=4).last() else mediaId

    /** Rebuilds a Song from a session MediaItem (metadata + the extras we attach when browsing). */
    private fun songFromMediaItem(item: MediaItem): Song {
        val md = item.mediaMetadata
        val ex = md.extras
        return Song(
            id = realTrackId(item.mediaId),
            parent = null,
            title = md.title?.toString() ?: "",
            album = md.albumTitle?.toString(),
            artist = md.artist?.toString() ?: "",
            track = null,
            year = null,
            genre = null,
            coverArt = ex?.getString("coverArt"),
            duration = ex?.getInt("duration") ?: 0,
            bitRate = null,
            contentType = null,
            suffix = null,
            size = null,
            albumId = ex?.getString("albumId"),
            artistId = ex?.getString("artistId"),
            type = null,
            created = null,
            starred = ex?.getString("starred"),
            musicTrack = ex?.getString("musicTrack")?.let { runCatching { gson.fromJson(it,com.armonia.app.homelab.MusicTrack::class.java) }.getOrNull() },
        )
    }

    private fun startProgressLoop() {
        progressJob?.cancel()
        progressJob = scope.launch {
            while (isActive) {
                snapshotProgress()
                delay(500)
            }
        }
    }

    private fun stopProgressLoop() {
        progressJob?.cancel()
        progressJob = null
        snapshotProgress()
        saveLastTrack()
    }

    private fun snapshotProgress() {
        val c = controller ?: return
        _progress.value = PlaybackProgress(
            positionMs = c.currentPosition.coerceAtLeast(0L),
            durationMs = c.duration.coerceAtLeast(0L),
            bufferedMs = c.bufferedPosition.coerceAtLeast(0L),
        )
        maybeContinue()
    }

    // ── Queue operations ─────────────────────────────────────────────────────

    fun collectionStart(songs: List<Song>): Int =
        if (shuffleOn.value && songs.isNotEmpty()) songs.indices.random() else 0

    fun playQueue(songs: List<Song>, startIndex: Int = 0, requestEpoch: Long = routeGuard.explicitPlay(), playlistId:String?=null, playlistKind:String="local", from: String? = null) {
        if (!routeGuard.permits(requestEpoch)) return
        stopAudition(resume = false)
        val c = controller
        if (c == null) {
            pendingPlay = { playQueue(songs, startIndex, requestEpoch, playlistId, playlistKind, from) }
            return
        }
        if (songs.isEmpty()) return
        playlistContext = playlistId?.let { com.armonia.app.homelab.PlaylistContext(playlistKind,it) }
        _playingFrom.value = from
        _playingPlaylistId.value = playlistId
        val start = startIndex.coerceIn(0, songs.size - 1)
        // As in Spotify, songs queued by hand and not played yet stay queued: after the new first song.
        val carried = carriedOver(c).filter { it.first.id != songs[start].id }
        resetContinuation()
        _queue.value = withCarriedOver(songs, start, carried.map { it.first })
        _currentIndex.value = start
        c.setMediaItems(withCarriedOver(songs.map { it.toMediaItem() }, start,
            carried.map { (song, token) -> song.toMediaItem().handPicked(token) }), start, 0L)
        c.prepare()
        c.play()
    }

    /** The songs queued by hand still to play, in play order, each with its mark (kept for «Deshacer»). */
    private fun carriedOver(c: MediaController): List<Pair<Song, String>> {
        val count = c.mediaItemCount
        if (count == 0) return emptyList()
        val order = c.currentTimeline.playOrder(c.shuffleModeEnabled)
        return handPickedUpcoming(order, c.currentMediaItemIndex, c.handPickedIndices()).mapNotNull { i ->
            val item = c.getMediaItemAt(i)
            val token = item.handPickedToken() ?: return@mapNotNull null
            val song = _queue.value.takeIf { it.size == count }?.getOrNull(i) ?: songFromMediaItem(item)
            song to token
        }
    }

    /**
     * A ten-second audition shares Media3, preserving the normal queue. It ends by itself or with
     * [stopAudition]; with [resumeAfter], music that was playing when it started plays again.
     */
    fun audition(song: Song, resumeAfter: Boolean = false) {
        val c = controller ?: return
        routeGuard.explicitPlay()
        if (auditionSnapshot == null) {
            auditionAccount = prefs.accountNamespace
            auditionSnapshot = SavedQueue(_queue.value,_currentIndex.value.coerceAtLeast(0),c.currentPosition.coerceAtLeast(0),_handPicked.value)
            auditionShuffle = c.shuffleModeEnabled
            auditionRepeat = c.repeatMode
            auditionResume = resumeAfter && c.isPlaying
        }
        _auditionId.value = song.id
        c.pause()
        val start = (song.duration * 500L - 5000L).coerceAtLeast(0)
        val item = song.toMediaItem()
        val extras = android.os.Bundle(item.mediaMetadata.extras ?: android.os.Bundle()).apply { putBoolean("audition",true) }
        c.repeatMode = Player.REPEAT_MODE_OFF
        c.shuffleModeEnabled = false
        c.setMediaItem(item.buildUpon()
            .setMediaMetadata(item.mediaMetadata.buildUpon().setExtras(extras).build())
            .setClippingConfiguration(MediaItem.ClippingConfiguration.Builder()
                .setStartPositionMs(start).setEndPositionMs(start+10000).build()).build())
        c.prepare()
        c.play()
    }

    fun stopAudition(resume: Boolean = true) {
        val saved = auditionSnapshot ?: return
        _auditionId.value = null
        if (auditionAccount != prefs.accountNamespace || prefs.cachedAuth.sessionId.isBlank()) {
            auditionSnapshot = null
            auditionAccount = null
            return
        }
        val c = controller ?: return
        // Only music that was playing, and that nothing paused meanwhile (a call, headphones
        // unplugged: playWhenReady goes false), plays again by itself.
        val playAgain = resume && auditionResume && c.playWhenReady && !routeGuard.blocked && saved.songs.isNotEmpty()
        auditionResume = false
        c.pause()
        if (saved.songs.isEmpty()) c.clearMediaItems()
        else c.setMediaItems(saved.mediaItems(),saved.currentIndex,saved.positionMs)
        c.shuffleModeEnabled = auditionShuffle
        c.repeatMode = auditionRepeat
        c.prepare()
        _queue.value = saved.songs
        _currentIndex.value = if(saved.songs.isEmpty()) -1 else saved.currentIndex
        auditionSnapshot = null
        auditionAccount = null
        if (playAgain) c.play()
    }

    /** A song the user has just put in the queue; shown with an undo for that insertion alone. */
    data class Queued(val song: Song, val next: Boolean, internal val token: String, val atEnd: Boolean = false)

    private val _queued = kotlinx.coroutines.flow.MutableSharedFlow<Queued>(extraBufferCapacity = 8)
    val queued: kotlinx.coroutines.flow.SharedFlow<Queued> = _queued

    /**
     * Takes back one insertion: the entry carrying its mark (HandPicked), wherever it is now.
     * Nothing once it has started playing (that one is the user's to skip) or is gone.
     */
    fun undoQueued(queued: Queued) = undoQueued(queued.token)

    fun undoQueued(token: String) {
        val c = controller ?: return
        val index = (0 until c.mediaItemCount).firstOrNull { c.getMediaItemAt(it).queuedToken() == token }
            ?: return
        if (index == c.currentMediaItemIndex) return
        removeFromQueue(index)
    }

    /** First among the songs queued by hand: right after the one playing. */
    fun playNext(song: Song): String? {
        stopAudition()
        return queueByHand(song, next = true)
    }

    /**
     * As in Spotify: after the song playing and the songs already queued by hand, ahead of the
     * rest of the list (and of suggestions still waiting). An empty queue just plays it.
     */
    fun addToQueue(song: Song): String? {
        stopAudition()
        if (_queue.value.isEmpty() || _currentIndex.value < 0) {
            playQueue(listOf(song), 0)
            return null
        }
        return queueByHand(song, next = false)
    }

    /** «Añadir al final de la cola»: after the whole list, ahead of suggestions still waiting. */
    fun addToEnd(song: Song): String? {
        stopAudition()
        if (_queue.value.isEmpty() || _currentIndex.value < 0) {
            playQueue(listOf(song), 0)
            return null
        }
        val c = controller ?: return null
        val queue = _queue.value
        val auto = _autoSongs.value
        val at = ((c.currentMediaItemIndex + 1).coerceAtLeast(0) until queue.size)
            .firstOrNull { i -> (i until queue.size).all { queue[it].id in auto } } ?: queue.size
        val token = java.util.UUID.randomUUID().toString()
        c.sendCustomCommand(
            androidx.media3.session.SessionCommand(LibrarySessionCallback.CMD_ADD_TO_END, android.os.Bundle.EMPTY),
            android.os.Bundle().apply { putString("song", gson.toJson(song)); putString("token", token); putInt("at", at) })
        _queued.tryEmit(Queued(song, next = false, token = token, atEnd = true))
        return token
    }

    /** The service places it (LibrarySessionCallback.queueByHand): it knows the shuffle order. */
    private fun queueByHand(song: Song, next: Boolean): String? {
        val c = controller ?: return null
        val token = java.util.UUID.randomUUID().toString()
        c.sendCustomCommand(
            androidx.media3.session.SessionCommand(
                if (next) "armonia.PLAY_NEXT" else LibrarySessionCallback.CMD_ADD_TO_QUEUE, android.os.Bundle.EMPTY),
            android.os.Bundle().apply { putString("song", gson.toJson(song)); putString("token", token) })
        if (_queue.value.isEmpty()) return null
        _queued.tryEmit(Queued(song, next, token))
        return token
    }

    fun removeFromQueue(index: Int) {
        val c = controller ?: return
        val list = _queue.value.toMutableList()
        if (index !in list.indices) return
        list.removeAt(index)
        _queue.value = list
        // Removing the current item makes ExoPlayer advance to the next; syncQueueFromController
        // then reconciles _currentIndex from the controller.
        c.removeMediaItem(index)
        _currentIndex.value = when {
            list.isEmpty() -> -1
            index < _currentIndex.value -> _currentIndex.value - 1
            index == _currentIndex.value -> _currentIndex.value.coerceAtMost(list.size - 1)
            else -> _currentIndex.value
        }
    }

    fun moveInQueue(from: Int, to: Int) {
        val c = controller ?: return
        val list = _queue.value.toMutableList()
        if (from !in list.indices || to !in list.indices || from == to) return
        val item = list.removeAt(from)
        list.add(to, item)
        _queue.value = list
        c.moveMediaItem(from, to)
    }

    /** Removes everything that would still play after the current track, in play order. */
    fun clearUpcoming() {
        val c = controller ?: return
        val cur = _currentIndex.value
        if (cur < 0) return
        val order = _playOrder.value.ifEmpty { _queue.value.indices.toList() }
        val pos = order.indexOf(cur)
        if (pos < 0) return
        val upcoming = order.drop(pos + 1).sortedDescending()
        if (upcoming.isEmpty()) return
        val remaining = _queue.value.filterIndexed { i, _ -> i !in upcoming }
        _queue.value = remaining
        upcoming.forEach { c.removeMediaItem(it) }
    }

    // ── Transport controls ──────────────────────────────────────────────────

    fun togglePlayPause() {
        val c = controller ?: return
        if (c.isPlaying) {
            c.pause()
        } else {
            routeGuard.explicitPlay()
            // After a playback error the player sits idle; play() alone does nothing.
            if (c.playbackState == Player.STATE_IDLE) c.prepare()
            c.play()
        }
    }

    fun next() {
        // Skipping a suggestion early means "not this one": it is not offered again in this session.
        currentSong.value?.let { song ->
            if (song.id in _autoSongs.value && (controller?.currentPosition ?: 0L) < 30_000L) {
                dismissed.addLast(trackKey(song)); if (dismissed.size > 200) dismissed.removeFirst()
            }
        }
        val c = controller ?: return
        if (c.hasNextMediaItem()) {
            c.seekToNextMediaItem()
        } else if (_repeatMode.value == RepeatMode.ALL && _queue.value.isNotEmpty()) {
            c.seekTo(0, 0L)
        }
    }

    fun canStep(step: Int): Boolean {
        val c = controller ?: return false
        if (c.mediaItemCount < 2) return false
        return if (step > 0) c.hasNextMediaItem() else c.hasPreviousMediaItem()
    }

    fun step(step: Int): Boolean {
        if (!canStep(step)) return false
        if (step > 0) next() else controller?.seekToPreviousMediaItem()
        return true
    }

    fun prev() {
        val c = controller ?: return
        if (c.currentPosition > 3000) {
            c.seekTo(0L)
        } else if (c.hasPreviousMediaItem()) {
            c.seekToPreviousMediaItem()
        } else {
            c.seekTo(0L)
        }
    }

    fun seekTo(positionMs: Long) {
        controller?.seekTo(positionMs.coerceAtLeast(0L))
        snapshotProgress()
    }

    /**
     * Jumps to a specific item in the current queue without rebuilding it.
     * Used by the queue panel when the user taps an upcoming/past track.
     */
    fun jumpTo(index: Int) {
        val c = controller ?: return
        if (index !in _queue.value.indices) return
        routeGuard.explicitPlay()
        c.seekTo(index, 0L)
        c.play()
    }

    fun seekFraction(fraction: Float) {
        val c = controller ?: return
        val dur = c.duration
        if (dur <= 0) return
        c.seekTo((fraction.coerceIn(0f, 1f) * dur).toLong())
        snapshotProgress()
    }

    fun toggleShuffle() {
        val c = controller ?: return
        c.shuffleModeEnabled = !c.shuffleModeEnabled
    }

    fun toggleRepeat() {
        val c = controller ?: return
        val next = when (_repeatMode.value) {
            RepeatMode.OFF -> RepeatMode.ONE
            RepeatMode.ONE -> RepeatMode.ALL
            RepeatMode.ALL -> RepeatMode.OFF
        }
        c.repeatMode = when (next) {
            RepeatMode.OFF -> Player.REPEAT_MODE_OFF
            RepeatMode.ONE -> Player.REPEAT_MODE_ONE
            RepeatMode.ALL -> Player.REPEAT_MODE_ALL
        }
    }

    /**
     * Toggles the like state of the current song. Optimistically updates the local
     * queue and reverts if the network call fails.
     */
    fun toggleLike() {
        val idx = _currentIndex.value
        val list = _queue.value
        val song = list.getOrNull(idx) ?: return
        if (song.isPreview()) return  // previews aren't in the library
        val wasLiked = !song.starred.isNullOrEmpty()
        val newStarred = if (wasLiked) null else java.time.Instant.now().toString()

        val updated = list.toMutableList()
        updated[idx] = updated[idx].copy(starred = newStarred)
        _queue.value = updated

        scope.launch {
            val result = if (wasLiked) libraryRepo.unstar(song.id) else libraryRepo.star(song.id)
            if (result.isFailure) {
                // Revert
                val reverted = _queue.value.toMutableList()
                if (idx in reverted.indices) {
                    reverted[idx] = reverted[idx].copy(starred = song.starred)
                    _queue.value = reverted
                }
            } else {
                // Keep the library/favorites screens in sync.
                libraryRepo.notifyLibraryChanged()
            }
        }
    }

    /** A favourite changed outside the player (a list or a menu): the queue, notification and car follow it. */
    fun syncStarred(ids: Set<String>, starred: Boolean) {
        val list = _queue.value
        if (list.none { it.id in ids && it.starred.isNullOrEmpty() == starred }) return
        val value = if (starred) java.time.Instant.now().toString() else null
        _queue.value = list.map { if (it.id in ids) it.copy(starred = value) else it }
    }

    fun closePlayer() {
        cancelSleepTimer()
        resetContinuation(forget = true)
        auditionAccount = null
        auditionSnapshot = null
        _auditionId.value = null
        playlistContext = null
        _playingFrom.value = null
        _playingPlaylistId.value = null
        val c = controller ?: return
        c.pause()
        c.clearMediaItems()
        _queue.value = emptyList()
        _currentIndex.value = -1
        _progress.value = PlaybackProgress(0L, 0L)
        scope.launch { prefs.clearLastTrack() }
    }

    // ── Last-track persistence ──────────────────────────────────────────────

    private fun saveLastTrack() {
        if (auditionSnapshot != null) return
        val c = controller
        val songs = _queue.value
        if (songs.isEmpty() || c == null) {
            scope.launch { prefs.clearLastTrack() }
            return
        }
        val saved = SavedQueue(
            songs = songs,
            currentIndex = _currentIndex.value.coerceAtLeast(0),
            positionMs = c.currentPosition.coerceAtLeast(0L),
            handPicked = _handPicked.value,
        )
        scope.launch { prefs.saveLastTrack(saved.toJson(gson)) }
    }

    private fun restoreLastTrack() {
        scope.launch {
            val c = controller ?: return@launch
            // The service may already hold a queue — e.g. Android Auto browsed and
            // started playback before the phone UI was opened. Mirror it instead of
            // replacing it with whatever we saved last time.
            if (c.mediaItemCount > 0) {
                syncQueueFromController()
                return@launch
            }
            val account = prefs.cachedAuth
            val saved = SavedQueue.parse(prefs.lastTrackJson.first(), gson)
            if (account != prefs.cachedAuth || account.sessionId.isBlank()) return@launch
            if (saved == null) {
                prefs.clearLastTrack()
                return@launch
            }
            _queue.value = saved.songs
            _currentIndex.value = saved.currentIndex
            c.setMediaItems(
                saved.mediaItems(),
                saved.currentIndex,
                saved.positionMs,
            )
            c.prepare()
            _progress.value = PlaybackProgress(
                positionMs = saved.positionMs,
                durationMs = saved.songs.getOrNull(saved.currentIndex)?.duration?.times(1000L) ?: 0L,
            )
        }
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    /** A saved queue back as player items, songs queued by hand still marked as such. */
    private fun SavedQueue.mediaItems(): List<MediaItem> = songs.mapIndexed { i, song ->
        song.toMediaItem().let { if (i in handPicked) it.handPicked(java.util.UUID.randomUUID().toString()) else it }
    }

    private fun Song.toMediaItem(): MediaItem {
        // The stream URI is resolved by LibrarySessionCallback.onAddMediaItems
        // via the mediaId (which we set to the Subsonic track id).
        return MediaItem.Builder()
            .setMediaId(id)
            .setMediaMetadata(
                MediaMetadata.Builder()
                    .setTitle(title)
                    .setArtist(artist)
                    .setAlbumTitle(album)
                    // Same fields as LibrarySessionCallback.createPlayableItem: the queue is rebuilt
                    // from these items (songFromMediaItem) whenever the service changes it, e.g. when
                    // a song is queued by hand, and covers and favourites must survive that.
                    .setExtras(android.os.Bundle().apply {
                        putInt("duration",duration)
                        putString("coverArt",coverArt)
                        putString("starred",starred)
                        putString("albumId",albumId)
                        putString("artistId",artistId)
                        putString("musicTrack",gson.toJson(this@toMediaItem.asMusicTrack()))
                    })
                    .build()
            )
            .build()
    }

    /**
     * Plays [songs] starting at [index], but if the song at [index] is already
     * in the current queue, just jumps to it instead of replacing the queue.
     */
    fun playOrJumpTo(songs: List<Song>, index: Int) {
        val songId = songs.getOrNull(index)?.id ?: return
        val queueIndex = _queue.value.indexOfFirst { it.id == songId }
        if (queueIndex >= 0) {
            jumpTo(queueIndex)
        } else {
            playQueue(songs, index)
        }
    }

    // ── Legacy shim ──────────────────────────────────────────────────────────
    // Existing call site: LibraryViewModel.play(song) → keep working as a
    // single-track queue while the UI migrates to playQueue.
    fun play(song: Song) = playQueue(listOf(song), 0)

    /**
     * Streams a YouTube/YT Music track without downloading it. Represented as a
     * synthetic Song whose id (`preview|<videoId>`) resolves to /api/preview, and
     * whose coverArt is the YT thumbnail URL (passed through by getCoverArtUrl).
     */
    fun playPreview(
        videoId: String,
        title: String,
        artist: String,
        thumbnailUrl: String?,
        durationSeconds: Int,
    ) {
        val preview = Song(
            id = "preview|$videoId",
            parent = null,
            title = title,
            album = null,
            artist = artist,
            track = null,
            year = null,
            genre = null,
            coverArt = thumbnailUrl,
            duration = durationSeconds,
            bitRate = null,
            contentType = null,
            suffix = null,
            size = null,
            albumId = null,
            artistId = null,
            type = null,
            created = null,
            starred = null,
        )
        playQueue(listOf(preview), 0)
    }
}

/** A preview (un-downloaded) track isn't in the library, so it can't be liked or deleted. */
fun Song.isPreview(): Boolean = (id.startsWith("preview|") || id.startsWith("external|"))
