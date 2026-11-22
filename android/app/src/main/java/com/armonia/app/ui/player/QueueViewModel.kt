package com.armonia.app.ui.player

import androidx.lifecycle.ViewModel
import com.armonia.app.data.repository.LibraryRepository
import com.armonia.app.playback.MusicPlayer
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject

@HiltViewModel
class QueueViewModel @Inject constructor(
    val musicPlayer: MusicPlayer,
    private val libraryRepo: LibraryRepository,
) : ViewModel() {

    fun getCoverUrl(coverArt: String, size: Int = 128): String =
        libraryRepo.getCoverArtUrl(coverArt, size)
}
