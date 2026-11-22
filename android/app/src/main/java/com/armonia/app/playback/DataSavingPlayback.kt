package com.armonia.app.playback

import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.util.UnstableApi
import androidx.media3.common.util.Util
import androidx.media3.datasource.DataSource
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.LoadControl
import androidx.media3.exoplayer.drm.DrmSessionManagerProvider
import androidx.media3.exoplayer.source.MediaSource
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import androidx.media3.exoplayer.upstream.LoadErrorHandlingPolicy

/**
 * How far ahead of what plays a song is downloaded. On mobile data at most [MOBILE_AHEAD_US] (the listener's
 * choice, 18-11-2026): on 18-11-2026 the server sent 182 MB of songs and 67 MB of it (37 %) belonged to 99 songs
 * skipped before their end, about 40-50 s of each downloaded ahead (ExoPlayer's default is 50 s). Elsewhere,
 * ExoPlayer's defaults. Every other rule (when to start, when to resume after a stall) stays the default.
 */
@UnstableApi
class DataSavingLoadControl(private val onMobileData: () -> Boolean = PathRate::metered) : DefaultLoadControl() {
    override fun shouldContinueLoading(parameters: LoadControl.Parameters): Boolean {
        if (farEnough(parameters.bufferedDurationUs)) return false
        return super.shouldContinueLoading(parameters)
    }

    /** On mobile data with [MOBILE_AHEAD_US] or more already loaded ahead: stop until it plays down. */
    fun farEnough(bufferedUs: Long): Boolean = onMobileData() && bufferedUs >= MOBILE_AHEAD_US

    companion object {
        const val MOBILE_AHEAD_US = 30_000_000L
    }
}

/**
 * Songs (progressive files) asking [DataSavingLoadControl] whether to go on every [CHECK_BYTES] instead of
 * ExoPlayer's 1 MiB; anything else (and a clipped item) as [fallback] makes it. Measured 19-11-2026 in the lab
 * on mobile data with the Opus 64 copy (~6.4 KB/s): with 1 MiB, loading stopped only after ~158 s of the song,
 * 113 s ahead instead of 30. 64 KB is ~10 s of Opus 64 and ~4 s of AAC 128.
 */
@UnstableApi
class SongMediaSourceFactory(dataSource: DataSource.Factory, private val fallback: MediaSource.Factory) : MediaSource.Factory {
    private val progressive = ProgressiveMediaSource.Factory(dataSource).setContinueLoadingCheckIntervalBytes(CHECK_BYTES)

    override fun setDrmSessionManagerProvider(provider: DrmSessionManagerProvider): MediaSource.Factory = apply {
        progressive.setDrmSessionManagerProvider(provider)
        fallback.setDrmSessionManagerProvider(provider)
    }

    override fun setLoadErrorHandlingPolicy(policy: LoadErrorHandlingPolicy): MediaSource.Factory = apply {
        progressive.setLoadErrorHandlingPolicy(policy)
        fallback.setLoadErrorHandlingPolicy(policy)
    }

    override fun getSupportedTypes(): IntArray = fallback.supportedTypes

    override fun createMediaSource(mediaItem: MediaItem): MediaSource {
        val local = mediaItem.localConfiguration
        val song = local != null && mediaItem.clippingConfiguration == MediaItem.ClippingConfiguration.UNSET &&
            Util.inferContentTypeForUriAndMimeType(local.uri, local.mimeType) == C.CONTENT_TYPE_OTHER
        return if (song) progressive.createMediaSource(mediaItem) else fallback.createMediaSource(mediaItem)
    }

    companion object {
        const val CHECK_BYTES = 64 * 1024
    }
}

/**
 * The next songs to have the server make in their data-saving copy while this one plays (see
 * middleware/routes/stream.py, prepare), so skipping to them starts at once. Asks once per set of songs.
 */
class SavingPreparation(private val ask: (List<String>) -> Unit) {
    private var asked: List<String> = emptyList()

    fun update(wanted: Boolean, nextUris: List<String>, onPhone: (String) -> Boolean) {
        if (!wanted) { asked = emptyList(); return }
        val ids = nextUris.mapNotNull { trackId(it) }.distinct().take(COUNT)
        if (ids.isEmpty() || ids == asked) return
        asked = ids
        val missing = ids.filterIndexed { i, _ -> !onPhone(nextUris[i]) }
        if (missing.isNotEmpty()) ask(missing)
    }

    companion object {
        const val COUNT = 2

        fun trackId(uri: String): String? = uri.substringBefore('?').substringAfter("/api/stream/", "")
            .takeIf { it.isNotEmpty() && '/' !in it }
            ?.let { java.net.URLDecoder.decode(it.replace("+", "%2B"), "UTF-8") }
    }
}
