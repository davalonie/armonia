package com.armonia.app.data.repository

import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Test

class SessionSavedSongsTest {
    @Test fun bothPlayersShareReadsUntilSaveOrAccountChange() = runBlocking {
        val cache = SessionSavedSongs()
        val user = AuthSnapshot(userId = "ana", sessionId = "lab")
        var calls = 0
        suspend fun read(id: String, revision: Long = 0, account: AuthSnapshot = user) =
            cache.get(account, revision, id) { calls++; delay(1); false }

        for (id in listOf("1", "2", "3", "1")) {
            awaitAll(async { read(id) }, async { read(id) })
        }
        assertEquals(3, calls)
        read("1", revision = 1)
        assertEquals(4, calls)
        read("1", revision = 1, account = user.copy(sessionId = "otra"))
        assertEquals(5, calls)
    }
}
