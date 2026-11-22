package com.armonia.app.homelab

import com.google.gson.Gson
import org.junit.Assert.*
import org.junit.Test

class PlaylistContractTest {
    @Test fun `list summaries carry count without requiring track arrays`() {
        val list = Gson().fromJson("""{"playlists":[{"id":"p","name":"Private","revision":2,"item_count":500}]}""", MixedLists::class.java)
        assertEquals(500, list.playlists.single().itemCount)
        assertEquals("p", list.playlists.single().id)
    }
    @Test fun `detail retains duplicate entries and provider identifiers`() {
        val result = Gson().fromJson("""{"id":"p","name":"Private","revision":2,"items":[{"id":"entry1","track":{"source":"authorized_http","source_id":"tone","title":"T","artist":"A"}},{"id":"entry2","track":{"source":"authorized_http","source_id":"tone","title":"T","artist":"A"}}]}""", MixedPlaylist::class.java)
        assertEquals(2,result.items.size)
        assertEquals("external|tone",result.items[1].track.toSong().id)
    }
}
