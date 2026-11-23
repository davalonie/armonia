package com.armonia.app.ui.library

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.armonia.app.data.api.ArtistDetail
import com.armonia.app.data.repository.LibraryRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class ArtistDetailViewModel @Inject constructor(
    private val repository: LibraryRepository,
    private val player: com.armonia.app.playback.MusicPlayer,
    savedStateHandle: SavedStateHandle,
) : ViewModel() {

    private val artistId: String = savedStateHandle.get<String>("id") ?: ""

    var artist by mutableStateOf<ArtistDetail?>(null)
    var isLoading by mutableStateOf(true)
    var error by mutableStateOf<String?>(null)

    init { load() }

    fun load() {
        if (artistId.isBlank()) {
            error = "Falta el identificador del artista"
            isLoading = false
            return
        }
        isLoading = true
        error = null
        viewModelScope.launch {
            repository.getArtist(artistId)
                .onSuccess { artist = it.artist }
                .onFailure { error = it.message }
            isLoading = false
        }
    }

    fun play(index: Int) = player.playQueue(artist?.song.orEmpty(), index)

    fun getCoverUrl(id: String, size: Int = 300): String =
        repository.getCoverArtUrl(id, size)
}
