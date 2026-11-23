package com.armonia.app.ui.player

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.PlaylistAdd
import androidx.compose.material.icons.automirrored.filled.QueueMusic
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.outlined.FavoriteBorder
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import com.armonia.app.ui.components.AddToPlaylistSheet
import com.armonia.app.ui.components.MarqueeText
import com.armonia.app.ui.components.canSaveInPlaylists
import com.armonia.app.ui.components.YtDownloadDialog
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import coil.compose.AsyncImage
import coil.imageLoader
import com.armonia.app.playback.RepeatMode
import com.armonia.app.playback.isPreview

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExpandedPlayerScreen(
    onClose: () -> Unit,
    onViewArtist: (artistId: String) -> Unit = {},
    viewModel: ExpandedPlayerViewModel = hiltViewModel(),
) {
    val player = viewModel.musicPlayer
    val song by player.currentSong.collectAsState()
    val isPlaying by player.isPlaying.collectAsState()
    val buffering by player.buffering.collectAsState()
    val shuffleOn by player.shuffleOn.collectAsState()
    val repeatMode by player.repeatMode.collectAsState()
    // Read only inside the seek bar, so a position tick does not recompose the whole screen.
    val progress = player.progress.collectAsState()
    val autoSongs by player.autoSongs.collectAsState()
    val playingFrom by player.playingFrom.collectAsState()

    // Auto-close if the queue empties (e.g., user deletes the current track).
    LaunchedEffect(song) { if (song == null) onClose() }
    val currentSong = song ?: return
    val isPreview = currentSong.isPreview()
    // A song not in the library yet can be saved too: the sheet downloads it first.
    val canSave = currentSong.canSaveInPlaylists()

    val loader = androidx.compose.ui.platform.LocalContext.current.imageLoader
    // 1024 px on Wi-Fi, 600 px on mobile data unless the big one is already on the phone (CoverSizes).
    val coverUrl = remember(currentSong.coverArt) {
        currentSong.coverArt?.let { art -> com.armonia.app.ui.components.CoverSizes.player({ viewModel.getCoverUrl(art, it) }, loader) }
    }
    // A small copy is enough behind a blur; it is decoded once per song, not per progress tick.
    val backdropUrl = remember(currentSong.coverArt) { currentSong.coverArt?.let { viewModel.getCoverUrl(it, 96) } }

    var menuOpen by remember { mutableStateOf(false) }
    var sleepDialogOpen by remember { mutableStateOf(false) }
    val offlineStates by viewModel.offlineSongStates.collectAsState()
    val sleepTimer by viewModel.musicPlayer.sleepTimer.collectAsState()
    var deleteConfirmOpen by remember { mutableStateOf(false) }
    var queueSheetOpen by remember { mutableStateOf(false) }
    var downloadDialogOpen by remember { mutableStateOf(false) }
    var sheetSong by remember { mutableStateOf<com.armonia.app.data.api.Song?>(null) }

    val actions = remember(player, onClose, currentSong.id) {
        PlayerPaneActions(
            minimize = onClose,
            menu = { menuOpen = true },
            playPause = { player.togglePlayPause() },
            previous = { player.prev() },
            next = { player.next() },
            shuffle = { player.toggleShuffle() },
            repeat = { player.toggleRepeat() },
            like = { player.toggleLike() },
            seek = { player.seekFraction(it) },
            queue = { queueSheetOpen = true },
            addToPlaylist = { sheetSong = currentSong },
        )
    }

    PlayerPane(
        state = PlayerPaneState(
            title = currentSong.title,
            artist = currentSong.artist,
            context = playingFrom,
            automatic = currentSong.id in autoSongs,
            playing = isPlaying,
            buffering = buffering,
            liked = if (canSave) savedState(currentSong) else null,
            shuffle = shuffleOn,
            repeat = repeatMode,
            canAddToPlaylist = canSave,
        ),
        progress = { progress.value },
        actions = actions,
        backdrop = {
            AsyncImage(
                model = backdropUrl,
                contentDescription = null,
                modifier = Modifier.fillMaxSize().blur(40.dp),
                contentScale = ContentScale.Crop,
            )
        },
        menu = {
            DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                DropdownMenuItem(
                    text = { Text("Ver la cola") },
                    leadingIcon = { Icon(Icons.AutoMirrored.Filled.QueueMusic, null) },
                    onClick = { menuOpen = false; queueSheetOpen = true },
                )
                if (canSave) {
                    DropdownMenuItem(
                        text = { Text("Añadir a una playlist") },
                        leadingIcon = { Icon(Icons.AutoMirrored.Filled.PlaylistAdd, null) },
                        onClick = { menuOpen = false; sheetSong = currentSong },
                    )
                }
                if (!isPreview && currentSong.artistId != null) {
                    DropdownMenuItem(
                        text = { Text("Ver artista") },
                        leadingIcon = { Icon(Icons.Default.Person, null) },
                        onClick = { menuOpen = false; onViewArtist(currentSong.artistId) },
                    )
                }
                if (isPreview) {
                    DropdownMenuItem(
                        text = { Text("Descargar a la biblioteca") },
                        leadingIcon = { Icon(Icons.Default.Download, null) },
                        onClick = { menuOpen = false; downloadDialogOpen = true },
                    )
                }
                if (!isPreview) {
                    val onPhone = offlineStates[currentSong.id] ?: com.armonia.app.offline.OfflineSongState.NONE
                    DropdownMenuItem(
                        text = {
                            Text(
                                when (onPhone) {
                                    com.armonia.app.offline.OfflineSongState.NONE -> "Descargar en el telefono"
                                    com.armonia.app.offline.OfflineSongState.DOWNLOADING -> "Descargando en el telefono… (toca para cancelar)"
                                    com.armonia.app.offline.OfflineSongState.DOWNLOADED -> "Quitar del telefono"
                                    com.armonia.app.offline.OfflineSongState.IN_COLLECTION -> "En el telefono (album o playlist guardados)"
                                }
                            )
                        },
                        leadingIcon = {
                            Icon(
                                if (onPhone == com.armonia.app.offline.OfflineSongState.NONE) Icons.Default.DownloadForOffline
                                else Icons.Default.DownloadDone,
                                null,
                            )
                        },
                        enabled = onPhone != com.armonia.app.offline.OfflineSongState.IN_COLLECTION,
                        onClick = { menuOpen = false; viewModel.toggleCurrentOnPhone() },
                    )
                }
                DropdownMenuItem(
                    text = { Text(if (sleepTimer.isActive) "Temporizador de apagado (activo)" else "Temporizador de apagado") },
                    leadingIcon = { Icon(Icons.Default.Bedtime, null) },
                    onClick = { menuOpen = false; sleepDialogOpen = true },
                )
                if (!isPreview) {
                    DropdownMenuItem(
                        text = { Text("Eliminar archivo de la biblioteca") },
                        leadingIcon = { Icon(Icons.Default.Delete, null) },
                        onClick = { menuOpen = false; deleteConfirmOpen = true },
                    )
                }
            }
        },
        cover = { coverModifier ->
            AsyncImage(
                model = coverUrl,
                contentDescription = "Portada de ${currentSong.album ?: currentSong.title}",
                modifier = coverModifier.trackSwipe(player, currentSong.id),
                contentScale = ContentScale.Crop,
            )
        },
    )

    // ── Queue sheet ───────────────────────────────────────────────────────
    if (queueSheetOpen) {
        QueueSheet(onDismiss = { queueSheetOpen = false })
    }

    // ── Add to playlist sheet ─────────────────────────────────────────────
    sheetSong?.let { target ->
        AddToPlaylistSheet(song = target, onDismiss = { sheetSong = null })
    }

    // ── Download dialog (preview tracks only) ─────────────────────────────
    if (downloadDialogOpen) {
        YtDownloadDialog(
            initialArtist = currentSong.artist,
            initialTitle = currentSong.title,
            initialAlbum = currentSong.album.orEmpty(),
            onConfirm = { artist, title, album ->
                viewModel.downloadPreview(artist, title, album)
                downloadDialogOpen = false
            },
            onDismiss = { downloadDialogOpen = false },
        )
    }

    // ── Sleep timer ───────────────────────────────────────────────────────
    if (sleepDialogOpen) {
        val remainingMin = sleepTimer.endsAtMs?.let { ((it - System.currentTimeMillis()) / 60_000L).coerceAtLeast(0) }
        AlertDialog(
            onDismissRequest = { sleepDialogOpen = false },
            title = { Text("Temporizador de apagado") },
            text = {
                Column {
                    when {
                        sleepTimer.atTrackEnd -> Text("La reproduccion se detendra cuando termine esta cancion.")
                        remainingMin != null -> Text("La reproduccion se detendra en unos $remainingMin min.")
                        else -> Text("Detener la reproduccion tras:")
                    }
                    Spacer(Modifier.height(8.dp))
                    listOf(15, 30, 45, 60).forEach { minutes ->
                        TextButton(onClick = {
                            viewModel.musicPlayer.setSleepTimer(minutes)
                            sleepDialogOpen = false
                        }) { Text("$minutes minutos") }
                    }
                    TextButton(onClick = {
                        viewModel.musicPlayer.setSleepAtTrackEnd()
                        sleepDialogOpen = false
                    }) { Text("Al terminar esta cancion") }
                }
            },
            confirmButton = {
                if (sleepTimer.isActive) {
                    TextButton(onClick = {
                        viewModel.musicPlayer.cancelSleepTimer()
                        sleepDialogOpen = false
                    }) { Text("Desactivar", color = MaterialTheme.colorScheme.error) }
                }
            },
            dismissButton = {
                TextButton(onClick = { sleepDialogOpen = false }) { Text("Cancelar") }
            },
        )
    }

    // ── Delete confirmation ───────────────────────────────────────────────
    if (deleteConfirmOpen) {
        AlertDialog(
            onDismissRequest = { deleteConfirmOpen = false },
            title = { Text("¿Eliminar de la biblioteca?") },
            text = { Text("«${currentSong.title}» se borrara del servidor para siempre. No se puede deshacer.") },
            confirmButton = {
                TextButton(onClick = {
                    deleteConfirmOpen = false
                    viewModel.deleteCurrentTrack()
                }) {
                    Text("Eliminar", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { deleteConfirmOpen = false }) { Text("Cancelar") }
            },
        )
    }
}
