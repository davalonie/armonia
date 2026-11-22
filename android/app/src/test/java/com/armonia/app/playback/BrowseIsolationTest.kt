package com.armonia.app.playback

import org.junit.Assert.*
import org.junit.Test

class BrowseIsolationTest {
    @Test fun `same search cannot reveal a previous account or session`() {
        val cache = ScopedSearchCache<String>()
        cache.put("alice:session1", "private", listOf("Alice private track"))
        assertEquals(listOf("Alice private track"), cache.get("alice:session1", "private"))
        assertNull(cache.get("bob:session2", "private"))
        assertNull(cache.get("alice:session3", "private"))
        assertNull(cache.get(null, "private"))
        assertNull(cache.get("alice:session1", "different"))
    }
    @Test fun `cached results are a snapshot and logout cannot populate a cache`() {
        val cache = ScopedSearchCache<String>()
        val tracks = mutableListOf("first")
        cache.put("alice:session", "query", tracks)
        tracks.add("second")
        assertEquals(listOf("first"), cache.get("alice:session", "query"))
        cache.put(null, "query", tracks)
        assertNull(cache.get("alice:session", "query"))
    }
    @Test fun `large libraries are paged without repeated results or overflow`() {
        val items=(0 until 10000).toList()
        assertEquals((100 until 200).toList(),browsePage(items,1,100))
        assertEquals(10000,browsePage(items,0,Int.MAX_VALUE).size)
        assertTrue(browsePage(items,Int.MAX_VALUE,Int.MAX_VALUE).isEmpty())
        assertTrue(browsePage(items,-1,100).isEmpty())
        assertTrue(browsePage(items,0,0).isEmpty())
    }
    @Test fun `auto keeps complete external and preview ids inside a mixed context`() {
        for (id in listOf("external|authorized-tone", "preview|abcdefghijk", "local-id")) {
            val encoded = "track|mixed|playlist-id|$id"
            assertEquals(id, realTrackId(encoded))
            assertEquals(TrackContext("mixed", "playlist-id", id), trackContext(encoded))
        }
        assertEquals(TrackContext("songs", "", "song-id"), trackContext("track|songs||song-id"))
        assertNull(trackContext("track|broken"))
        assertNull(trackContext("external|tone"))
    }
}
