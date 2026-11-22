package com.armonia.app.ui.playlists

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AddCircleOutline
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import coil.compose.AsyncImage
import com.armonia.app.data.api.Song
import com.armonia.app.playback.PlaybackProgress
import com.armonia.app.ui.components.matchesSearch

/**
 * Pick songs for one playlist: search, listen to ten seconds by tapping the cover, add with +.
 * Each + is saved on its own and the screen stays open to keep adding.
 *
 * Only songs of the library are offered: a Navidrome playlist cannot hold a song from outside
 * it, and nothing is downloaded here to make + look like it worked.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddSongsScreen(onBack: () -> Unit, viewModel: PlaylistDetailViewModel) {
    var query by rememberSaveable { mutableStateOf("") }
    val states by viewModel.addStates.collectAsState()
    val previewing by viewModel.auditionId.collectAsState()
    val progress = viewModel.progress.collectAsState()
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(Unit) { viewModel.loadLibrarySongs() }
    DisposableEffect(Unit) { onDispose { viewModel.stopPreview() } }
    LaunchedEffect(viewModel.notice) {
        viewModel.notice?.let { snackbar.showSnackbar(it); viewModel.notice = null }
    }
    LaunchedEffect(viewModel.lastAdded) {
        val song = viewModel.lastAdded ?: return@LaunchedEffect
        val result = snackbar.showSnackbar("«${song.title}» añadida", actionLabel = "Deshacer", duration = SnackbarDuration.Short)
        if (result == SnackbarResult.ActionPerformed) viewModel.undoAdd(song)
        else if (viewModel.lastAdded?.id == song.id) viewModel.lastAdded = null
    }
    val songs = viewModel.allLibrarySongs
    val shown = remember(songs, query) {
        val q = query.trim()
        if (q.isEmpty()) songs
        else songs.filter { matchesSearch(q, it.title, it.artist, it.album) }
    }

    Scaffold(
        contentWindowInsets = WindowInsets(0),
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("Añadir canciones", style = MaterialTheme.typography.titleMedium)
                        Text(
                            "a «${viewModel.playlist?.name.orEmpty()}»",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.primary,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Volver a la playlist") } },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
        },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize().imePadding()) {
            TextField(
                value = query,
                onValueChange = { query = it },
                placeholder = { Text("Buscar canción o artista", maxLines = 1) },
                leadingIcon = { Icon(Icons.Default.Search, null) },
                trailingIcon = { if (query.isNotEmpty()) IconButton(onClick = { query = "" }) { Icon(Icons.Default.Close, "Borrar la búsqueda") } },
                singleLine = true,
                shape = RoundedCornerShape(28.dp),
                colors = TextFieldDefaults.colors(
                    focusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                    unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                    focusedIndicatorColor = Color.Transparent,
                    unfocusedIndicatorColor = Color.Transparent,
                ),
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
            )
            Text(
                "Canciones de tu biblioteca. Toca una portada para escuchar 10 segundos; + la añade.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
            )
            when {
                viewModel.pickerLoading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                viewModel.pickerError != null -> Column(Modifier.fillMaxWidth().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(viewModel.pickerError!!, color = MaterialTheme.colorScheme.error)
                    OutlinedButton(onClick = { viewModel.loadLibrarySongs() }, modifier = Modifier.padding(top = 8.dp)) { Text("Reintentar") }
                }
                shown.isEmpty() -> Text(
                    if (songs.isEmpty()) "Tu biblioteca todavía no tiene canciones."
                    else "No hay canciones en tu biblioteca para «${query.trim()}». Las de fuera se añaden desde Buscar, descargándolas antes.",
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                    modifier = Modifier.padding(24.dp),
                )
                else -> LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 16.dp)) {
                    items(shown, key = { it.id }) { song ->
                        // Read here so `states` changing recomposes the rows.
                        val state = states[song.id] ?: viewModel.stateOf(song)
                        AddSongRow(
                            song = song,
                            coverUrl = song.coverArt?.let { viewModel.getCoverUrl(it) },
                            state = state,
                            previewing = previewing == song.id,
                            progress = { progress.value },
                            onPreview = { viewModel.togglePreview(song) },
                            onAdd = { viewModel.addSong(song) },
                            onUndo = { viewModel.undoAdd(song) },
                        )
                    }
                }
            }
        }
    }
}

/** Cover (tap: ten-second preview), title and artists, and the + button with its state. */
@Composable
fun AddSongRow(
    song: Song,
    coverUrl: String?,
    state: AddState,
    previewing: Boolean,
    progress: () -> PlaybackProgress,
    onPreview: () -> Unit,
    onAdd: () -> Unit,
    onUndo: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth().height(72.dp).padding(start = 16.dp, end = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(52.dp)
                .clip(RoundedCornerShape(8.dp))
                .background(MaterialTheme.colorScheme.surfaceContainerHighest)
                .clickable(role = Role.Button, onClick = onPreview)
                .semantics {
                    contentDescription = if (previewing) "Parar la preescucha de ${song.title}" else "Escuchar 10 segundos de ${song.title}"
                }
                .testTag("preview-${song.id}"),
            contentAlignment = Alignment.Center,
        ) {
            AsyncImage(model = coverUrl, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            if (previewing) {
                Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.55f)))
                val now = progress()
                CircularProgressIndicator(
                    progress = { if (now.durationMs > 0) (now.positionMs.toFloat() / now.durationMs).coerceIn(0f, 1f) else 0f },
                    modifier = Modifier.size(36.dp),
                    color = MaterialTheme.colorScheme.primary,
                    trackColor = Color.White.copy(alpha = 0.25f),
                    strokeWidth = 3.dp,
                )
                Icon(Icons.Default.Stop, null, tint = Color.White, modifier = Modifier.size(18.dp))
            } else {
                Icon(
                    Icons.Default.PlayArrow, null, tint = Color.White,
                    modifier = Modifier.size(22.dp).background(Color.Black.copy(alpha = 0.45f), CircleShape),
                )
            }
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(song.title, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
            // The album tells a studio take from its live version when title and artist are the same.
            val credits = listOfNotNull(song.artist, song.album?.takeIf { it.isNotBlank() }).joinToString(" · ")
            Text(
                text = when (state) {
                    AddState.ALREADY -> "Ya está en la playlist · $credits"
                    AddState.ADDED -> "Añadida · $credits"
                    AddState.FAILED -> "No se pudo añadir · $credits"
                    else -> credits
                },
                style = MaterialTheme.typography.bodySmall,
                color = when (state) {
                    AddState.FAILED -> MaterialTheme.colorScheme.error
                    AddState.ADDED -> MaterialTheme.colorScheme.primary
                    else -> MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
                },
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(top = 2.dp),
            )
        }
        when (state) {
            AddState.SENDING -> Box(Modifier.size(48.dp), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(Modifier.size(22.dp).semantics { contentDescription = "Guardando ${song.title}" }, strokeWidth = 2.5.dp)
            }
            AddState.ADDED -> IconButton(onClick = onUndo, modifier = Modifier.testTag("undo-${song.id}")) {
                Icon(Icons.Default.CheckCircle, "Añadida. Toca para quitar ${song.title} de la playlist", tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(28.dp))
            }
            AddState.ALREADY -> Box(Modifier.size(48.dp), contentAlignment = Alignment.Center) {
                Icon(Icons.Default.CheckCircle, "${song.title} ya está en la playlist", tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.35f), modifier = Modifier.size(28.dp))
            }
            AddState.FAILED -> IconButton(onClick = onAdd, modifier = Modifier.testTag("add-${song.id}")) {
                Icon(Icons.Default.Refresh, "Reintentar añadir ${song.title}", tint = MaterialTheme.colorScheme.error, modifier = Modifier.size(28.dp))
            }
            AddState.NONE -> IconButton(onClick = onAdd, modifier = Modifier.testTag("add-${song.id}")) {
                Icon(Icons.Default.AddCircleOutline, "Añadir ${song.title} a la playlist", tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(28.dp))
            }
        }
    }
}
