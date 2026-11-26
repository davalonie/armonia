package com.armonia.app.web

import com.armonia.app.data.api.Song
import com.armonia.app.homelab.MusicTrack
import com.google.gson.Gson
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParser

/**
 * Track references sent by the web. MusicTrack has no empty constructor, so Gson ignores the
 * Kotlin defaults and leaves every missing field null; the first copy() then crashes (Scrobbler
 * at half the song when `artist_mbids` was not sent). They are built field by field instead.
 */
internal object TrackRefs {
    private val sources = setOf("navidrome", "youtube", "authorized_http")
    private val sourceId = Regex("[A-Za-z0-9_-]{1,128}")
    private val mbid = Regex("[a-fA-F0-9]{8}(-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}")
    private val isrc = Regex("[A-Z]{2}[A-Z0-9]{3}[0-9]{7}")

    private fun JsonElement?.text(): String? = this?.takeIf { it.isJsonPrimitive }?.asString
    private fun JsonObject.text(key: String) = get(key).text()

    fun musicTrack(json: String): MusicTrack = musicTrack(JsonParser.parseString(json).asJsonObject)

    fun musicTrack(ref: JsonObject): MusicTrack {
        val source = requireNotNull(ref.text("source")?.takeIf { it in sources }) { "Fuente de la cancion desconocida" }
        val id = ref.text("source_id").orEmpty()
        require(sourceId.matches(id)) { "La cancion no tiene identificador" }
        val title = ref.text("title").orEmpty()
        val artist = ref.text("artist").orEmpty()
        require(title.isNotBlank() && artist.isNotBlank()) { "La cancion no tiene titulo o artista" }
        val duration = ref.get("duration")?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isNumber }
            ?.asDouble?.takeIf { it.isFinite() && it > 0 }
        val artistMbids = ref.get("artist_mbids")?.takeIf { it.isJsonArray }?.asJsonArray
            ?.mapNotNull { it.text()?.takeIf(mbid::matches) }?.distinct()?.take(20).orEmpty()
        return MusicTrack(
            source = source, sourceId = id, title = title, artist = artist,
            album = ref.text("album").orEmpty(), duration = duration,
            recordingMbid = ref.text("recording_mbid")?.takeIf(mbid::matches),
            artistMbids = artistMbids, isrc = ref.text("isrc")?.takeIf(isrc::matches),
        )
    }

    /** A library song: Gson would also leave its required `artist` null when it is missing. */
    fun song(gson: Gson, json: String): Song {
        val obj = JsonParser.parseString(json).asJsonObject
        if (obj.text("artist") == null) obj.addProperty("artist", "")
        obj.get("musicTrack")?.let { nested ->
            val track = runCatching { musicTrack(nested.asJsonObject) }.getOrNull()
            // An unusable reference is dropped; asMusicTrack() then derives it from the song.
            if (track == null) obj.remove("musicTrack") else obj.add("musicTrack", gson.toJsonTree(track))
        }
        return gson.fromJson(obj, Song::class.java)
    }
}
