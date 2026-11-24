package com.armonia.app.ui.library

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.armonia.app.data.api.AlbumDetail
import com.armonia.app.data.api.Song
import com.armonia.app.data.repository.LibraryRepository
import com.armonia.app.offline.OfflineCollection
import com.armonia.app.offline.OfflineManager
import com.armonia.app.offline.OfflineProgress
import com.armonia.app.playback.MusicPlayer
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class AlbumDetailViewModel @Inject constructor(
    private val repository: LibraryRepository,
    val musicPlayer: MusicPlayer,
    private val offline: OfflineManager,
    savedStateHandle: SavedStateHandle,
) : ViewModel() {

    private val albumId: String = savedStateHandle.get<String>("id") ?: ""

    var album by mutableStateOf<AlbumDetail?>(null)
    var isLoading by mutableStateOf(true)
    var error by mutableStateOf<String?>(null)

    // ── Keep offline ────────────────────────────────────────────────────────
    var isPinnedOffline by mutableStateOf(false)
        private set
    var offlineProgress by mutableStateOf<OfflineProgress?>(null)
        private set

    private val offlineKey get() = OfflineCollection.albumKey(albumId)

    init {
        viewModelScope.launch { offline.catalog.collect { isPinnedOffline = it.find(offlineKey) != null } }
        viewModelScope.launch { offline.progress.collect { offlineProgress = it[offlineKey] } }
    }

    fun toggleOffline() {
        if (isPinnedOffline) {
            offline.unpin(offlineKey)
            return
        }
        val a = album ?: return
        offline.pin(OfflineCollection(
            key = OfflineCollection.albumKey(albumId),
            title = a.name,
            subtitle = a.artist,
            coverArt = a.song.firstOrNull()?.coverArt,
            songs = a.song,
            pinnedAt = System.currentTimeMillis(),
        ))
    }

    var starredOverrides by mutableStateOf<Map<String, Boolean>>(emptyMap())
        private set

    init { load() }

    fun load() {
        if (albumId.isBlank()) {
            error = "Missing album id"
            isLoading = false
            return
        }
        isLoading = true
        error = null
        viewModelScope.launch {
            repository.getAlbum(albumId)
                .onSuccess { album = it.album }
                .onFailure { error = it.message }
            isLoading = false
        }
    }

    fun playFromIndex(index: Int) {
        val list = album?.song ?: return
        musicPlayer.playQueue(list, index, from = album?.name)
    }

    fun playAll() = playFromIndex(musicPlayer.collectionStart(album?.song.orEmpty()))


    fun addToQueue(song: Song) {
        musicPlayer.addToQueue(song)
    }

    fun isStarred(song: Song): Boolean {
        return starredOverrides[song.id] ?: !song.starred.isNullOrEmpty()
    }

    fun toggleStar(song: Song) {
        val was = isStarred(song)
        starredOverrides = starredOverrides + (song.id to !was)
        viewModelScope.launch {
            val result = if (was) repository.unstar(song.id) else repository.star(song.id)
            if (result.isFailure) {
                starredOverrides = starredOverrides + (song.id to was)
            }
        }
    }

    /** Removes the song from the album immediately; the server delete follows in the background. */
    fun deleteSong(song: Song) {
        val before = album
        album = album?.copy(song = album!!.song.filter { it.id != song.id })
        repository.deleteInBackground(song) { album = before }
    }

    fun getCoverUrl(id: String, size: Int = 512): String =
        repository.getCoverArtUrl(id, size)
}
