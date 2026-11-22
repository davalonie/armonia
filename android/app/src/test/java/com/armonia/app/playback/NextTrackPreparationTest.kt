package com.armonia.app.playback

import com.armonia.app.data.repository.AuthSnapshot
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

class NextTrackPreparationTest {
    private val alice = AuthSnapshot("https://fixture.invalid", "alice", "alice-id", "session-A")
    private val first = "aaaaaaaaaaa"
    private val second = "bbbbbbbbbbb"

    @Test fun `only active next YouTube item is eligible`() {
        fun eligible(id: String?, active: Boolean = true, audition: Boolean = false,
                     repeatOne: Boolean = false, localFile: Boolean = false) =
            NextTrackPreparation.eligibleVideoId(id, active, audition, repeatOne, localFile)
        assertEquals(first, eligible("preview|$first"))
        assertEquals(first, eligible("track|songs|all|preview|$first"))
        assertNull(eligible("local-song"))
        assertNull(eligible("external|authorized-fixture"))
        assertNull(eligible("preview|../../etc/passwd"))
        assertNull(eligible(null))
        assertNull(eligible("preview|$first", active = false))
        assertNull(eligible("preview|$first", audition = true))
        assertNull(eligible("preview|$first", repeatOne = true))
        assertNull(eligible("preview|$first", localFile = true))
    }

    @Test fun `duplicate events prepare once and completed targets expire`() = runBlocking {
        var now = 0L
        val calls = mutableListOf<String>()
        val preparer = NextTrackPreparation(this, {alice}, {id, auth ->
            assertEquals(alice, auth); calls.add(id); PreparationResult.ACCEPTED
        }, nowMs = {now}, debounceMs = 0)
        repeat(20) { preparer.update(alice, first) }
        yield()
        repeat(20) { preparer.update(alice, first) }
        yield()
        assertEquals(listOf(first), calls)
        now = 120_001
        preparer.update(alice, first); yield()
        assertEquals(listOf(first, first), calls)
        preparer.cancel()
    }

    @Test fun `changing next item cancels old request and pause cancels replacement`() = runBlocking {
        val started = CompletableDeferred<Unit>()
        val stopped = CompletableDeferred<Unit>()
        val replacement = CompletableDeferred<Unit>()
        val replacementStopped = CompletableDeferred<Unit>()
        val preparer = NextTrackPreparation(this, {alice}, { id, _ ->
            if (id == first) {
                started.complete(Unit)
                try { awaitCancellation() } finally { stopped.complete(Unit) }
            } else {
                replacement.complete(Unit)
                try { awaitCancellation() } finally { replacementStopped.complete(Unit) }
            }
        }, debounceMs = 0)
        preparer.update(alice, first)
        withTimeout(1_000) { started.await() }
        preparer.update(alice, second)
        withTimeout(1_000) { stopped.await(); replacement.await() }
        preparer.update(alice, null)
        withTimeout(1_000) { replacementStopped.await() }
    }

    @Test fun `rapid queue changes discard obsolete requests before dispatch`() = runBlocking {
        val calls = mutableListOf<String>()
        val preparer = NextTrackPreparation(this, {alice}, {id, _ -> calls.add(id); PreparationResult.ACCEPTED}, debounceMs = 0)
        preparer.update(alice, first)
        preparer.update(alice, second)
        yield()
        assertEquals(listOf(second), calls)
        preparer.cancel()
    }

    @Test fun `logout cancels request and new session does not reuse completed state`() = runBlocking {
        var auth = alice
        val calls = mutableListOf<AuthSnapshot>()
        val preparer = NextTrackPreparation(this, {auth}, {_, captured -> calls.add(captured); PreparationResult.ACCEPTED}, debounceMs = 0)
        preparer.update(auth, first); yield()
        auth = alice.copy(sessionId = "")
        preparer.update(auth, first); yield()
        assertEquals(1, calls.size)
        auth = alice.copy(sessionId = "session-B")
        preparer.update(auth, first); yield()
        assertEquals(listOf(alice, auth), calls)
        preparer.cancel()
    }

    @Test fun `account changed before dispatch sends nothing`() = runBlocking {
        var auth = alice
        val preparer = NextTrackPreparation(this, {auth}, {_, _ -> fail("stale account sent"); PreparationResult.UNAVAILABLE}, debounceMs = 0)
        preparer.update(auth, first)
        auth = alice.copy(userId = "bob-id", sessionId = "bob-session")
        yield()
        preparer.cancel()
    }

    @Test fun `provider failure is quiet and bounded by cooldown`() = runBlocking {
        var now = 0L
        var calls = 0
        val preparer = NextTrackPreparation(this, {alice}, {_, _ -> calls++; throw IOException("fixture failure")},
            nowMs = {now}, debounceMs = 0)
        preparer.update(alice, first); yield()
        repeat(20) {preparer.update(alice, first)}; yield()
        assertEquals(1, calls)
        now = 30_001
        preparer.update(alice, first); yield()
        assertEquals(2, calls)
        preparer.cancel()
    }

    @Test fun `server busy retries at most twice without another player event then cools down`() = runBlocking {
        var now = 0L
        var calls = 0
        val preparer = NextTrackPreparation(this, {alice}, {_, _ -> calls++; PreparationResult.BUSY},
            nowMs = {now}, debounceMs = 0, busyRetryDelaysMs = listOf(0, 0))
        preparer.update(alice, first); yield()
        preparer.update(alice, first); yield()
        assertEquals(3, calls)
        now = 30_001
        preparer.update(alice, first); yield()
        assertEquals(6, calls)
        preparer.cancel()
    }

    @Test fun `busy then accepted prepares next without player events`() = runBlocking {
        var calls = 0
        val preparer = NextTrackPreparation(this, {alice}, {_, captured ->
            assertEquals(alice, captured)
            if (++calls == 1) PreparationResult.BUSY else PreparationResult.ACCEPTED
        }, debounceMs = 0, busyRetryDelaysMs = listOf(0, 0))
        preparer.update(alice, first); yield()
        assertEquals(2, calls)
        preparer.update(alice, first); yield()
        assertEquals(2, calls)
        preparer.cancel()
    }

    @Test fun `pause cancels pending busy retry`() = runBlocking {
        var calls = 0
        val entered = CompletableDeferred<Unit>()
        val preparer = NextTrackPreparation(this, {alice}, {_, _ ->
            calls++; entered.complete(Unit); PreparationResult.BUSY
        }, debounceMs = 0)
        preparer.update(alice, first)
        withTimeout(1_000) { entered.await() }
        preparer.update(alice, null)
        yield()
        assertEquals(1, calls)
        preparer.cancel()
    }

    @Test fun `unavailable state never enters busy retries`() = runBlocking {
        var calls = 0
        val preparer = NextTrackPreparation(this, {alice}, {_, _ -> calls++; PreparationResult.UNAVAILABLE},
            debounceMs = 0, busyRetryDelaysMs = listOf(0, 0))
        preparer.update(alice, first); yield()
        assertEquals(1, calls)
        preparer.cancel()
    }

    @Test fun `logout cancels an already dispatched request`() = runBlocking {
        var auth = alice
        val entered = CompletableDeferred<Unit>()
        val stopped = CompletableDeferred<Unit>()
        val preparer = NextTrackPreparation(this, {auth}, {_, _ ->
            entered.complete(Unit)
            try { awaitCancellation() } finally { stopped.complete(Unit) }
        }, debounceMs = 0)
        preparer.update(auth, first)
        withTimeout(1_000) { entered.await() }
        auth = auth.copy(sessionId = "")
        preparer.update(auth, first)
        withTimeout(1_000) { stopped.await() }
        preparer.cancel()
    }
}
