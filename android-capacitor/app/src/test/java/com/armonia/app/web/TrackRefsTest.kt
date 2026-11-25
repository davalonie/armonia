package com.armonia.app.web

import com.armonia.app.homelab.asMusicTrack
import com.google.gson.Gson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class TrackRefsTest {
    private val gson = Gson()

    @Test fun externalReferenceWithoutOptionalFieldsCanBeCopied() {
        // What Search used to send for «Paseo»: no artist_mbids and no album.
        val track = TrackRefs.musicTrack("""{"source":"youtube","source_id":"abc_DEF-123","title":"Paseo","artist":"Estopa","duration":null}""")
        assertEquals(emptyList<String>(), track.artistMbids)
        assertEquals("", track.album)
        assertNull(track.duration)
        // Scrobbler.sample does exactly this; it threw NullPointerException before.
        val copied = track.copy(duration = 201.0)
        assertEquals(201.0, copied.duration!!, 0.0)
        assertEquals("preview|abc_DEF-123", track.toSong().id)
    }

    @Test fun gsonAloneLeavesKotlinDefaultsNull() {
        // The cause of the crash: no empty constructor, so Gson never runs the Kotlin defaults.
        val raw = gson.fromJson("""{"source":"youtube","source_id":"x1","title":"T","artist":"A"}""",
            com.armonia.app.homelab.MusicTrack::class.java)
        @Suppress("SENSELESS_COMPARISON") assertEquals(true, raw.artistMbids == null)
        assertThrows(NullPointerException::class.java) { raw.copy(duration = 1.0) }
    }

    @Test fun explicitNullsBecomeDefaults() {
        val track = TrackRefs.musicTrack("""{"source":"youtube","source_id":"x1","title":"T","artist":"A","album":null,"artist_mbids":null,"isrc":null,"recording_mbid":null}""")
        assertEquals("", track.album)
        assertEquals(emptyList<String>(), track.artistMbids)
        track.copy(duration = 1.0)
    }

    @Test fun keepsOnlyValidIdentifiers() {
        val good = "0383dadf-2a4e-4d10-a46a-e9e041da8eb3"
        val track = TrackRefs.musicTrack("""{"source":"youtube","source_id":"x1","title":"T","artist":"A","duration":180.5,
            "artist_mbids":["$good","nope",null,"$good"],"recording_mbid":"bad","isrc":"ESA011234567"}""")
        assertEquals(listOf(good), track.artistMbids)
        assertNull(track.recordingMbid)
        assertEquals("ESA011234567", track.isrc)
        assertEquals(180.5, track.duration!!, 0.0)
    }

    @Test fun rejectsReferencesWithoutRequiredFields() {
        listOf(
            """{"source":"spotify","source_id":"x1","title":"T","artist":"A"}""",
            """{"source_id":"x1","title":"T","artist":"A"}""",
            """{"source":"youtube","title":"T","artist":"A"}""",
            """{"source":"youtube","source_id":"a/b","title":"T","artist":"A"}""",
            """{"source":"youtube","source_id":"x1","title":null,"artist":"A"}""",
            """{"source":"youtube","source_id":"x1","title":"T","artist":" "}""",
        ).forEach { json -> assertThrows(IllegalArgumentException::class.java) { TrackRefs.musicTrack(json) } }
    }

    @Test fun librarySongWithoutArtistDoesNotCrashTheScrobbler() {
        val song = TrackRefs.song(gson, """{"id":"s1","title":"Pleamar","duration":200}""")
        assertEquals("", song.artist)
        song.asMusicTrack().copy(duration = 1.0)
    }

    @Test fun nestedReferenceIsNormalisedOrDropped() {
        val kept = TrackRefs.song(gson, """{"id":"preview|x1","title":"T","artist":"A","duration":1,
            "musicTrack":{"source":"youtube","source_id":"x1","title":"T","artist":"A"}}""")
        assertEquals(emptyList<String>(), kept.musicTrack!!.artistMbids)
        kept.asMusicTrack().copy(duration = 1.0)
        val dropped = TrackRefs.song(gson, """{"id":"s1","title":"T","artist":"A","duration":1,"musicTrack":{"source":"youtube"}}""")
        assertNull(dropped.musicTrack)
        assertEquals("navidrome", dropped.asMusicTrack().source)
    }
}
