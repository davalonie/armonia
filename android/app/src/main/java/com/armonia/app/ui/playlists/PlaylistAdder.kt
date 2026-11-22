package com.armonia.app.ui.playlists

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

enum class AddState(val inPlaylist: Boolean) {
    NONE(false), SENDING(false), ADDED(true), ALREADY(true), FAILED(false)
}

/**
 * The + button of "Añadir canciones", one song at a time.
 *
 * A song whose request is in flight is not sent again, so a double tap is one addition. Nothing
 * counts as added until [send] succeeds; a failure leaves the song addable again. [send] itself
 * must be idempotent (add only if absent), which makes a retry after a lost answer safe.
 */
class PlaylistAdder(
    private val send: suspend (songId: String) -> Result<Unit>,
    private val remove: suspend (songId: String) -> Result<Unit>,
    private val now: () -> Long = { System.nanoTime() / 1_000_000 },
) {
    private val addedAt = mutableMapOf<String, Long>()

    private val _states = MutableStateFlow<Map<String, AddState>>(emptyMap())
    val states: StateFlow<Map<String, AddState>> = _states.asStateFlow()

    fun stateOf(songId: String, alreadyInPlaylist: Boolean): AddState =
        _states.value[songId] ?: if (alreadyInPlaylist) AddState.ALREADY else AddState.NONE

    /** True if the song was added by this call; false if the tap was ignored or the server refused. */
    suspend fun add(songId: String, alreadyInPlaylist: Boolean): Boolean {
        val now = stateOf(songId, alreadyInPlaylist)
        if (now == AddState.SENDING || now.inPlaylist) return false
        _states.value += songId to AddState.SENDING
        val ok = send(songId).isSuccess
        if (ok) addedAt[songId] = now()
        _states.value += songId to if (ok) AddState.ADDED else AddState.FAILED
        return ok
    }

    /** False for a song this screen did not add, and for the instant after adding it. */
    fun canUndo(songId: String): Boolean =
        _states.value[songId] == AddState.ADDED && now() - (addedAt[songId] ?: 0L) >= UNDO_GUARD_MS

    /**
     * Only what this screen added can be undone. True if it is no longer in the playlist.
     *
     * The undo control appears where + was. A second tap of a double tap that lands just after
     * a fast server answered must not remove what the first one added, so undo is ignored for
     * a moment after the addition.
     */
    suspend fun undo(songId: String): Boolean {
        if (!canUndo(songId)) return false
        _states.value += songId to AddState.SENDING
        val ok = remove(songId).isSuccess
        _states.value = if (ok) _states.value - songId else _states.value + (songId to AddState.ADDED)
        return ok
    }

    companion object {
        const val UNDO_GUARD_MS = 700L
    }
}
