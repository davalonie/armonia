package com.armonia.app.ui.homelab

import com.armonia.app.homelab.MusicTrack
import org.junit.Assert.assertEquals
import org.junit.Test

class SongsOnPhoneTest {
    @Test fun keepsPlayableLegacyFilesAndDropsEvictedSongs() {
        val metadata = listOf("kept", "evicted").associateWith { MusicTrack("navidrome", it, "Title $it", "Artist").toSong() }
        val songs = songsOnPhone(setOf("legacy", "kept"), metadata)
        assertEquals(listOf("legacy", "kept"), songs.map { it.id })
        assertEquals("Title kept", songs.last().title)
        assertEquals(emptyList<String>(), songsOnPhone(emptySet(), metadata).map { it.id })
    }
}
