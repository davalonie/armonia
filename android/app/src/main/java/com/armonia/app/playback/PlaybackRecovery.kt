package com.armonia.app.playback

import androidx.media3.common.PlaybackException

/**
 * Decides whether a failed song is resumed from the same position.
 *
 * ExoPlayer already retries a dropped connection a few times within seconds; when that is
 * exhausted (a network change, the server restarting, Wi-Fi waking up) the player stops in
 * an error state. Only a network failure or a temporary server answer is retried, only while
 * the listener still wants it to play, never after a headphone/Bluetooth disconnection, a
 * pause, a denial (401/403/404) or an undecodable file, and a bounded number of times per song.
 */
internal class PlaybackRecovery(
    private val delaysMs: List<Long> = listOf(2_000, 5_000, 10_000),
    private val steadyMs: Long = 30_000,
) {
    private var item: String? = null
    private var attempts = 0
    private var lastFailureMs = Long.MIN_VALUE / 2

    /** Milliseconds to wait before preparing again, or null when the failure is left to the listener. */
    fun onError(itemId: String?, errorCode: Int, httpStatus: Int?, playWhenReady: Boolean,
                routeBlocked: Boolean, nowMs: Long, online: Boolean = true): Long? {
        if (itemId != item) { item = itemId; attempts = 0 }
        lastFailureMs = nowMs
        if (itemId == null || !playWhenReady || routeBlocked || !retryable(errorCode, httpStatus)) return null
        // With no network at all, one short wait covers a change of network; more is silence.
        if (attempts >= if (online) delaysMs.size else 1) return null
        return delaysMs[attempts++]
    }

    /** Playing steadily again restores the budget; a song that fails every few seconds does not. */
    fun onPlaying(nowMs: Long) {
        if (nowMs - lastFailureMs >= steadyMs) attempts = 0
    }

    companion object {
        fun retryable(errorCode: Int, httpStatus: Int?): Boolean = when (errorCode) {
            PlaybackException.ERROR_CODE_IO_UNSPECIFIED,
            PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_FAILED,
            PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT,
            PlaybackException.ERROR_CODE_TIMEOUT -> true
            PlaybackException.ERROR_CODE_IO_BAD_HTTP_STATUS ->
                httpStatus != null && (httpStatus >= 500 || httpStatus == 408 || httpStatus == 429)
            else -> false
        }
    }
}
