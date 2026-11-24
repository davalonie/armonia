package com.armonia.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.PlaylistAdd
import androidx.compose.material.icons.automirrored.filled.PlaylistPlay
import androidx.compose.material.icons.automirrored.filled.QueueMusic
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DownloadDone
import androidx.compose.material.icons.filled.DownloadForOffline
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.HeartBroken
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.outlined.FavoriteBorder
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.util.fastForEach
import coil.compose.AsyncImage
import coil.request.ImageRequest
import androidx.compose.ui.platform.LocalContext
import com.armonia.app.data.api.Song
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import kotlinx.coroutines.launch

/**
 * Reusable song row used across Library, Favorites, Album detail, and Playlist detail.
 *
 * Each screen wires its own callbacks for the actions — typically delegating to a
 * ViewModel that talks to LibraryRepository + MusicPlayer.
 */
@Composable
fun SongRow(
    song: Song,
    isStarred: Boolean,
    getCoverUrl: (String) -> String,
    onClick: () -> Unit,
    onToggleStar: () -> Unit,
    onAddToQueue: () -> Unit,
    onPlay: () -> Unit,
    onDelete: () -> Unit,
    onAddToPlaylist: (() -> Unit)? = null,
    extraMenuItems: List<MenuAction> = emptyList(),
    isCurrent: Boolean = false,
    isPlayingNow: Boolean = false,
    offline: OfflineSongAction? = null,
    showFavorite: Boolean = true,
) {
    val coverUrl = remember(song.coverArt) { song.coverArt?.let { getCoverUrl(it) } }

    var menuOpen by remember { mutableStateOf(false) }
    var ratingOpen by remember(song.id) { mutableStateOf(false) }
    var ratingBusy by remember(song.id) { mutableStateOf(false) }
    var ratingError by remember(song.id) { mutableStateOf<String?>(null) }
    var rating by remember(song.id) { mutableStateOf(song.userRating ?: 0) }
    val actions: SongActionsViewModel = hiltViewModel()
    val scope = rememberCoroutineScope()
    if (ratingOpen) AlertDialog(onDismissRequest = { if (!ratingBusy) ratingOpen = false },
        title = { Text("Valorar ${song.title}") },
        text = { Column {
            Text(if (rating == 0) "Sin valoracion" else "$rating de 5")
            Slider(rating.toFloat(), { rating = it.toInt() }, valueRange = 0f..5f, steps = 4, enabled = !ratingBusy)
            ratingError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        } },
        confirmButton = { TextButton(enabled = !ratingBusy, onClick = { scope.launch {
            ratingBusy = true
            actions.rate(song, rating).onSuccess { ratingOpen = false }.onFailure { ratingError = "No se pudo guardar la valoracion" }
            ratingBusy = false
        } }) { Text("Guardar") } },
        dismissButton = { TextButton(enabled = !ratingBusy, onClick = { ratingOpen = false }) { Text("Cancelar") } })

    // Pull the row to the right to queue the song (see SwipeToQueue).
    SwipeToQueue(onQueue = onAddToQueue) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(72.dp) // Fixed height helps LazyColumn measure items
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(modifier = Modifier.size(52.dp)) {
            AsyncImage(
                model = ImageRequest.Builder(LocalContext.current)
                    .data(coverUrl)
                    .crossfade(true)
                    .build(),
                contentDescription = null,
                modifier = Modifier
                    .fillMaxSize()
                    .clip(RoundedCornerShape(8.dp))
                    .background(MaterialTheme.colorScheme.surfaceContainerHighest),
                contentScale = ContentScale.Crop,
            )
            if (isCurrent) {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .clip(RoundedCornerShape(8.dp))
                        .background(Color.Black.copy(alpha = 0.5f)),
                    contentAlignment = Alignment.Center,
                ) {
                    if (isPlayingNow) {
                        NowPlayingBars(
                            color = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.height(16.dp),
                        )
                    } else {
                        Icon(
                            Icons.Filled.GraphicEq,
                            contentDescription = "Sonando",
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(20.dp),
                        )
                    }
                }
            }
        }
        Spacer(Modifier.width(14.dp))
        Column(modifier = Modifier.weight(1f)) {
            // Still text, cut with an ellipsis: a list where every long title scrolls is hard to
            // read. The whole title and artists head the row's menu.
            Text(
                text = song.title,
                style = MaterialTheme.typography.titleSmall,
                color = if (isCurrent) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(2.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                // Small "on this phone" marker, so it's clear what plays without a connection.
                if (offline != null && offline.state != com.armonia.app.offline.OfflineSongState.NONE) {
                    Icon(
                        Icons.Default.DownloadDone,
                        contentDescription = "En este telefono",
                        tint = if (offline.state == com.armonia.app.offline.OfflineSongState.DOWNLOADING)
                            MaterialTheme.colorScheme.onSurface.copy(alpha = 0.4f)
                        else MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(14.dp),
                    )
                    Spacer(Modifier.width(4.dp))
                }
                Text(
                    text = song.artist,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        if (showFavorite) IconButton(
            onClick = onToggleStar,
            modifier = Modifier.minimumInteractiveComponentSize()
        ) {
            Icon(
                imageVector = if (isStarred) Icons.Default.Favorite else Icons.Outlined.FavoriteBorder,
                contentDescription = if (isStarred) "Quitar de favoritos" else "Añadir a favoritos",
                tint = if (isStarred) MaterialTheme.colorScheme.primary
                       else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.4f),
            )
        }
        Box {
            IconButton(
                onClick = { menuOpen = true },
                modifier = Modifier.minimumInteractiveComponentSize()
            ) {
                Icon(
                    Icons.Default.MoreVert,
                    contentDescription = "Opciones de ${song.title}",
                    tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                )
            }
            DropdownMenu(
                expanded = menuOpen,
                onDismissRequest = { menuOpen = false },
            ) {
                Column(Modifier.widthIn(max = 280.dp).padding(horizontal = 12.dp, vertical = 8.dp)) {
                    Text(song.title, style = MaterialTheme.typography.titleSmall)
                    Text(song.artist, style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.65f))
                }
                HorizontalDivider()
                DropdownMenuItem(text = { Text("Reproducir a continuacion") }, onClick = { menuOpen = false; actions.playNext(song) })
                if (!song.id.contains('|')) RatingStars(rating, enabled = !ratingBusy, modifier = Modifier.padding(horizontal = 8.dp)) { value ->
                    scope.launch {
                        ratingBusy = true
                        actions.rate(song, value).onSuccess { rating = value }
                        ratingBusy = false
                    }
                }
                DropdownMenuItem(
                    text = { Text("Reproducir") },
                    leadingIcon = { Icon(Icons.Default.PlayArrow, null) },
                    onClick = { menuOpen = false; onPlay() },
                )
                DropdownMenuItem(
                    text = { Text("Añadir a la cola") },
                    leadingIcon = { Icon(Icons.AutoMirrored.Filled.QueueMusic, null) },
                    onClick = { menuOpen = false; onAddToQueue() },
                )
                DropdownMenuItem(
                    text = { Text("Añadir al final de la cola") },
                    leadingIcon = { Icon(Icons.AutoMirrored.Filled.PlaylistPlay, null) },
                    onClick = { menuOpen = false; actions.addToEnd(song) },
                )
                if (onAddToPlaylist != null) {
                    DropdownMenuItem(
                        text = { Text("Añadir a una playlist") },
                        leadingIcon = { Icon(Icons.AutoMirrored.Filled.PlaylistAdd, null) },
                        onClick = { menuOpen = false; onAddToPlaylist() },
                    )
                }
                DropdownMenuItem(
                    text = { Text(if (isStarred) "Quitar de favoritos" else "Añadir a favoritos") },
                    leadingIcon = {
                        Icon(
                            if (isStarred) Icons.Default.HeartBroken else Icons.Default.Favorite,
                            null,
                        )
                    },
                    onClick = { menuOpen = false; onToggleStar() },
                )
                if (offline != null) {
                    val (label, enabled) = when (offline.state) {
                        com.armonia.app.offline.OfflineSongState.NONE -> "Descargar en el telefono" to true
                        com.armonia.app.offline.OfflineSongState.DOWNLOADING -> "Descargando… (toca para cancelar)" to true
                        com.armonia.app.offline.OfflineSongState.DOWNLOADED -> "Quitar del telefono" to true
                        com.armonia.app.offline.OfflineSongState.IN_COLLECTION -> "En el telefono (album o playlist guardados)" to false
                    }
                    DropdownMenuItem(
                        text = { Text(label) },
                        leadingIcon = {
                            Icon(
                                if (offline.state == com.armonia.app.offline.OfflineSongState.NONE) Icons.Default.DownloadForOffline
                                else Icons.Default.DownloadDone,
                                null,
                            )
                        },
                        enabled = enabled,
                        onClick = { menuOpen = false; offline.onToggle() },
                    )
                }
                extraMenuItems.fastForEach { extra ->
                    DropdownMenuItem(
                        text = { Text(extra.label) },
                        leadingIcon = extra.icon?.let { { Icon(it, null) } },
                        onClick = { menuOpen = false; extra.onClick() },
                    )
                }
                HorizontalDivider()
                DropdownMenuItem(
                    text = {
                        Text(
                            "Eliminar archivo de la biblioteca",
                            color = MaterialTheme.colorScheme.error,
                        )
                    },
                    leadingIcon = {
                        Icon(
                            Icons.Default.Delete,
                            null,
                            tint = MaterialTheme.colorScheme.error,
                        )
                    },
                    onClick = { menuOpen = false; onDelete() },
                )
            }
        }
    }
    }
}

/** "Descargar en el telefono" / "Quitar del telefono" for a song row. */
data class OfflineSongAction(
    val state: com.armonia.app.offline.OfflineSongState,
    val onToggle: () -> Unit,
)

data class MenuAction(
    val label: String,
    val icon: androidx.compose.ui.graphics.vector.ImageVector? = null,
    val onClick: () -> Unit,
)
