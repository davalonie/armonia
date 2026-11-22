package com.armonia.app.playback

/** Extracts the real Subsonic track id from a (possibly context-encoded) mediaId. */
fun realTrackId(mediaId: String): String =
    if (mediaId.startsWith("track|")) mediaId.split('|', limit=4).last() else mediaId

/** Previews (`preview|<videoId>`) aren't library tracks. */
fun isPreviewMediaId(mediaId: String): Boolean = (mediaId.startsWith("preview|") || mediaId.startsWith("external|"))

/** Keep provider-qualified IDs intact after removing the outer context marker. */
data class TrackContext(val type: String, val id: String, val trackId: String)
fun trackContext(mediaId: String): TrackContext? {
    if (!mediaId.startsWith("track|")) return null
    val parts = mediaId.removePrefix("track|").split('|', limit = 3)
    return if (parts.size == 3 && parts[2].isNotBlank()) TrackContext(parts[0], parts[1], parts[2]) else null
}
