package com.armonia.app.playback

import androidx.media3.common.PlaybackException
import org.junit.Assert.*
import org.junit.Test

class PlaybackRecoveryTest {
    private val network = PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_FAILED
    private val badStatus = PlaybackException.ERROR_CODE_IO_BAD_HTTP_STATUS

    @Test fun aLostConnectionIsResumedABoundedNumberOfTimes() {
        val r = PlaybackRecovery()
        assertEquals(2_000L, r.onError("preview|a", network, null, true, false, 0))
        assertEquals(5_000L, r.onError("preview|a", network, null, true, false, 3_000))
        assertEquals(10_000L, r.onError("preview|a", network, null, true, false, 9_000))
        assertNull(r.onError("preview|a", network, null, true, false, 20_000))
    }

    @Test fun anIntentionalPauseOrRouteLossIsNeverOverridden() {
        val r = PlaybackRecovery()
        assertNull(r.onError("preview|a", network, null, playWhenReady = false, routeBlocked = false, nowMs = 0))
        assertNull(r.onError("preview|a", network, null, playWhenReady = true, routeBlocked = true, nowMs = 0))
    }

    @Test fun denialsAndUndecodableFilesAreShownNotRetried() {
        val r = PlaybackRecovery()
        for (status in listOf(401, 403, 404, 416)) assertNull(r.onError("a", badStatus, status, true, false, 0))
        assertNull(r.onError("a", PlaybackException.ERROR_CODE_PARSING_CONTAINER_MALFORMED, null, true, false, 0))
        assertNull(r.onError("a", PlaybackException.ERROR_CODE_DECODING_FAILED, null, true, false, 0))
        assertNull(r.onError(null, network, null, true, false, 0))
    }

    @Test fun temporaryServerAnswersAreRetried() {
        for (status in listOf(500, 502, 503, 504, 408, 429)) {
            assertNotNull(PlaybackRecovery().onError("a", badStatus, status, true, false, 0))
        }
        assertNotNull(PlaybackRecovery().onError("a", PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT, null, true, false, 0))
    }

    @Test fun theBudgetIsPerSongAndReturnsOnlyAfterSteadyPlayback() {
        val r = PlaybackRecovery(delaysMs = listOf(1_000))
        assertNotNull(r.onError("a", network, null, true, false, 0))
        assertNull(r.onError("a", network, null, true, false, 2_000))
        // The next song starts with a full budget.
        assertNotNull(r.onError("b", network, null, true, false, 3_000))
        // Playing for a few seconds between failures does not refill it...
        r.onPlaying(10_000)
        assertNull(r.onError("b", network, null, true, false, 12_000))
        // ...thirty seconds of steady playback does.
        r.onPlaying(50_000)
        assertNotNull(r.onError("b", network, null, true, false, 60_000))
    }
}
