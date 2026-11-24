package com.armonia.app.ui.offline

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.armonia.app.data.api.Song
import com.armonia.app.data.repository.LibraryRepository
import com.armonia.app.offline.OfflineCatalog
import com.armonia.app.offline.OfflineCollection
import com.armonia.app.offline.OfflineManager
import com.armonia.app.offline.OfflineProgress
import com.armonia.app.playback.MusicPlayer
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class OfflineViewModel @Inject constructor(
    private val offline: OfflineManager,
    private val repository: LibraryRepository,
    val musicPlayer: MusicPlayer,
) : ViewModel() {

    val persistenceProblem = offline.persistenceProblem

    var catalog by mutableStateOf(OfflineCatalog())
        private set
    var progress by mutableStateOf<Map<String, OfflineProgress>>(emptyMap())
        private set
    var selected by mutableStateOf<OfflineCollection?>(null)
        private set
    /** Ids of the selected collection's songs that are fully on disk (computed off the UI thread). */
    var cachedIds by mutableStateOf<Set<String>>(emptySet())
        private set

    init {
        viewModelScope.launch {
            offline.catalog.collect { c ->
                catalog = c
                selected = selected?.let { c.find(it.key) }
            }
        }
        viewModelScope.launch {
            offline.progress.collect {
                progress = it
                refreshCached()
            }
        }
    }

    fun select(collection: OfflineCollection?) {
        selected = collection
        cachedIds = emptySet()
        refreshCached()
    }

    private fun refreshCached() {
        val c = selected ?: return
        viewModelScope.launch { cachedIds = offline.cachedSongIds(c.songs) }
    }

    fun getCoverUrl(coverArt: String): String = repository.getCoverArtUrl(coverArt)

    fun play(songs: List<Song>, index: Int) = musicPlayer.playQueue(songs, index)


    fun remove(key: String) {
        offline.unpin(key)
        if (selected?.key == key) select(null)
    }
}
