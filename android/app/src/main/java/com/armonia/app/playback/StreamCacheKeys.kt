package com.armonia.app.playback

/** A cache entry belongs to a server and account, never to an ephemeral bearer. */
object StreamCacheKeys {
    fun keyFor(url: String, account: String = "legacy-disabled"): String =
        account + ":" + url.substringBefore('?')

    /**
     * Playback asks the server for the light copy of a song by default (or another variant, see Variants.kt) (no cover embedded in its header, see
     * middleware/services/mp4_light.py): a different file from the original that offline downloads keep,
     * so it is never stored under the same key.
     */
    fun playbackKeyFor(url: String, account: String = "legacy-disabled"): String = Variant.LIGERA.key(keyFor(url, account))
}
