package com.armonia.app.playback

/**
 * When a song cannot be loaded and retrying did not help, playback goes on with the next song
 * of the queue that is already on the phone (downloaded, or kept from having been played).
 */
object OfflineSkip {
    /** How many songs are passed over to reach [target] in [upcoming], the failed one included. */
    data class Jump(val target: Int, val skipped: Int)

    /** [upcoming] is the play order after the failed song; null when none of it is on the phone. */
    fun next(upcoming: List<Int>, onPhone: (Int) -> Boolean): Jump? {
        val at = upcoming.indexOfFirst(onPhone)
        return if (at < 0) null else Jump(upcoming[at], at + 1)
    }

    fun notice(skipped: Int): String =
        if (skipped == 1) "Sin conexion: se salta una cancion que no esta en el telefono."
        else "Sin conexion: se saltan $skipped canciones que no estan en el telefono."

    const val NOTHING_ON_PHONE = "Sin conexion: ninguna de las siguientes canciones esta guardada en el telefono."
}
