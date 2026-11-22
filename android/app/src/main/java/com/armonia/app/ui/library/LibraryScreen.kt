package com.armonia.app.ui.library

import com.armonia.app.ui.components.FastScroll
import com.armonia.app.ui.components.scrollInitial
import androidx.compose.runtime.remember
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material.icons.filled.UnfoldMore
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.pulltorefresh.rememberPullToRefreshState
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import kotlinx.coroutines.delay
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import coil.compose.AsyncImage
import com.armonia.app.R
import com.armonia.app.data.api.ArtistResult
import com.armonia.app.data.api.SearchResult
import com.armonia.app.data.api.Song
import com.armonia.app.ui.components.AddToPlaylistSheet
import com.armonia.app.ui.components.MarqueeText
import com.armonia.app.ui.components.SongRow
import com.armonia.app.ui.components.YtDownloadDialog
import com.armonia.app.ui.ytmusic.DownloadButton

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LibraryScreen(
    isFavorites: Boolean = false,
    startWithSearch: Boolean = false,
    initialSearch: String = "",
    onSongClick: (Song) -> Unit,
    onOpenSettings: () -> Unit = {},
    onOpenOffline: () -> Unit = {},
    onArtistClick: (String) -> Unit = {},
    // Inside Biblioteca the tab already names the screen: a search field like the other tabs instead of a second title.
    embedded: Boolean = false,
    viewModel: LibraryViewModel = hiltViewModel()
) {
    // "Descargar en el teléfono" state for each song row.
    LaunchedEffect(initialSearch) { if (initialSearch.isNotBlank()) viewModel.searchFromHistory(initialSearch) }
    val offlineSongs: com.armonia.app.ui.offline.OfflineSongsViewModel = hiltViewModel()
    val offlineStates by offlineSongs.states.collectAsState()
    val items by remember(isFavorites, startWithSearch) {
        derivedStateOf { when {
            isFavorites -> viewModel.sortedFavorites
            startWithSearch && viewModel.filterQuery.isBlank() -> viewModel.recentSongs
            else -> viewModel.sortedSongs
        } }
    }

    var deleteTarget by remember { mutableStateOf<Song?>(null) }
    var playlistTarget by remember { mutableStateOf<Song?>(null) }
    var dlTarget by remember { mutableStateOf<SearchResult?>(null) }
    var searchOpen by remember { mutableStateOf(startWithSearch) }
    var sortSheetOpen by remember { mutableStateOf(false) }
    // Search filter, as on the web: everything, songs only or artists only.
    var filter by rememberSaveable { mutableStateOf("todo") }
    val focusRequester = remember { FocusRequester() }
    val keyboard = LocalSoftwareKeyboardController.current

    val playingSong by viewModel.currentSong.collectAsState()
    val isPlaying by viewModel.isPlaying.collectAsState()

    // Online search applies to the main Library only, not Favorites.
    val onlineEnabled = !isFavorites
    val searching by remember { derivedStateOf { viewModel.filterQuery.isNotBlank() } }

    // Show the search UI whenever the bar is explicitly open OR a query persists.
    // `searchOpen` is plain UI state that resets when the composable is recreated
    // (returning from an artist page, switching tabs); the ViewModel's query
    // survives. Deriving from both keeps an exit (back arrow / BackHandler) visible
    // so the user is never stranded in search results with the normal top bar.
    val inSearch = searchOpen || searching

    val closeSearch = {
        searchOpen = false
        viewModel.filterQuery = ""
        viewModel.clearOnline()
    }

    // System back exits the search view (instead of leaving the Library tab).
    BackHandler(enabled = inSearch) { closeSearch() }

    Scaffold(
        contentWindowInsets = WindowInsets(0),
        topBar = {
            if (inSearch) {
                TopAppBar(
                    title = {
                        TextField(
                            value = viewModel.filterQuery,
                            onValueChange = {
                                viewModel.filterQuery = it
                                if (onlineEnabled) viewModel.clearOnline()
                            },
                            placeholder = { Text(if (onlineEnabled) "¿Qué quieres escuchar?" else "Buscar en favoritos…") },
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(end = 12.dp)
                                .focusRequester(focusRequester),
                            singleLine = true,
                            shape = RoundedCornerShape(28.dp),
                            leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                            trailingIcon = {
                                if (viewModel.filterQuery.isNotEmpty()) IconButton(onClick = {
                                    viewModel.filterQuery = ""
                                    if (onlineEnabled) viewModel.clearOnline()
                                    focusRequester.requestFocus()
                                }) { Icon(Icons.Default.Close, contentDescription = "Borrar la búsqueda") }
                            },
                            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                            keyboardActions = KeyboardActions(onSearch = {
                                keyboard?.hide()
                                if (onlineEnabled) viewModel.runOnlineSearch()
                            }),
                            colors = TextFieldDefaults.colors(
                                focusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                                unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                                focusedIndicatorColor = Color.Transparent,
                                unfocusedIndicatorColor = Color.Transparent,
                            ),
                        )
                    },
                    navigationIcon = {
                        IconButton(onClick = closeSearch) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Volver a la biblioteca")
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = MaterialTheme.colorScheme.background
                    ),
                )
            } else if (embedded) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp).height(56.dp)
                    .clip(RoundedCornerShape(4.dp))
                    .border(1.dp, MaterialTheme.colorScheme.outline, RoundedCornerShape(4.dp))
                    .clickable { searchOpen = true }.padding(horizontal = 16.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Default.Search, contentDescription = null)
                    Spacer(Modifier.width(16.dp))
                    Text("Buscar en tus canciones…", color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodyLarge)
                }
            } else {
                TopAppBar(
                    title = {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(
                                painter = painterResource(id = R.drawable.ic_armonia),
                                contentDescription = null,
                                modifier = Modifier.size(40.dp),
                                tint = Color.Unspecified
                            )
                            Spacer(Modifier.width(6.dp))
                            Text(
                                if (isFavorites) "Favoritos" else if (startWithSearch) "Buscar" else "Canciones",
                                color = Color.White,
                                style = MaterialTheme.typography.headlineMedium,
                            )
                        }
                    },
                    actions = {
                        IconButton(onClick = { searchOpen = true }) {
                            Icon(Icons.Default.Search, contentDescription = "Buscar")
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = MaterialTheme.colorScheme.background
                    )
                )
            }
        }
    ) { padding ->
        val pullState = rememberPullToRefreshState()

        PullToRefreshBox(
            isRefreshing = viewModel.isLoading,
            onRefresh = { viewModel.loadAll() },
            state = pullState,
            modifier = Modifier.padding(padding).fillMaxSize(),
        ) {
            if (viewModel.isLoading && items.isEmpty() && !searching) {
                CircularProgressIndicator(modifier = Modifier.align(Alignment.Center))
            } else {
                // Always host content in a LazyColumn so pull-to-refresh works even
                // when the list (e.g. empty Favorites) has nothing to scroll.
                val state = androidx.compose.foundation.lazy.rememberLazyListState()
                LazyColumn(state = state, modifier = Modifier.fillMaxSize()) {
                    if (viewModel.error != null && items.isEmpty() && !searching) {
                        item {
                            CenteredMessage(viewModel.error!!, MaterialTheme.colorScheme.error)
                            // Most likely no connection to the server — the music kept on
                            // the phone still plays.
                            Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                                OutlinedButton(onClick = onOpenOffline) { Text("Abrir música sin conexión") }
                            }
                        }
                    } else if (!searching && items.isEmpty()) {
                        item {
                            CenteredMessage(
                                text = if (isFavorites) "Todavía no tienes favoritos" else "La biblioteca está vacía",
                                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                            )
                        }
                    } else if (!searching) {
                        // ── Saved searches, shown while the search box is open and empty ──
                        if ((inSearch || startWithSearch) && onlineEnabled && viewModel.searchHistory.isNotEmpty()) {
                            item {
                                RecentSearches(
                                    history = viewModel.searchHistory,
                                    onSearch = { keyboard?.hide(); viewModel.searchFromHistory(it) },
                                    onRemove = { viewModel.removeFromHistory(it) },
                                    onClear = { viewModel.clearHistory() },
                                )
                            }
                        }
                        // ── Normal library browse ──────────────────────────
                        item {
                            if (startWithSearch) SectionHeader("Añadidas recientemente") else BrowseControls(
                                sortKey = viewModel.sortKey,
                                onOpenSort = { sortSheetOpen = true },
                                canPlay = items.isNotEmpty(),
                                onPlayAll = { viewModel.playFromList(items, viewModel.musicPlayer.collectionStart(items)) },
                                player = viewModel.musicPlayer,
                            )
                        }
                        librarySongs(items, viewModel, isFavorites, playingSong?.id, isPlaying, onSongClick,
                            onDelete = { deleteTarget = it }, onAddToPlaylist = { playlistTarget = it },
                            offlineAction = { offlineSongs.actionFor(it, offlineStates) })
                    } else {
                        // ── Search mode: filters, then the library, then outside it ──
                        val showSongs = filter != "artistas"
                        val showArtists = filter != "canciones"
                        if (onlineEnabled) item {
                            Row(
                                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                            ) {
                                listOf("todo" to "Todo", "canciones" to "Canciones", "artistas" to "Artistas").forEach { (key, label) ->
                                    FilterChip(selected = filter == key, onClick = { filter = key }, label = { Text(label) })
                                }
                            }
                        }
                        if (items.isNotEmpty() && showSongs) {
                            val shownLocal = if (filter == "todo") items.take(5) else items
                            item { SectionHeader("Canciones en tu biblioteca") }
                            librarySongs(shownLocal, viewModel, isFavorites, playingSong?.id, isPlaying, onSongClick,
                                onDelete = { deleteTarget = it }, onAddToPlaylist = { playlistTarget = it },
                                offlineAction = { offlineSongs.actionFor(it, offlineStates) })
                            if (shownLocal.size < items.size) item {
                                TextButton(onClick = { filter = "canciones" }, modifier = Modifier.padding(horizontal = 8.dp)) {
                                    Text("Ver las ${items.size} canciones")
                                }
                            }
                        }

                        if (onlineEnabled) {
                            val sourceLabel = if (viewModel.searchSource == "youtube_music") "YouTube Music" else "YouTube"
                            when {
                                !viewModel.onlineSearched -> item {
                                    OnlineHint(
                                        query = viewModel.filterQuery.trim(),
                                        sourceLabel = sourceLabel,
                                        onClick = { keyboard?.hide(); viewModel.runOnlineSearch() },
                                    )
                                }
                                viewModel.onlineLoading -> {
                                    item { SectionHeader("Fuera de tu biblioteca · $sourceLabel") }
                                    item {
                                        Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) {
                                            CircularProgressIndicator()
                                        }
                                    }
                                }
                                viewModel.onlineError != null -> {
                                    item { SectionHeader("Fuera de tu biblioteca · $sourceLabel") }
                                    item {
                                        Column(Modifier.fillMaxWidth().padding(16.dp)) {
                                            Text(
                                                "No se pudo buscar fuera de tu biblioteca. Tus canciones siguen disponibles.",
                                                color = MaterialTheme.colorScheme.error,
                                            )
                                            OutlinedButton(onClick = { viewModel.runOnlineSearch(remember = false) },
                                                modifier = Modifier.padding(top = 8.dp)) { Text("Reintentar") }
                                        }
                                    }
                                }
                                else -> {
                                    val artists = if (showArtists) viewModel.onlineArtists else emptyList()
                                    val songs = when {
                                        !showSongs -> emptyList()
                                        filter == "todo" -> viewModel.onlineSongs.take(8)
                                        else -> viewModel.onlineSongs
                                    }
                                    if (artists.isNotEmpty()) {
                                        item { SectionHeader("Artistas") }
                                        item { ArtistShelf(artists, onArtistClick) }
                                    }
                                    if (songs.isNotEmpty()) item { SectionHeader("Fuera de tu biblioteca · $sourceLabel") }
                                    items(songs, key = { it.videoId }) { result ->
                                        OnlineSongRow(
                                            result = result,
                                            state = viewModel.downloadStates[result.videoId],
                                            onPlay = { viewModel.playPreview(result) },
                                            onNext = { viewModel.playNext(result) },
                                            onQueue = { viewModel.addToQueue(result) },
                                            onDownload = { dlTarget = result },
                                        )
                                    }
                                    if (songs.size < viewModel.onlineSongs.size && showSongs) item {
                                        TextButton(onClick = { filter = "canciones" }, modifier = Modifier.padding(horizontal = 8.dp)) {
                                            Text("Ver más canciones")
                                        }
                                    }
                                    val nothingLocal = items.isEmpty() || !showSongs
                                    if (songs.isEmpty() && artists.isEmpty() && nothingLocal) {
                                        item {
                                            CenteredMessage(
                                                text = when (filter) {
                                                    "artistas" -> "No hay artistas para «${viewModel.filterQuery.trim()}»"
                                                    else -> "No hay resultados para «${viewModel.filterQuery.trim()}»"
                                                },
                                                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                                            )
                                        }
                                    }
                                }
                            }
                        } else if (items.isEmpty()) {
                            item {
                                CenteredMessage(
                                    text = "No hay resultados para «${viewModel.filterQuery.trim()}»",
                                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                                )
                            }
                        }
                    }
                }
                if (!startWithSearch && !searching) {
                    val labels = remember(items, viewModel.sortKey) { items.map { song ->
                        when (viewModel.sortKey) {
                            SortKey.ADDED_DESC -> com.armonia.app.ui.components.scrollMonth(song.created)
                            SortKey.ARTIST_ASC, SortKey.ARTIST_DESC -> scrollInitial(song.artist)
                            SortKey.TITLE_ASC, SortKey.TITLE_DESC -> scrollInitial(song.title)
                            else -> "${song.duration / 60} min"
                        }
                    } }
                    val headers = if (inSearch && onlineEnabled && viewModel.searchHistory.isNotEmpty()) 2 else 1
                    FastScroll(labels, { state.firstVisibleItemIndex }, state.isScrollInProgress, headers) { state.scrollToItem(it) }
                }
            }
        }
    }

    // Search outside the library on its own once typing pauses, as the web does; a partial
    // query found this way is not saved to the recent searches.
    LaunchedEffect(viewModel.filterQuery, onlineEnabled) {
        val typed = viewModel.filterQuery.trim()
        if (onlineEnabled && typed.length >= 3 && !viewModel.onlineSearched) {
            delay(700)
            viewModel.runOnlineSearch(remember = false)
        }
    }

    LaunchedEffect(searchOpen) {
        if (searchOpen) focusRequester.requestFocus()
    }

    if (sortSheetOpen) {
        SortBottomSheet(
            sortKey = viewModel.sortKey,
            onSelect = { viewModel.sortKey = it; sortSheetOpen = false },
            onDismiss = { sortSheetOpen = false },
        )
    }

    playlistTarget?.let { song ->
        AddToPlaylistSheet(song = song, onDismiss = { playlistTarget = null })
    }

    dlTarget?.let { result ->
        val initialAlbum = if (viewModel.searchSource == "youtube_music") result.album.orEmpty() else ""
        YtDownloadDialog(
            initialArtist = result.channel,
            initialTitle = result.title,
            initialAlbum = initialAlbum,
            onConfirm = { artist, title, album ->
                viewModel.downloadOnline(result, artist, title, album)
                dlTarget = null
            },
            onDismiss = { dlTarget = null },
        )
    }

    viewModel.duplicateWarning?.let { w ->
        AlertDialog(
            onDismissRequest = { viewModel.dismissDuplicateWarning() },
            title = { Text("Ya está en la biblioteca") },
            text = { Text("«${w.title}» de ${w.artist} puede que ya esté en tu biblioteca. ¿Descargarla igualmente?") },
            confirmButton = {
                TextButton(onClick = { viewModel.forceDownloadOnline() }) { Text("Descargar igualmente") }
            },
            dismissButton = {
                TextButton(onClick = { viewModel.dismissDuplicateWarning() }) { Text("Cancelar") }
            },
        )
    }

    val target = deleteTarget
    if (target != null) {
        AlertDialog(
            onDismissRequest = { deleteTarget = null },
            title = { Text("¿Eliminar de la biblioteca?") },
            text = {
                Text("«${target.title}» se eliminará definitivamente. No se puede deshacer.")
            },
            confirmButton = {
                TextButton(onClick = {
                    val toDelete = target
                    deleteTarget = null
                    viewModel.deleteSong(toDelete)
                }) {
                    Text("Eliminar", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { deleteTarget = null }) { Text("Cancelar") }
            },
        )
    }
}

/** Recent YouTube / YouTube Music searches: tap to re-run, X to forget one. */
@Composable
private fun RecentSearches(
    history: List<String>,
    onSearch: (String) -> Unit,
    onRemove: (String) -> Unit,
    onClear: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(start = 16.dp, end = 4.dp, top = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "Búsquedas recientes",
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
                modifier = Modifier.weight(1f),
            )
            TextButton(onClick = onClear) { Text("Borrar") }
        }
        history.forEach { q ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { onSearch(q) }
                    .padding(start = 16.dp, end = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    Icons.Default.History,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f),
                    modifier = Modifier.size(20.dp),
                )
                Spacer(Modifier.width(12.dp))
                Text(
                    q,
                    style = MaterialTheme.typography.bodyLarge,
                    maxLines = 1,
                    overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f).padding(vertical = 12.dp),
                )
                IconButton(onClick = { onRemove(q) }) {
                    Icon(
                        Icons.Default.Close,
                        contentDescription = "Quitar «$q» de las búsquedas recientes",
                        tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f),
                    )
                }
            }
        }
        HorizontalDivider(modifier = Modifier.padding(top = 4.dp))
    }
}

/** Emits the local song rows shared by browse and search modes. */
private fun androidx.compose.foundation.lazy.LazyListScope.librarySongs(
    items: List<Song>,
    viewModel: LibraryViewModel,
    isFavorites: Boolean,
    currentSongId: String?,
    isPlaying: Boolean,
    onSongClick: (Song) -> Unit,
    onDelete: (Song) -> Unit,
    onAddToPlaylist: (Song) -> Unit,
    offlineAction: (Song) -> com.armonia.app.ui.components.OfflineSongAction,
) {
    itemsIndexed(items, key = { _, song -> song.id }) { index, song ->
        val isStarred = viewModel.isStarred(song, defaultStarred = isFavorites)
        val isCurrent = song.id == currentSongId
        SongRow(
            song = song,
            isStarred = isStarred,
            getCoverUrl = { viewModel.getCoverArtUrl(it) },
            onClick = {
                viewModel.playFromList(items, index)
                onSongClick(song)
            },
            onToggleStar = { viewModel.toggleStar(song, defaultStarred = isFavorites) },
            onAddToQueue = { viewModel.addToQueue(song) },
            onPlay = {
                viewModel.playFromList(items, index)
                onSongClick(song)
            },
            onDelete = { onDelete(song) },
            onAddToPlaylist = { onAddToPlaylist(song) },
            isCurrent = isCurrent,
            isPlayingNow = isCurrent && isPlaying,
            offline = offlineAction(song),
        )
    }
}

/** Full-viewport centered message; used inside the LazyColumn so it stays pull-to-refreshable. */
@Composable
private fun androidx.compose.foundation.lazy.LazyItemScope.CenteredMessage(text: String, color: Color) {
    Box(
        modifier = Modifier.fillParentMaxSize().padding(24.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(text = text, color = color, textAlign = TextAlign.Center)
    }
}

@Composable
private fun SectionHeader(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.titleSmall,
        fontWeight = FontWeight.SemiBold,
        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.65f),
        modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 6.dp),
    )
}

@Composable
private fun OnlineHint(query: String, sourceLabel: String, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Default.Search, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
        Spacer(Modifier.width(12.dp))
        Text(
            text = "Buscar «$query» en $sourceLabel",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.primary,
        )
    }
}

@Composable
private fun ArtistShelf(artists: List<ArtistResult>, onArtistClick: (String) -> Unit) {
    LazyRow(
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        items(artists, key = { it.channelId }) { artist ->
            ArtistCard(artist = artist, onClick = { onArtistClick(artist.channelId) })
        }
    }
}

@Composable
private fun ArtistCard(artist: ArtistResult, onClick: () -> Unit) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .width(88.dp)
            .clip(RoundedCornerShape(12.dp))
            .clickable(onClick = onClick)
            .padding(vertical = 4.dp),
    ) {
        if (artist.thumbnail != null) {
            AsyncImage(
                model = artist.thumbnail,
                contentDescription = null,
                modifier = Modifier
                    .size(80.dp)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.surfaceContainerHighest),
                contentScale = ContentScale.Crop,
            )
        } else {
            Box(
                modifier = Modifier
                    .size(80.dp)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.surfaceContainerHighest),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Default.Search, null, tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.4f))
            }
        }
        Spacer(Modifier.height(6.dp))
        Text(
            text = artist.name,
            style = MaterialTheme.typography.bodySmall,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            textAlign = TextAlign.Center,
        )
    }
}

@Composable
private fun OnlineSongRow(
    result: SearchResult,
    onNext: () -> Unit,
    onQueue: () -> Unit,
    state: com.armonia.app.ui.ytmusic.YtDownloadState?,
    onPlay: () -> Unit,
    onDownload: () -> Unit,
) {
    var queued by remember(result.videoId) { mutableStateOf(false) }
    val enqueue = { onNext(); queued = true }
    com.armonia.app.ui.components.SwipeToQueue(onQueue = { onQueue(); queued = true }) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onPlay)
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(contentAlignment = Alignment.Center) {
            AsyncImage(
                model = result.thumbnail,
                contentDescription = null,
                modifier = Modifier
                    .size(48.dp)
                    .clip(RoundedCornerShape(6.dp))
                    .background(MaterialTheme.colorScheme.surfaceContainerHighest),
                contentScale = ContentScale.Crop,
            )
            Icon(
                Icons.Default.PlayArrow,
                contentDescription = "Vista previa",
                tint = Color.White,
                modifier = Modifier
                    .size(24.dp)
                    .background(Color.Black.copy(alpha = 0.35f), CircleShape),
            )
        }
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            MarqueeText(result.title, style = MaterialTheme.typography.bodyMedium)
            MarqueeText(
                result.channel,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.55f),
            )
        }
        TextButton(onClick=enqueue){Text(if(queued) "En cola" else "Siguiente")}
        DownloadButton(state, onDownload)
    }
    }
}

/**
 * One row above the songs: the order on the left; shuffle and a round Play on the right, the
 * same shapes as in a playlist or an album instead of two wide buttons.
 */
@Composable
private fun BrowseControls(
    sortKey: SortKey,
    onOpenSort: () -> Unit,
    canPlay: Boolean,
    onPlayAll: () -> Unit,
    player: com.armonia.app.playback.MusicPlayer,
) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(start = 4.dp, end = 16.dp, top = 4.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        TextButton(onClick = onOpenSort) {
            Text(
                text = "Orden: ${sortLabel(sortKey)}",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
            )
            Spacer(Modifier.width(4.dp))
            Icon(
                imageVector = Icons.Default.UnfoldMore,
                contentDescription = null,
                modifier = Modifier.size(16.dp),
                tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
            )
        }
        Spacer(Modifier.weight(1f))
        if (canPlay) {
            com.armonia.app.ui.components.PlayAndShuffle(
                enabled = true, onPlay = onPlayAll, player = player, playLabel = "Reproducir todo")
        }
    }
}

private val SORT_OPTIONS = listOf(
    SortKey.ADDED_DESC    to "Añadidas recientemente",
    SortKey.ARTIST_ASC    to "Artista A → Z",
    SortKey.ARTIST_DESC   to "Artista Z → A",
    SortKey.TITLE_ASC     to "Título A → Z",
    SortKey.TITLE_DESC    to "Título Z → A",
    SortKey.DURATION_ASC  to "Más cortas primero",
    SortKey.DURATION_DESC to "Más largas primero",
)

private fun sortLabel(key: SortKey) = SORT_OPTIONS.first { it.first == key }.second

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SortBottomSheet(
    sortKey: SortKey,
    onSelect: (SortKey) -> Unit,
    onDismiss: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
    ) {
        Text(
            text = "Ordenar por",
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp),
        )
        HorizontalDivider()
        SORT_OPTIONS.forEach { (key, label) ->
            val selected = key == sortKey
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { onSelect(key) }
                    .padding(horizontal = 24.dp, vertical = 16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = label,
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.weight(1f),
                    color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
                )
                if (selected) {
                    Icon(
                        imageVector = Icons.Default.Check,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(20.dp),
                    )
                }
            }
        }
        Spacer(Modifier.height(16.dp))
    }
}
