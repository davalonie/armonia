package com.armonia.app.ui.library

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.armonia.app.data.api.Album
import com.armonia.app.data.api.Artist
import com.armonia.app.data.repository.LibraryRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

/** One artist of the library with what the list shows about it. */
data class ArtistEntry(val artist: Artist, val albums: Int, val cover: String?)

/**
 * Albums and album artists of the library, loaded once for both screens.
 *
 * With external services off the server has no artist pictures, so an artist is shown with the
 * cover of one of their albums; nothing is requested from outside for that.
 */
@HiltViewModel
class CollectionViewModel @Inject constructor(private val repository: LibraryRepository) : ViewModel() {
    var albums by mutableStateOf<List<Album>>(emptyList()); private set
    var artists by mutableStateOf<List<ArtistEntry>>(emptyList()); private set
    var isLoading by mutableStateOf(true); private set
    var error by mutableStateOf<String?>(null); private set
    // Kept here, not in the screen: they survive opening an album or artist and coming back.
    var albumQuery by mutableStateOf("")
    var albumSort by mutableStateOf("name")
    var artistQuery by mutableStateOf("")
    var artistSort by mutableStateOf("name")

    init {
        load()
        viewModelScope.launch { repository.libraryChanged.collect { load(silent = true) } }
    }

    fun load(silent: Boolean = false) {
        if (!silent) isLoading = true
        viewModelScope.launch {
            val all = mutableListOf<Album>()
            val visible = mutableListOf<Album>()
            var failure: Throwable? = null
            while (failure == null) {
                val page = repository.getAlbumList("alphabeticalByName", 500, all.size)
                    .onFailure { failure = it }.getOrNull()?.albumList2 ?: break
                all += page.album
                visible += page.album.filter { it.name != page.defaultAlbum }
                if (page.album.size < 500) break
            }
            val listed = repository.getArtists().onFailure { failure = failure ?: it }.getOrNull()
                ?.artists?.index?.flatMap { it.artist }.orEmpty()
            if (failure != null && all.isEmpty() && listed.isEmpty()) {
                error = "No se pudo cargar tu colección. Comprueba la conexión."
            } else {
                error = null
                albums = visible
                artists = artistEntries(listed, all)
            }
            isLoading = false
        }
    }

    fun cover(id: String, size: Int = 300) = repository.getCoverArtUrl(id, size)

    val shownAlbums: List<Album> get() = filterAlbums(albums, albumQuery, albumSort)
    val shownArtists: List<ArtistEntry> get() = filterArtists(artists, artistQuery, artistSort)
}

internal fun artistEntries(artists: List<Artist>, albums: List<Album>): List<ArtistEntry> {
    val byArtist = albums.filter { it.artistId != null }.groupBy { it.artistId }
    return artists.map { artist ->
        val own = byArtist[artist.id].orEmpty()
        ArtistEntry(artist, maxOf(artist.albumCount, own.size), own.firstNotNullOfOrNull { it.coverArt })
    }
}

internal fun filterAlbums(albums: List<Album>, query: String, sort: String): List<Album> {
    val q = query.trim()
    val found = if (q.isEmpty()) albums else albums.filter { com.armonia.app.ui.components.matchesSearch(q, it.name, it.artist) }
    return when (sort) {
        "artist" -> found.sortedWith(compareBy({ it.artist.lowercase() }, { it.name.lowercase() }))
        "year" -> found.sortedWith(compareByDescending<Album> { it.year ?: 0 }.thenBy { it.name.lowercase() })
        else -> found.sortedBy { it.name.lowercase() }
    }
}

internal fun filterArtists(artists: List<ArtistEntry>, query: String, sort: String): List<ArtistEntry> {
    val q = query.trim()
    val found = if (q.isEmpty()) artists else artists.filter { com.armonia.app.ui.components.matchesSearch(q, it.artist.name) }
    return when (sort) {
        "albums" -> found.sortedWith(compareByDescending<ArtistEntry> { it.albums }.thenBy { it.artist.name.lowercase() })
        else -> found.sortedBy { it.artist.name.lowercase() }
    }
}

internal fun albumCount(n: Int) = if (n == 1) "1 álbum" else "$n álbumes"
