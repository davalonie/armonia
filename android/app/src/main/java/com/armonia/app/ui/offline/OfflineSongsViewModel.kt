package com.armonia.app.ui.offline

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.armonia.app.data.api.Song
import com.armonia.app.offline.OfflineManager
import com.armonia.app.offline.OfflineSongState
import com.armonia.app.ui.components.OfflineSongAction
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import javax.inject.Inject

/** Per-song "Descargar en el teléfono" state and action, shared by every song list. */
@HiltViewModel
class OfflineSongsViewModel @Inject constructor(
    private val offline: OfflineManager,
) : ViewModel() {

    val states: StateFlow<Map<String, OfflineSongState>> =
        offline.songStates.stateIn(viewModelScope, SharingStarted.Eagerly, offline.songStates.value)

    fun actionFor(song: Song, states: Map<String, OfflineSongState>): OfflineSongAction {
        val state = states[song.id] ?: OfflineSongState.NONE
        return OfflineSongAction(state) {
            when (state) {
                OfflineSongState.NONE -> offline.pinSong(song)
                OfflineSongState.DOWNLOADING, OfflineSongState.DOWNLOADED -> offline.unpinSong(song.id)
                OfflineSongState.IN_COLLECTION -> Unit
            }
        }
    }
}
