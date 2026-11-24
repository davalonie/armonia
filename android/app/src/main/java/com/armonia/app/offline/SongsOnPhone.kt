package com.armonia.app.offline

import com.armonia.app.data.api.Song
import com.armonia.app.homelab.MusicTrack

/** The songs this phone can play without a connection, with the best metadata it knows, by title. */
fun songsOnPhone(available: Set<String>, metadata: Map<String, Song>): List<Song> =
    available.map { id -> metadata[id] ?: MusicTrack("navidrome", id, id, "").toSong() }
        .sortedBy { it.title.lowercase() }
