package com.armonia.app.ui.playlists

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PlaylistAdderTest {
    @Test fun aDoubleTapSendsTheSongOnce() = runBlocking {
        val gate = CompletableDeferred<Unit>()
        var sent = 0
        val adder = PlaylistAdder(send = { sent++; gate.await(); Result.success(Unit) }, remove = { Result.success(Unit) })
        val first = async { adder.add("song", false) }
        yield()
        assertEquals(AddState.SENDING, adder.stateOf("song", false))
        assertFalse(adder.add("song", false))  // second tap while the first is in flight
        gate.complete(Unit)
        assertTrue(first.await())
        assertFalse(adder.add("song", false))  // and once it is in
        assertEquals(1, sent)
        assertEquals(AddState.ADDED, adder.stateOf("song", false))
    }

    @Test fun aFailureIsNotShownAsAddedAndCanBeRetried() = runBlocking {
        var attempts = 0
        val adder = PlaylistAdder(
            send = { if (++attempts == 1) Result.failure(IllegalStateException("sin red")) else Result.success(Unit) },
            remove = { Result.success(Unit) },
        )
        assertFalse(adder.add("song", false))
        assertEquals(AddState.FAILED, adder.stateOf("song", false))
        assertFalse(adder.stateOf("song", false).inPlaylist)
        assertTrue(adder.add("song", false))
        assertEquals(AddState.ADDED, adder.stateOf("song", false))
        assertEquals(2, attempts)
    }

    @Test fun aSongAlreadyInThePlaylistIsNotSentAgain() = runBlocking {
        var sent = 0
        val adder = PlaylistAdder(send = { sent++; Result.success(Unit) }, remove = { Result.success(Unit) })
        assertEquals(AddState.ALREADY, adder.stateOf("song", true))
        assertFalse(adder.add("song", true))
        assertEquals(0, sent)
    }

    @Test fun undoRemovesOnlyWhatThisScreenAdded() = runBlocking {
        val removed = mutableListOf<String>()
        var clock = 0L
        val adder = PlaylistAdder(send = { Result.success(Unit) }, remove = { removed += it; Result.success(Unit) }, now = { clock })
        assertFalse(adder.undo("old"))  // was in the playlist before: not this screen's to remove
        adder.add("new", false)
        clock += PlaylistAdder.UNDO_GUARD_MS
        assertTrue(adder.undo("new"))
        assertEquals(listOf("new"), removed)
        assertEquals(AddState.NONE, adder.stateOf("new", false))
    }

    @Test fun aFailedUndoKeepsTheSongShownAsAdded() = runBlocking {
        var clock = 0L
        val adder = PlaylistAdder(send = { Result.success(Unit) }, remove = { Result.failure(IllegalStateException("409")) }, now = { clock })
        adder.add("song", false)
        clock += PlaylistAdder.UNDO_GUARD_MS
        assertFalse(adder.undo("song"))
        assertEquals(AddState.ADDED, adder.stateOf("song", false))
    }

    @Test fun theSecondTapOfADoubleTapDoesNotUndoAFastAddition() = runBlocking {
        var clock = 0L
        val removed = mutableListOf<String>()
        val adder = PlaylistAdder(send = { Result.success(Unit) }, remove = { removed += it; Result.success(Unit) }, now = { clock })
        assertTrue(adder.add("song", false))   // the server answered before the second tap
        clock += 150
        assertFalse(adder.undo("song"))        // that tap lands on the undo control: ignored
        assertEquals(AddState.ADDED, adder.stateOf("song", false))
        assertTrue(removed.isEmpty())
        clock += PlaylistAdder.UNDO_GUARD_MS
        assertTrue(adder.undo("song"))         // a deliberate undo still works
    }
}
