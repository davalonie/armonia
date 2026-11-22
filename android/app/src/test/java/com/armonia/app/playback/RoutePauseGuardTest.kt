package com.armonia.app.playback

import org.junit.Assert.*
import org.junit.Test

class RoutePauseGuardTest {
    @Test fun disconnectInvalidatesLoadingAndReconnectDoesNotResume() {
        val guard = RoutePauseGuard()
        val loading = guard.explicitPlay()
        guard.disconnect()
        assertFalse(guard.permits(loading))
        assertTrue(guard.blocked)
        // Adding an audio device deliberately has no effect on the guard.
        assertFalse(guard.permits(guard.epoch))
        val newRequest = guard.explicitPlay()
        assertTrue(guard.permits(newRequest))
        assertFalse(guard.permits(loading))
    }
    @Test fun repeatedDisconnectsCannotRestoreOldRequests() {
        val guard = RoutePauseGuard()
        val first = guard.explicitPlay()
        guard.disconnect()
        val second = guard.explicitPlay()
        guard.disconnect()
        assertFalse(guard.permits(first))
        assertFalse(guard.permits(second))
    }
}
