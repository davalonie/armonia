package com.armonia.app.playback

import com.google.gson.Gson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SavedQueueTest {
    private val gson = Gson()

    private fun songJson(id: String, title: String = "t") =
        """{"id":"$id","title":"$title","artist":"a","duration":120}"""

    @Test
    fun `parses a full saved queue`() {
        val json = """{"songs":[${songJson("1")},${songJson("2")},${songJson("3")}],"currentIndex":1,"positionMs":4500}"""
        val q = SavedQueue.parse(json, gson)!!
        assertEquals(listOf("1", "2", "3"), q.songs.map { it.id })
        assertEquals(1, q.currentIndex)
        assertEquals(4500L, q.positionMs)
    }

    @Test
    fun `keeps which songs were queued by hand and drops positions outside the queue`() {
        val json = SavedQueue(SavedQueue.parse(
            """{"songs":[${songJson("1")},${songJson("2")},${songJson("3")}],"currentIndex":0}""", gson)!!.songs,
            0, 0L, handPicked = setOf(1, 2)).toJson(gson)
        assertEquals(setOf(1, 2), SavedQueue.parse(json, gson)!!.handPicked)
        val odd = """{"songs":[${songJson("1")}],"handPicked":[0,5,-1]}"""
        assertEquals(setOf(0), SavedQueue.parse(odd, gson)!!.handPicked)
        val older = """{"songs":[${songJson("1")}]}"""
        assertEquals(emptySet<Int>(), SavedQueue.parse(older, gson)!!.handPicked)
    }

    @Test
    fun `falls back to the legacy single-track field`() {
        val json = """{"song":${songJson("42")},"positionMs":10}"""
        val q = SavedQueue.parse(json, gson)!!
        assertEquals(listOf("42"), q.songs.map { it.id })
        assertEquals(0, q.currentIndex)
        assertEquals(10L, q.positionMs)
    }

    @Test
    fun `clamps an out-of-range index and negative position`() {
        val json = """{"songs":[${songJson("1")},${songJson("2")}],"currentIndex":7,"positionMs":-3}"""
        val q = SavedQueue.parse(json, gson)!!
        assertEquals(1, q.currentIndex)
        assertEquals(0L, q.positionMs)
    }

    @Test
    fun `returns null for empty, malformed, or song-less payloads`() {
        assertNull(SavedQueue.parse(null, gson))
        assertNull(SavedQueue.parse("", gson))
        assertNull(SavedQueue.parse("not json", gson))
        assertNull(SavedQueue.parse("""{"songs":[],"currentIndex":0}""", gson))
        assertNull(SavedQueue.parse("""{"currentIndex":0}""", gson))
    }
}
