package com.armonia.app.ui.playlists

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.armonia.app.data.api.PlaylistDetail
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
class PlaylistDetailViewModel @Inject constructor(
    private val repository: LibraryRepository,
    val musicPlayer: MusicPlayer,
    private val offline: OfflineManager,
    savedStateHandle: SavedStateHandle,
) : ViewModel() {

    val playlistId: String = savedStateHandle.get<String>("id") ?: ""

    var playlist by mutableStateOf<PlaylistDetail?>(null)
    var isLoading by mutableStateOf(true)
    var error by mutableStateOf<String?>(null)

    // ── Keep offline ────────────────────────────────────────────────────────
    var isPinnedOffline by mutableStateOf(false)
        private set
    var offlineProgress by mutableStateOf<OfflineProgress?>(null)
        private set

    private val offlineKey get() = OfflineCollection.playlistKey(playlistId)

    init {
        viewModelScope.launch { offline.catalog.collect { isPinnedOffline = it.find(offlineKey) != null } }
        viewModelScope.launch { offline.progress.collect { offlineProgress = it[offlineKey] } }
    }

    fun toggleOffline() {
        if (isPinnedOffline) {
            offline.unpin(offlineKey)
            return
        }
        val a = playlist ?: return
        offline.pin(OfflineCollection(
            key = OfflineCollection.playlistKey(playlistId),
            title = a.name,
            subtitle = "Playlist · ${a.entry.orEmpty().size} canciones",
            coverArt = a.coverArt ?: a.entry.orEmpty().firstOrNull()?.coverArt,
            songs = a.entry.orEmpty(),
            pinnedAt = System.currentTimeMillis(),
        ))
    }
    var allLibrarySongs by mutableStateOf<List<Song>>(emptyList())
    var pickerLoading by mutableStateOf(false)

    var starredOverrides by mutableStateOf<Map<String, Boolean>>(emptyMap())
        private set

    init { load() }

    /** Showing the copy saved on the phone because the server could not be reached. */
    var stale by mutableStateOf(false)
        private set

    fun load(pulled: Boolean = false) {
        if (playlistId.isBlank()) {
            error = "Falta el identificador de la playlist"
            isLoading = false
            return
        }
        error = null
        viewModelScope.launch {
            // What the phone remembers first; the server's answer replaces it when it arrives.
            if (playlist == null) repository.cachedPlaylist(playlistId)?.let { playlist = it }
            isLoading = pulled || playlist == null
            repository.getPlaylist(playlistId)
                .onSuccess { playlist = it.playlist; stale = false }
                .onFailure { if (playlist == null) error = it.message else stale = true }
            isLoading = false
        }
    }

    fun playFromIndex(index: Int) {
        val list = playlist?.entry ?: return
        musicPlayer.playQueue(list, index, playlistId = playlistId, from = playlist?.name)
    }

    fun playAll() = playFromIndex(musicPlayer.collectionStart(playlist?.entry.orEmpty()))


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

    /** Removes the song from the list immediately; the server delete follows in the background. */
    fun deleteSong(song: Song) {
        val before = playlist
        playlist = playlist?.let { p -> p.copy(entry = p.entry?.filter { it.id != song.id }) }
        repository.deleteInBackground(song) { playlist = before }
    }

    fun removeFromPlaylist(index: Int) {
        viewModelScope.launch {
            repository.removeSongFromPlaylist(playlistId, index)
                .onSuccess { load() }
                .onFailure { notice = "No se pudo quitar la cancion: ${it.message}" }
        }
    }

    /** A failed action on a list that is still shown; [error] is for a list that could not load. */
    var notice by mutableStateOf<String?>(null)

    // ── Añadir canciones ────────────────────────────────────────────────────
    val currentSong = musicPlayer.currentSong
    val playingPlaylistId = musicPlayer.playingPlaylistId
    fun togglePlayPause() = musicPlayer.togglePlayPause()
    val isPlaying = musicPlayer.isPlaying
    val auditionId = musicPlayer.auditionId
    val progress = musicPlayer.progress

    /** Loads the full library list for the "Añadir canciones" screen. */
    fun loadLibrarySongs() {
        if (allLibrarySongs.isNotEmpty() || pickerLoading) return
        pickerLoading = true
        pickerError = null
        viewModelScope.launch {
            repository.getSongs()
                .onSuccess { list -> allLibrarySongs = list.sortedWith(compareBy({ it.artist.lowercase() }, { it.title.lowercase() })) }
                .onFailure { pickerError = "No se pudo cargar tu biblioteca. Comprueba la conexion." }
            pickerLoading = false
        }
    }
    var pickerError by mutableStateOf<String?>(null)
        private set

    private val adder = PlaylistAdder(
        send = { id -> repository.addUniqueToPlaylist(playlistId, id) },
        remove = { id -> repository.removeLastFromPlaylist(playlistId, id) },
    )
    val addStates = adder.states

    fun stateOf(song: Song): AddState = adder.stateOf(song.id, inPlaylist(song))

    private fun inPlaylist(song: Song) = playlist?.entry.orEmpty().any { it.id == song.id }

    /** The song offered for "Deshacer"; cleared when undone or dismissed. */
    var lastAdded by mutableStateOf<Song?>(null)

    fun addSong(song: Song) {
        viewModelScope.launch {
            val before = adder.stateOf(song.id, inPlaylist(song))
            if (adder.add(song.id, inPlaylist(song))) {
                playlist = playlist?.let { p -> p.copy(entry = p.entry.orEmpty() + song) }
                lastAdded = song
            } else if (before == AddState.NONE || before == AddState.FAILED) {
                notice = "No se pudo añadir «${song.title}». Pulsa + para reintentar."
            }
        }
    }

    fun undoAdd(song: Song) {
        if (!adder.canUndo(song.id)) return  // not ours to undo, or the tail of a double tap on +
        viewModelScope.launch {
            if (lastAdded?.id == song.id) lastAdded = null
            if (adder.undo(song.id)) {
                playlist = playlist?.let { p ->
                    val at = p.entry.orEmpty().indexOfLast { it.id == song.id }
                    p.copy(entry = p.entry.orEmpty().filterIndexed { i, _ -> i != at })
                }
            } else notice = "No se pudo deshacer. «${song.title}» sigue en la playlist."
        }
    }

    /** Ten seconds from the middle; tapping the song that is sounding stops it. Never adds or downloads. */
    fun togglePreview(song: Song) {
        if (musicPlayer.auditionId.value == song.id) musicPlayer.stopAudition()
        else musicPlayer.audition(song, resumeAfter = true)
    }

    fun stopPreview() = musicPlayer.stopAudition()

    fun getCoverUrl(id: String, size: Int = 128): String =
        repository.getCoverArtUrl(id, size)
}
