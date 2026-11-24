package com.armonia.app.ui.playlists

import com.armonia.app.ui.components.FastScroll
import com.armonia.app.ui.components.scrollInitial
import androidx.compose.runtime.remember
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.DownloadDone
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.RemoveCircleOutline
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material.icons.outlined.DownloadForOffline
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.pulltorefresh.rememberPullToRefreshState
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import com.armonia.app.data.api.Song
import com.armonia.app.offline.OfflineProgress
import com.armonia.app.ui.components.AddToPlaylistSheet
import com.armonia.app.ui.components.MenuAction
import com.armonia.app.ui.components.SongRow
import com.armonia.app.ui.components.matchesSearch
import com.armonia.app.ui.components.rememberOfflineToggle

/** "3 h 12 min" / "47 min", from seconds. */
internal fun totalDuration(seconds: Int): String {
    val minutes = (seconds + 30) / 60
    return if (minutes >= 60) "${minutes / 60} h ${minutes % 60} min" else "$minutes min"
}

internal fun songCount(n: Int) = if (n == 1) "1 cancion" else "$n canciones"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlaylistDetailScreen(
    onBack: () -> Unit,
    onAddSongs: () -> Unit = {},
    viewModel: PlaylistDetailViewModel = hiltViewModel(),
) {
    // "Descargar en el telefono" state for each song row.
    val offlineSongs: com.armonia.app.ui.offline.OfflineSongsViewModel = hiltViewModel()
    val offlineStates by offlineSongs.states.collectAsState()
    val playlist = viewModel.playlist
    var deleteTarget by remember { mutableStateOf<Song?>(null) }
    var playlistTarget by remember { mutableStateOf<Song?>(null) }
    // Saved, so coming back from a song's album or from "Añadir canciones" keeps the search.
    var searchOpen by rememberSaveable { mutableStateOf(false) }
    var query by rememberSaveable { mutableStateOf("") }
    var sort by rememberSaveable { mutableStateOf("original") }
    val entries = playlist?.entry.orEmpty()
    val rows = remember(entries, query, sort) {
        entries.withIndex().filter { (_, song) ->
            matchesSearch(query, song.title, song.artist, song.album)
        }.let { found ->
            when (sort) {
                "title" -> found.sortedBy { it.value.title.lowercase() }
                "artist" -> found.sortedBy { it.value.artist.lowercase() }
                else -> found
            }
        }
    }
    val listState = rememberLazyListState()
    val titleInBar by remember { derivedStateOf { listState.firstVisibleItemIndex > 0 } }
    val current by viewModel.currentSong.collectAsState()
    val playing by viewModel.isPlaying.collectAsState()
    val playingPlaylist by viewModel.playingPlaylistId.collectAsState()
    val thisIsPlaying = playingPlaylist == viewModel.playlistId && current != null
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(viewModel.notice) {
        viewModel.notice?.let { snackbar.showSnackbar(it); viewModel.notice = null }
    }

    Scaffold(
        contentWindowInsets = WindowInsets(0),
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = {
                    if (titleInBar) Text(
                        text = playlist?.name.orEmpty(),
                        style = MaterialTheme.typography.titleMedium,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Volver")
                    }
                },
                actions = {
                    if (entries.isNotEmpty()) IconButton(onClick = {
                        searchOpen = !searchOpen
                        if (!searchOpen) { query = ""; sort = "original" }
                    }) {
                        Icon(
                            if (searchOpen) Icons.Default.Close else Icons.Default.Search,
                            contentDescription = if (searchOpen) "Cerrar la busqueda" else "Buscar y ordenar en esta playlist",
                            tint = if (searchOpen) MaterialTheme.colorScheme.primary else LocalContentColor.current,
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
        }
    ) { padding ->
        val pullState = rememberPullToRefreshState()
        PullToRefreshBox(
            isRefreshing = viewModel.isLoading,
            onRefresh = { viewModel.load(pulled = true) },
            state = pullState,
            modifier = Modifier.padding(padding).fillMaxSize(),
        ) {
            when {
                viewModel.isLoading && playlist == null -> CircularProgressIndicator(modifier = Modifier.align(Alignment.Center))
                viewModel.error != null -> Column(Modifier.align(Alignment.Center).padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("No se pudo cargar la playlist.", color = MaterialTheme.colorScheme.error)
                    OutlinedButton(onClick = { viewModel.load() }, modifier = Modifier.padding(top = 8.dp)) { Text("Reintentar") }
                }
                playlist == null -> Text(
                    text = "Playlist no encontrada",
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                    modifier = Modifier.align(Alignment.Center),
                )
                else -> LazyColumn(state = listState, modifier = Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 16.dp)) {
                    item(key = "header") {
                        PlaylistHeader(
                            name = playlist.name,
                            cover = playlist.coverArt?.takeIf { it.startsWith("armonia-art-") }?.let { viewModel.getCoverUrl(it, 256) },
                            songs = entries.size,
                            seconds = entries.sumOf { it.duration },
                            isPinnedOffline = viewModel.isPinnedOffline,
                            offlineProgress = viewModel.offlineProgress,
                            onToggleOffline = { viewModel.toggleOffline() },
                            showingPause = thisIsPlaying && playing,
                            onPlay = { if (thisIsPlaying) viewModel.togglePlayPause() else viewModel.playAll() },
                            player = viewModel.musicPlayer,
                        )
                    }
                    if (viewModel.stale) item(key = "saved-copy") { com.armonia.app.ui.components.SavedCopyNotice() }
                    if (searchOpen) item(key = "search") {
                        SearchAndSort(query, { query = it }, sort, { sort = it }, shown = rows.size, total = entries.size)
                    }
                    item(key = "add") { AddToThisListRow(onAddSongs) }
                    if (entries.isEmpty()) item(key = "empty") {
                        Text(
                            "Esta playlist todavia no tiene canciones.",
                            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 24.dp),
                        )
                    } else if (rows.isEmpty()) item(key = "none") {
                        Text(
                            "Ninguna cancion coincide con «${query.trim()}».",
                            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 24.dp),
                        )
                    }
                    itemsIndexed(items = rows, key = { _, row -> "${row.index}_${row.value.id}" }) { _, row ->
                        val index = row.index
                        val song = row.value
                        val isStarred = remember(song.id, viewModel.starredOverrides) { viewModel.isStarred(song) }
                        val onToggleStar = remember(song) { { viewModel.toggleStar(song) } }
                        val onAddToQueue = remember(song) { { viewModel.addToQueue(song) } }
                        val onClick = remember(index) { { viewModel.playFromIndex(index) } }
                        val onDelete = remember(song) { { deleteTarget = song } }
                        val onAddToPlaylist = remember(song) { { playlistTarget = song } }
                        val extraItems = remember(index) {
                            listOf(
                                MenuAction(
                                    label = "Quitar de esta playlist",
                                    icon = Icons.Default.RemoveCircleOutline,
                                    onClick = { viewModel.removeFromPlaylist(index) },
                                ),
                            )
                        }
                        val isCurrent = thisIsPlaying && current?.id == song.id
                        SongRow(
                            song = song,
                            isStarred = isStarred,
                            getCoverUrl = { viewModel.getCoverUrl(it) },
                            onClick = onClick,
                            onToggleStar = onToggleStar,
                            onAddToQueue = onAddToQueue,
                            onPlay = onClick,
                            onDelete = onDelete,
                            onAddToPlaylist = onAddToPlaylist,
                            extraMenuItems = extraItems,
                            isCurrent = isCurrent,
                            isPlayingNow = isCurrent && playing,
                            offline = offlineSongs.actionFor(song, offlineStates),
                            // The heart lives in the row's menu here: cover, text and one menu button.
                            showFavorite = false,
                        )
                    }
                }
            }
            val labels = remember(rows, sort) { rows.map { (index, song) ->
                when (sort) {
                    "title" -> scrollInitial(song.title)
                    "artist" -> scrollInitial(song.artist)
                    else -> (index + 1).toString()
                }
            } }
            FastScroll(labels, { listState.firstVisibleItemIndex }, listState.isScrollInProgress,
                2 + (if (viewModel.stale) 1 else 0) + (if (searchOpen) 1 else 0)) { listState.scrollToItem(it) }
        }
    }

    playlistTarget?.let { song ->
        AddToPlaylistSheet(song = song, onDismiss = { playlistTarget = null })
    }

    val target = deleteTarget
    if (target != null) {
        AlertDialog(
            onDismissRequest = { deleteTarget = null },
            title = { Text("¿Eliminar de la biblioteca?") },
            text = { Text("«${target.title}» se borrara del servidor para siempre, no solo de esta playlist. No se puede deshacer.") },
            confirmButton = {
                TextButton(onClick = {
                    val toDelete = target
                    deleteTarget = null
                    viewModel.deleteSong(toDelete)
                }) { Text("Eliminar", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { deleteTarget = null }) { Text("Cancelar") } },
        )
    }
}

/**
 * Title, count and one compact row of actions: the phone download on the left; shuffle and
 * the round Play on the right.
 */
@Composable
private fun PlaylistHeader(
    name: String,
    cover: String?,
    songs: Int,
    seconds: Int,
    isPinnedOffline: Boolean,
    offlineProgress: OfflineProgress?,
    onToggleOffline: () -> Unit,
    showingPause: Boolean,
    onPlay: () -> Unit,
    player: com.armonia.app.playback.MusicPlayer,
) {
    val downloading = isPinnedOffline && offlineProgress?.running == true
    val failed = offlineProgress?.failed ?: 0
    Column(modifier = Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 8.dp)) {
        if (cover != null) coil.compose.AsyncImage(cover, "Portada de $name", Modifier.size(96.dp))
        Text(
            text = name,
            style = MaterialTheme.typography.headlineMedium,
            color = MaterialTheme.colorScheme.onBackground,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = if (songs == 0) "Sin canciones" else "${songCount(songs)} · ${totalDuration(seconds)}",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
            modifier = Modifier.padding(top = 2.dp),
        )
        // The files are the server's library either way; this says whether the phone also has them.
        Text(
            text = when {
                downloading -> "En tu biblioteca · Descargando en el telefono ${offlineProgress?.done ?: 0}/${offlineProgress?.total ?: songs}"
                isPinnedOffline && failed > 0 -> "En tu biblioteca · En el telefono, $failed sin descargar"
                isPinnedOffline -> "En tu biblioteca · Descargada en este telefono"
                else -> "En tu biblioteca · No descargada en el telefono"
            },
            style = MaterialTheme.typography.bodySmall,
            color = if (isPinnedOffline && failed > 0 && !downloading) MaterialTheme.colorScheme.error
                    else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.55f),
            modifier = Modifier.padding(top = 2.dp),
        )
        com.armonia.app.ui.components.CollectionControls(
            songs = songs, isPinnedOffline = isPinnedOffline, offlineProgress = offlineProgress,
            onToggleOffline = onToggleOffline, showingPause = showingPause, onPlay = onPlay, player = player,
            playLabel = "Reproducir la playlist", modifier = Modifier.padding(top = 8.dp),
        )
    }
}

@Composable
private fun SearchAndSort(query: String, onQuery: (String) -> Unit, sort: String, onSort: (String) -> Unit, shown: Int, total: Int) {
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { if (query.isEmpty()) focus.requestFocus() }
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp)) {
        TextField(
            value = query,
            onValueChange = onQuery,
            placeholder = { Text("Buscar en esta playlist") },
            leadingIcon = { Icon(Icons.Default.Search, null) },
            trailingIcon = {
                if (query.isNotEmpty()) IconButton(onClick = { onQuery("") }) { Icon(Icons.Default.Close, "Borrar la busqueda") }
            },
            singleLine = true,
            shape = RoundedCornerShape(28.dp),
            colors = TextFieldDefaults.colors(
                focusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                focusedIndicatorColor = Color.Transparent,
                unfocusedIndicatorColor = Color.Transparent,
            ),
            modifier = Modifier.fillMaxWidth().focusRequester(focus),
        )
        Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            listOf("original" to "Orden de la lista", "title" to "Titulo", "artist" to "Artista").forEach { (key, label) ->
                FilterChip(selected = sort == key, onClick = { onSort(key) }, label = { Text(label) })
            }
        }
        if (query.isNotBlank()) Text(
            "$shown de $total",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.55f),
            modifier = Modifier.padding(top = 2.dp),
        )
    }
}

@Composable
private fun AddToThisListRow(onClick: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().height(72.dp).clickable(onClick = onClick).padding(horizontal = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(52.dp).clip(RoundedCornerShape(8.dp)).background(MaterialTheme.colorScheme.surfaceContainerHighest),
            contentAlignment = Alignment.Center,
        ) { Icon(Icons.Default.Add, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(28.dp)) }
        Spacer(Modifier.width(14.dp))
        Text("Añadir a esta lista", style = MaterialTheme.typography.titleSmall)
    }
}
