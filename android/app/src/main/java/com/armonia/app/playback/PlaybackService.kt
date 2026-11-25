package com.armonia.app.playback

import android.app.ActivityManager
import android.app.ForegroundServiceStartNotAllowedException
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.os.Build
import android.media.AudioManager
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import androidx.core.content.ContextCompat
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.ForwardingSimpleBasePlayer
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.HttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.exoplayer.source.ShuffleOrder
import androidx.media3.session.DefaultMediaNotificationProvider
import androidx.media3.session.MediaLibraryService
import androidx.media3.session.MediaSession
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import com.armonia.app.AppEntry
import com.armonia.app.R
import com.armonia.app.data.repository.LibraryRepository
import com.armonia.app.data.repository.PreferencesRepository
import com.armonia.app.homelab.MusicApi
import com.armonia.app.homelab.checked
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import javax.inject.Inject
import kotlin.random.Random

@UnstableApi
@AndroidEntryPoint
class PlaybackService : MediaLibraryService() {
    @Inject lateinit var routeGuard: RoutePauseGuard
    private var audioManager: AudioManager? = null
    private var routeCallback: AudioDeviceCallback? = null
    private var noisyReceiver: BroadcastReceiver? = null
    private var mediaSession: MediaLibrarySession? = null
    private var nextPreparation: NextTrackPreparation? = null
    private val recovery = PlaybackRecovery()
    private var recoveryJob: Job? = null
    private val preload = NextSongPreload()
    private var preloadJob: Job? = null
    // Whether the listener is going through the queue in order (next, or a song ending), not picking songs.
    private var inOrder = false
    private var expectedNext = C.INDEX_UNSET
    @Inject lateinit var musicApi: MusicApi

    @Inject
    lateinit var callback: LibrarySessionCallback

    @Inject
    lateinit var prefs: PreferencesRepository

    @Inject
    lateinit var streamCache: StreamCache

    @Inject
    lateinit var repository: LibraryRepository

    @Inject lateinit var listenOutbox: com.armonia.app.homelab.ListenOutbox

    @Inject lateinit var network: NetworkMonitor

    @Inject lateinit var notices: PlaybackNotices

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    // ExoPlayer must only be touched from the thread it was created on (main).
    private val playerScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    override fun onCreate() {
        super.onCreate()

        val notificationProvider = DefaultMediaNotificationProvider(this)
        notificationProvider.setSmallIcon(R.drawable.ic_armonia_notification)
        setMediaNotificationProvider(notificationProvider)

        val player = ExoPlayer.Builder(this)
            // Route every stream through the on-device cache (see StreamCache).
            // Songs check every 64 KB whether to go on loading, so the limit below holds (SongMediaSourceFactory).
            .setMediaSourceFactory(streamCache.dataSourceFactory().let { source ->
                SongMediaSourceFactory(source, DefaultMediaSourceFactory(this).setDataSourceFactory(source))
            })
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
                    .setUsage(C.USAGE_MEDIA)
                    .build(),
                true,
            )
            .setHandleAudioBecomingNoisy(true)
            // At most 30 s ahead on mobile data (see DataSavingLoadControl).
            .setLoadControl(DataSavingLoadControl())
            // Keep the CPU and Wi-Fi awake while a stream plays with the screen off; without
            // it the radio may doze between buffer refills and the song stops half-way.
            .setWakeMode(C.WAKE_MODE_NETWORK)
            .build()

        val sessionActivity = PendingIntent.getActivity(
            this,
            0,
            AppEntry.intent(this),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

        // On Android 15 a cold service must be in the foreground before ExoPlayer
        // requests audio focus. A car or Bluetooth controller can play with no activity.
        val sessionPlayer = if (Build.VERSION.SDK_INT >= 35) object : ForwardingSimpleBasePlayer(player), WrapsExoPlayer {
            override val exoPlayer = player
            override fun handleSetPlayWhenReady(playWhenReady: Boolean): ListenableFuture<*> {
                if (playWhenReady && !prepareBackgroundPlayback()) return Futures.immediateVoidFuture()
                return super.handleSetPlayWhenReady(playWhenReady)
            }
        } else player
        mediaSession = MediaLibrarySession.Builder(this, sessionPlayer, callback)
            .setSessionActivity(sessionActivity)
            .setBitmapLoader(CoilBitmapLoader(this))
            .build()

        nextPreparation = NextTrackPreparation(playerScope, { prefs.cachedAuth }, prepare = { id, auth ->
            val result = musicApi.prepare(id, auth.userId, auth).checked()
            when (result.get("state")?.asString) {
                "ready", "preparing" -> PreparationResult.ACCEPTED
                "skipped" -> PreparationResult.BUSY
                else -> PreparationResult.UNAVAILABLE
            }
        })

        fun updateNextPreparation() {
            val nextIndex = player.nextMediaItemIndex // Uses the real shuffle/repeat order, not current + 1.
            val next = if (nextIndex in 0 until player.mediaItemCount) player.getMediaItemAt(nextIndex) else null
            val scheme = next?.localConfiguration?.uri?.scheme
            val id = NextTrackPreparation.eligibleVideoId(
                next?.mediaId, active = player.isPlaying && !routeGuard.blocked,
                audition = player.currentMediaItem?.mediaMetadata?.extras?.getBoolean("audition") == true,
                repeatOne = player.repeatMode == Player.REPEAT_MODE_ONE,
                localFile = scheme == "file" || scheme == "content",
            )
            nextPreparation?.update(prefs.cachedAuth, id)
        }

        fun routeLost() {
            recoveryJob?.cancel()
            nextPreparation?.cancel()
            routeGuard.disconnect()
            callback.cancelPending()
            player.pause() // Keeps media items, current position and shuffle/repeat state.
        }
        noisyReceiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context?, intent: Intent?) {
                if (intent?.action == AudioManager.ACTION_AUDIO_BECOMING_NOISY) routeLost()
            }
        }.also { ContextCompat.registerReceiver(this, it,
            IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY), ContextCompat.RECEIVER_NOT_EXPORTED) }
        audioManager = getSystemService(AudioManager::class.java)
        routeCallback = object : AudioDeviceCallback() {
            override fun onAudioDevicesRemoved(devices: Array<out AudioDeviceInfo>) {
                if (devices.any { it.isSink && it.type in setOf(
                    AudioDeviceInfo.TYPE_BLUETOOTH_A2DP, AudioDeviceInfo.TYPE_BLUETOOTH_SCO,
                    AudioDeviceInfo.TYPE_BLE_HEADSET, AudioDeviceInfo.TYPE_BLE_SPEAKER,
                    AudioDeviceInfo.TYPE_WIRED_HEADPHONES, AudioDeviceInfo.TYPE_WIRED_HEADSET) }) routeLost()
            }
            // No onAudioDevicesAdded auto-resume. Ear detection is not a route loss.
        }.also { audioManager?.registerAudioDeviceCallback(it, Handler(Looper.getMainLooper())) }

        playerScope.launch {
            var previous = prefs.accountNamespace
            prefs.authState.distinctUntilChanged().collect { auth ->
                nextPreparation?.update(auth, null)
                if (auth.sessionId.isBlank() || auth.namespace != previous) { player.stop(); player.clearMediaItems() }
                previous = auth.namespace
            }
        }
        Scrobbler(player, repository, playerScope, prefs, listenOutbox).attach()
        playerScope.launch { prefs.dataSaver.collect { DataSaving.choice = it } }

        // Saving data: the server makes the next songs' copies while this one plays (see SavingPreparation).
        val savingPreparation = SavingPreparation { ids ->
            serviceScope.launch {
                runCatching { musicApi.prepareSaving(com.armonia.app.homelab.SavingRequest(ids)) }
                    .onFailure { Log.i(TAG, "saving prepare error=${it.javaClass.simpleName}") }
            }
        }
        fun updateSavingPreparation() {
            val timeline = player.currentTimeline
            if (timeline.isEmpty || !player.isPlaying) return
            val mode = if (player.repeatMode == Player.REPEAT_MODE_ONE) Player.REPEAT_MODE_OFF else player.repeatMode
            val uris = mutableListOf<String>()
            var index = player.currentMediaItemIndex
            for (step in 0 until SavingPreparation.COUNT) {
                index = timeline.getNextWindowIndex(index, mode, player.shuffleModeEnabled)
                if (index == C.INDEX_UNSET) break
                player.getMediaItemAt(index).localConfiguration?.uri?.toString()?.let { uris += it }
            }
            val wanted = DataSaving.wanted()
            serviceScope.launch {
                val onPhone = uris.associateWith { runCatching { streamCache.isOnPhone(it) }.getOrDefault(false) }
                withContext(Dispatchers.Main) { savingPreparation.update(wanted, uris) { onPhone[it] == true } }
            }
        }

        // The start of the next song, kept while this one plays (see NextSongPreload).
        fun updatePreload() {
            val nextIndex = player.nextMediaItemIndex
            val next = if (nextIndex in 0 until player.mediaItemCount) player.getMediaItemAt(nextIndex) else null
            val duration = player.duration
            val uri = preload.next(
                playing = player.isPlaying && !routeGuard.blocked,
                bufferedAheadMs = player.totalBufferedDuration,
                loadedToEnd = duration != C.TIME_UNSET && player.bufferedPosition >= duration - 1_000,
                nextUri = next?.localConfiguration?.uri?.toString(),
                slow = PathRate.slow(),
                inOrder = inOrder,
            ) ?: return
            preloadJob?.cancel()
            preloadJob = serviceScope.launch {
                val kept = runCatching { streamCache.preloadStart(uri) { isActive } }
                Log.i(TAG, "preload bytes=${kept.getOrNull() ?: "-"}" +
                    (kept.exceptionOrNull()?.let { " error=${it.javaClass.simpleName}" } ?: ""))
                withContext(Dispatchers.Main) { preload.done(uri) }
            }
        }
        // How much is buffered changes without player events: look again every few seconds while playing.
        playerScope.launch {
            while (true) {
                delay(5_000)
                if (player.isPlaying) updatePreload()
            }
        }

        // Bounded diagnostics for logcat (tag ArmoniaPlayback): how long each song took to
        // start, every rebuffer and every failure. No addresses, accounts or song identifiers.
        var waitingSince = 0L
        var startedItem = false
        fun kind() = if (player.currentMediaItem?.mediaId?.contains("preview|") == true) "external" else "library"
        player.addListener(object : Player.Listener {
            override fun onEvents(player: Player, events: Player.Events) {
                updateNextPreparation()
                updatePreload()
                if (events.containsAny(Player.EVENT_MEDIA_ITEM_TRANSITION, Player.EVENT_IS_PLAYING_CHANGED,
                        Player.EVENT_TIMELINE_CHANGED, Player.EVENT_SHUFFLE_MODE_ENABLED_CHANGED)) updateSavingPreparation()
                expectedNext = player.nextMediaItemIndex
            }
            override fun onPlaybackStateChanged(state: Int) {
                val now = SystemClock.elapsedRealtime()
                if (state == Player.STATE_BUFFERING && !startedItem && player.playWhenReady) PlaybackStart.begin()
                if (state != Player.STATE_BUFFERING) PlaybackStart.end()
                if (state == Player.STATE_BUFFERING && waitingSince == 0L) waitingSince = now
                if (state == Player.STATE_READY && waitingSince != 0L) {
                    Log.i(TAG, "${if (startedItem) "rebuffer" else "start"} kind=${kind()} ms=${now - waitingSince} pos=${player.currentPosition / 1000}s")
                    startedItem = true
                    waitingSince = 0L
                }
            }
            override fun onIsPlayingChanged(isPlaying: Boolean) {
                if (isPlaying) recovery.onPlaying(SystemClock.elapsedRealtime())
            }
            override fun onPlayWhenReadyChanged(playWhenReady: Boolean, reason: Int) {
                if (playWhenReady && routeGuard.blocked) player.pause()
            }
            // Keep the shuffle/repeat buttons in sync when the state changes anywhere
            // (e.g. toggled from the phone UI), so Android Auto reflects it.
            override fun onShuffleModeEnabledChanged(shuffleModeEnabled: Boolean) {
                if (shuffleModeEnabled) reseedShuffle(player, shuffledBefore = false)
                mediaSession?.let { it.setMediaButtonPreferences(callback.buildMediaButtons(it.player)) }
            }

            // A freshly set queue gets a blind random order from ExoPlayer; re-seed so
            // shuffle starts from the item that was chosen and covers the whole queue.
            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
                startedItem = false
                waitingSince = if (player.playbackState == Player.STATE_BUFFERING) SystemClock.elapsedRealtime() else 0L
                if (player.playbackState == Player.STATE_BUFFERING && player.playWhenReady) PlaybackStart.begin()
                inOrder = reason == Player.MEDIA_ITEM_TRANSITION_REASON_AUTO ||
                    (reason == Player.MEDIA_ITEM_TRANSITION_REASON_SEEK && player.currentMediaItemIndex == expectedNext)
                // From here the player reads that song itself; a preload still going would only download it twice.
                preloadJob?.cancel()
                if (reason == Player.MEDIA_ITEM_TRANSITION_REASON_PLAYLIST_CHANGED && player.shuffleModeEnabled) {
                    reseedShuffle(player, shuffledBefore = true)
                }
            }

            override fun onRepeatModeChanged(repeatMode: Int) {
                mediaSession?.let { it.setMediaButtonPreferences(callback.buildMediaButtons(it.player)) }
            }

            // Media requests carry a session header. A delayed failure belongs
            // only to that session; it must never clear a newer login.
            override fun onPlayerError(error: PlaybackException) {
                val cause = error.cause
                if (cause is HttpDataSource.InvalidResponseCodeException && cause.responseCode == 401) {
                    cause.dataSpec.httpRequestHeaders["X-Session-Id"]?.let { failed ->
                        serviceScope.launch { prefs.clearSessionIfCurrent(failed) }
                    }
                }
                // A connection that stayed lost beyond ExoPlayer's own retries: resume from the
                // same position, a few times, unless the listener paused or the route was lost.
                val status = (cause as? HttpDataSource.InvalidResponseCodeException)?.responseCode
                val item = player.currentMediaItem?.mediaId
                val wait = recovery.onError(item, error.errorCode, status, player.playWhenReady,
                    routeGuard.blocked, SystemClock.elapsedRealtime(), network.online)
                Log.w(TAG, "error kind=${kind()} code=${error.errorCodeName} http=${status ?: "-"} pos=${player.currentPosition / 1000}s retry_ms=${wait ?: "-"} online=${network.online}")
                recoveryJob?.cancel()
                if (wait != null) recoveryJob = playerScope.launch {
                    delay(wait)
                    if (player.playerError != null && player.playWhenReady && !routeGuard.blocked &&
                        player.currentMediaItem?.mediaId == item) player.prepare()
                } else if (player.playWhenReady && !routeGuard.blocked &&
                    PlaybackRecovery.retryable(error.errorCode, status)) {
                    recoveryJob = skipToSongOnPhone(player, item)
                }
            }
        })
    }

    /**
     * The connection did not come back: go on with the next song of the queue that is already
     * on the phone, in play order (shuffle and repeat-all included), and say how many were
     * passed over. With none, playback stays where it failed, to be resumed when there is network.
     */
    private fun skipToSongOnPhone(player: ExoPlayer, failed: String?): Job {
        val timeline = player.currentTimeline
        val repeat = if (player.repeatMode == Player.REPEAT_MODE_ALL) Player.REPEAT_MODE_ALL else Player.REPEAT_MODE_OFF
        val upcoming = mutableListOf<Int>()
        val uris = mutableMapOf<Int, String>()
        var index = player.currentMediaItemIndex
        for (step in 1 until player.mediaItemCount) {
            index = timeline.getNextWindowIndex(index, repeat, player.shuffleModeEnabled)
            if (index == androidx.media3.common.C.INDEX_UNSET || index == player.currentMediaItemIndex) break
            upcoming += index
            player.getMediaItemAt(index).localConfiguration?.uri?.let { uris[index] = it.toString() }
        }
        return playerScope.launch {
            val jump = withContext(Dispatchers.IO) {
                OfflineSkip.next(upcoming) { i -> uris[i]?.let { runCatching { streamCache.isOnPhone(it) }.getOrDefault(false) } == true }
            }
            // Only if nothing changed meanwhile: still failed on that song and still meant to play.
            if (player.playerError == null || !player.playWhenReady || routeGuard.blocked ||
                player.currentMediaItem?.mediaId != failed) return@launch
            if (jump == null) { notices.post(OfflineSkip.NOTHING_ON_PHONE); return@launch }
            Log.w(TAG, "offline skip=${jump.skipped}")
            player.seekTo(jump.target, 0)
            player.prepare()
            player.play()
            notices.post(OfflineSkip.notice(jump.skipped))
        }
    }

    /**
     * ExoPlayer's default shuffle order is a plain random permutation, which leaves
     * the current track at an arbitrary point in it — with repeat off, playback can
     * stop after a handful of songs. Use an order that starts at the current track.
     * Songs queued by hand that were coming next still come next (HandPickedQueue):
     * read in the queue's own order when shuffle has just been turned on, in the
     * shuffle order when the queue changed under it.
     */
    private fun reseedShuffle(player: ExoPlayer, shuffledBefore: Boolean) {
        val count = player.mediaItemCount
        if (count < 2) return
        val current = player.currentMediaItemIndex
        val handPicked = player.handPickedIndices()
        // A new list arrives with a blind random order: songs carried over from the old queue
        // (MusicPlayer.playQueue) sit right after its first song in the queue's own order.
        val next = handPickedRun(player.currentTimeline.playOrder(shuffledBefore), current, handPicked)
            .ifEmpty { handPickedRun(player.currentTimeline.playOrder(false), current, handPicked) }
        val order = shuffledOrderStartingAt(count, current, next = next)
        player.setShuffleOrder(ShuffleOrder.DefaultShuffleOrder(order, Random.nextLong()))
    }

    @androidx.annotation.RequiresApi(35)
    private fun prepareBackgroundPlayback(): Boolean {
        val session = mediaSession ?: return false
        if (session.player.mediaItemCount == 0 || foregroundServiceType != ServiceInfo.FOREGROUND_SERVICE_TYPE_NONE) return true
        val process = ActivityManager.RunningAppProcessInfo()
        ActivityManager.getMyMemoryState(process)
        if (process.importance == ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND) return true

        // Media3 takes over this same notification as soon as playback starts.
        val channelId = DefaultMediaNotificationProvider.DEFAULT_CHANNEL_ID
        val channelName = getString(DefaultMediaNotificationProvider.DEFAULT_CHANNEL_NAME_RESOURCE_ID)
        getSystemService(NotificationManager::class.java)
            .createNotificationChannel(NotificationChannel(channelId, channelName, NotificationManager.IMPORTANCE_LOW))
        val notification = Notification.Builder(this, channelId)
            .setSmallIcon(R.drawable.ic_armonia_notification)
            .setContentTitle(session.player.mediaMetadata.title ?: getString(R.string.app_name))
            .setContentIntent(session.sessionActivity)
            .setStyle(Notification.MediaStyle().setMediaSession(session.platformToken))
            .build()
        return try {
            startForeground(DefaultMediaNotificationProvider.DEFAULT_NOTIFICATION_ID, notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK)
            true
        } catch (_: ForegroundServiceStartNotAllowedException) {
            notices.post("Android no ha autorizado la reproducción en segundo plano.")
            false
        }
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaLibrarySession? {
        // Media3 binds the platform MediaBrowser before it knows the caller's UID.
        // LibrarySessionCallback.onConnect then authorizes the actual controller.
        if (controllerInfo.uid < 0 && controllerInfo.packageName == MediaSession.ControllerInfo.LEGACY_CONTROLLER_PACKAGE_NAME) {
            return mediaSession
        }
        return if (com.armonia.app.security.AccountScope.controllerAllowed(
            controllerInfo.uid, android.os.Process.myUid(), controllerInfo.isTrusted)) mediaSession else null
    }

    // onTaskRemoved is left to Media3's default, which stops the service when the
    // player isn't set to play (and handles the Android 14+ foreground-service rules).

    override fun onDestroy() {
        recoveryJob?.cancel()
        preloadJob?.cancel()
        PlaybackStart.end()
        routeCallback?.let { audioManager?.unregisterAudioDeviceCallback(it) }
        noisyReceiver?.let { unregisterReceiver(it) }
        callback.cancelPending()
        nextPreparation?.cancel()
        serviceScope.cancel()
        playerScope.cancel()
        mediaSession?.run {
            player.release()
            release()
            mediaSession = null
        }
        super.onDestroy()
    }

    private companion object { const val TAG = "ArmoniaPlayback" }
}
