package com.armonia.app.ui.components

import coil.ImageLoader
import com.armonia.app.playback.PathRate

/**
 * The size of the big cover in the full player: 1024 px on Wi-Fi, 600 px on mobile data (the listener's
 * choice, 18-11-2026), unless the 1024 px one is already on the phone. Measured on 30 covers of the library
 * (JPEG): 1024 px about 54 KB, 600 px about 24 KB, 128 px (lists) about 2 KB. Every cover is kept on the phone
 * for good (the server lets it, see middleware/main.py), so each size of a cover is downloaded once.
 */
object CoverSizes {
    const val PLAYER = 1024
    const val PLAYER_ON_DATA = 600

    fun player(url: (Int) -> String, loader: ImageLoader, onMobileData: Boolean = PathRate.metered()): String {
        val big = url(PLAYER)
        if (!onMobileData || kept(loader, big)) return big
        return url(PLAYER_ON_DATA)
    }

    fun kept(loader: ImageLoader, url: String): Boolean = runCatching {
        loader.memoryCache?.keys?.any { it.key == url } == true ||
            loader.diskCache?.openSnapshot(url)?.use { true } == true
    }.getOrDefault(false)
}
