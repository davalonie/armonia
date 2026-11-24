package com.armonia.app.ui.components

import androidx.lifecycle.ViewModel
import com.armonia.app.data.api.Song
import com.armonia.app.data.repository.LibraryRepository
import com.armonia.app.playback.MusicPlayer
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject

@HiltViewModel
class SongActionsViewModel @Inject constructor(
    private val repository: LibraryRepository,
    private val player: MusicPlayer,
) : ViewModel() {
    fun playNext(song: Song) = player.playNext(song)
    suspend fun rate(song: Song, rating: Int) = repository.setRating(song.id, rating)
    fun addToQueue(song: Song) = player.addToQueue(song)
    fun addToEnd(song: Song) = player.addToEnd(song)
    suspend fun favorite(song: Song, on: Boolean) = if (on) repository.star(song.id) else repository.unstar(song.id)
}
