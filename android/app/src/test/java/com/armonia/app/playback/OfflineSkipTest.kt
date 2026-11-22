package com.armonia.app.playback

import androidx.media3.common.PlaybackException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class OfflineSkipTest {
    @Test fun goesToTheFirstUpcomingSongThatIsOnThePhone() {
        val onPhone = setOf(7, 9)
        assertEquals(OfflineSkip.Jump(target = 7, skipped = 3), OfflineSkip.next(listOf(4, 5, 7, 9)) { it in onPhone })
        assertEquals(OfflineSkip.Jump(target = 4, skipped = 1), OfflineSkip.next(listOf(4, 5)) { true })
    }

    @Test fun followsThePlayOrderItIsGivenNotTheQueueOrder() {
        // Shuffle: the service passes the shuffled order; the first one on the phone wins.
        assertEquals(OfflineSkip.Jump(target = 2, skipped = 2), OfflineSkip.next(listOf(8, 2, 5)) { it in setOf(2, 5) })
    }

    @Test fun withNothingOnThePhoneItStaysWhereItIs() {
        assertNull(OfflineSkip.next(listOf(1, 2, 3)) { false })
        assertNull(OfflineSkip.next(emptyList()) { true })
    }

    @Test fun theNoticeSaysHowManyWerePassedOver() {
        assertEquals("Sin conexión: se salta una canción que no está en el teléfono.", OfflineSkip.notice(1))
        assertEquals("Sin conexión: se saltan 3 canciones que no están en el teléfono.", OfflineSkip.notice(3))
    }

    @Test fun withoutAnyNetworkOnlyOneShortWaitBeforeGivingUp() {
        val recovery = PlaybackRecovery()
        val code = PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_FAILED
        assertEquals(2_000L, recovery.onError("a", code, null, true, false, 0, online = false))
        assertNull("no network: the second failure is not waited for", recovery.onError("a", code, null, true, false, 3_000, online = false))
    }

    @Test fun withNetworkTheUsualRetriesStillHappen() {
        val recovery = PlaybackRecovery()
        val code = PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_FAILED
        assertEquals(listOf(2_000L, 5_000L, 10_000L, null), (0..3).map { recovery.onError("a", code, null, true, false, it * 1_000L) })
    }
}
