package com.armonia.app.homelab

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

class DurableListenQueueTest {
    private fun event(id: String) = PlayEvent(id, MusicTrack("authorized_http", "tone", "Tone", "Fixture"), 100, 20.0)
    private class Store {
        val data = mutableMapOf<String,List<PendingListen>>()
        var fail = false
        val queue = DurableListenQueue({ data[it].orEmpty() }, { key, value ->
            if (fail) throw IOException("simulated disk full")
            data[key] = value
        })
    }
    @Test fun `blocked delivery never blocks persistence and cannot lose a concurrent enqueue`() = runBlocking {
        val s=Store();s.queue.enqueue("alice","A",event("first"))
        val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>()
        val sending=launch { s.queue.flush("alice","A",{true}) { entered.complete(Unit);release.await();202 } }
        entered.await()
        withTimeout(500) {s.queue.enqueue("alice","A",event("second"))}
        assertEquals(2,s.data["alice"]!!.size)
        release.complete(Unit);sending.join()
        assertEquals(listOf("second"),s.data["alice"]!!.map{it.event.id})
    }
    @Test fun `network error and cancellation preserve the original payload for retry`() = runBlocking {
        val s=Store();val original=event("first");s.queue.enqueue("alice","A",original)
        val entered=CompletableDeferred<Unit>()
        val sending=launch { s.queue.flush("alice","A",{true}) { entered.complete(Unit);awaitCancellation() } }
        entered.await();sending.cancelAndJoin()
        assertEquals(original,s.data["alice"]!!.single().event)
        s.queue.flush("alice","A",{true}) {503}
        assertEquals(1,s.data["alice"]!!.size)
        s.queue.flush("alice","A",{true}) {202}
        assertTrue(s.data["alice"]!!.isEmpty())
    }
    @Test fun `changing accounts during request keeps old event and never sends it for another owner`() = runBlocking {
        val s=Store();s.queue.enqueue("alice","A",event("first"));var current=true
        s.queue.flush("alice","A",{current}) {current=false;409}
        assertEquals(1,s.data["alice"]!!.size);assertNull(s.data["alice-rejected"])
        s.queue.flush("alice","B",{true}) {fail("sent as wrong owner");202}
    }
    @Test fun `disk failure cannot acknowledge a delivery or replace existing queue`() = runBlocking {
        val s=Store();s.queue.enqueue("alice","A",event("first"));s.fail=true
        try {s.queue.enqueue("alice","A",event("second"));fail("expected disk error")} catch (_:IOException) {}
        try {s.queue.flush("alice","A",{true}) {202};fail("expected disk error")} catch (_:IOException) {}
        assertEquals(listOf("first"),s.data["alice"]!!.map{it.event.id})
        s.fail=false;s.queue.flush("alice","A",{true}) {202};assertTrue(s.data["alice"]!!.isEmpty())
    }
    @Test fun `duplicate enqueue is idempotent and rejection does not starve newer listens`() = runBlocking {
        val s=Store();s.queue.enqueue("alice","A",event("first"));s.queue.enqueue("alice","A",event("first"))
        s.queue.enqueue("alice","A",event("second"))
        s.queue.flush("alice","A",{true}) {if(it.event.id=="first")422 else 202}
        assertTrue(s.data["alice"]!!.isEmpty())
        assertEquals("first",s.data["alice-rejected"]!!.single().event.id)
    }
}
