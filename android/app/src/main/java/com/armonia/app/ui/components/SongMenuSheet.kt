package com.armonia.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.PlaylistAdd
import androidx.compose.material.icons.automirrored.filled.PlaylistPlay
import androidx.compose.material.icons.automirrored.filled.QueueMusic
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.outlined.FavoriteBorder
import androidx.compose.material.icons.outlined.StarBorder
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import coil.compose.AsyncImage
import com.armonia.app.data.api.Song
import com.armonia.app.playback.isPreview
import kotlinx.coroutines.launch

/** Five stars in a row; tapping the current value clears it. */
@Composable
fun RatingStars(rating: Int, enabled: Boolean, modifier: Modifier = Modifier, onRate: (Int) -> Unit) {
    Row(modifier, verticalAlignment = Alignment.CenterVertically) {
        for (n in 1..5) IconButton(onClick = { onRate(if (rating == n) 0 else n) }, enabled = enabled, modifier = Modifier.size(40.dp)) {
            Icon(if (n <= rating) Icons.Default.Star else Icons.Outlined.StarBorder,
                contentDescription = if (n == 1) "1 estrella" else "$n estrellas",
                tint = if (n <= rating) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f))
        }
    }
}

/**
 * The one song menu: who the song is, favourite, rating as stars, play next, queue, playlist.
 * Favourite and rating belong to the library, so songs from external sources do not offer them here.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SongMenuSheet(song: Song, coverUrl: String?, onDismiss: () -> Unit, actions: SongActionsViewModel = hiltViewModel(), onDownload: (() -> Unit)? = null) {
    val scope = rememberCoroutineScope()
    var starred by remember(song.id) { mutableStateOf(!song.starred.isNullOrEmpty()) }
    var rating by remember(song.id) { mutableStateOf(song.userRating ?: 0) }
    var busy by remember(song.id) { mutableStateOf(false) }
    var error by remember(song.id) { mutableStateOf<String?>(null) }
    var playlistOpen by remember(song.id) { mutableStateOf(false) }
    if (playlistOpen) { AddToPlaylistSheet(song = song, onDismiss = { playlistOpen = false; onDismiss() }); return }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.fillMaxWidth().padding(bottom = 16.dp)) {
            Row(Modifier.padding(horizontal = 20.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                AsyncImage(model = coverUrl, contentDescription = null, contentScale = ContentScale.Crop,
                    modifier = Modifier.size(56.dp).clip(RoundedCornerShape(6.dp)).background(MaterialTheme.colorScheme.surfaceVariant))
                Column(Modifier.padding(start = 14.dp)) {
                    Text(song.title, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(song.artist, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.65f))
                }
            }
            HorizontalDivider(Modifier.padding(vertical = 8.dp), color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.08f))
            if (!song.isPreview()) {
                Entry(if (starred) Icons.Default.Favorite else Icons.Outlined.FavoriteBorder,
                    if (starred) "Quitar de favoritos" else "Añadir a favoritos", enabled = !busy) {
                    scope.launch {
                        busy = true; error = null
                        actions.favorite(song, !starred).onSuccess { starred = !starred }.onFailure { error = "No se pudo guardar el favorito" }
                        busy = false
                    }
                }
                Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("Valoracion", Modifier.weight(1f))
                    RatingStars(rating, enabled = !busy) { value ->
                        scope.launch {
                            busy = true; error = null
                            actions.rate(song, value).onSuccess { rating = value }.onFailure { error = "No se pudo guardar la valoracion" }
                            busy = false
                        }
                    }
                }
            }
            Entry(Icons.Default.SkipNext, "Reproducir a continuacion") { actions.playNext(song); onDismiss() }
            Entry(Icons.AutoMirrored.Filled.QueueMusic, "Añadir a la cola") { actions.addToQueue(song); onDismiss() }
            Entry(Icons.AutoMirrored.Filled.PlaylistPlay, "Añadir al final de la cola") { actions.addToEnd(song); onDismiss() }
            Entry(Icons.AutoMirrored.Filled.PlaylistAdd, "Añadir a una playlist") { playlistOpen = true }
            onDownload?.let { Entry(Icons.Default.Download, "Descargar a la biblioteca", onClick = it) }
            error?.let { Text(it, Modifier.padding(horizontal = 20.dp, vertical = 8.dp), color = MaterialTheme.colorScheme.error) }
        }
    }
}

@Composable
private fun Entry(icon: ImageVector, label: String, enabled: Boolean = true, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(enabled = enabled, onClick = onClick).padding(horizontal = 20.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, null, tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.8f))
        Text(label, Modifier.padding(start = 16.dp))
    }
}
