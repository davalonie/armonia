package com.armonia.app.ui.player

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.outlined.AddCircleOutline
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.armonia.app.ui.components.MarqueeText
import com.armonia.app.ui.components.canSaveInPlaylists

@Composable
fun MiniPlayer(
    onExpand: () -> Unit,
    viewModel: MiniPlayerViewModel = hiltViewModel(),
) {
    val player = viewModel.musicPlayer
    val song by player.currentSong.collectAsState()
    val isPlaying by player.isPlaying.collectAsState()
    val progress by player.progress.collectAsState()

    // A ten-second preview is not the queue: showing it here, with previous/next, made it look
    // as if the preview had replaced what was playing. The bar comes back when the preview ends.
    val previewing by player.auditionId.collectAsState()
    if (previewing != null) return
    val current = song ?: return

    var sheet by remember(current.id) { mutableStateOf(false) }
    if (sheet) com.armonia.app.ui.components.AddToPlaylistSheet(current, { sheet = false })
    val coverUrl = remember(current.coverArt) { current.coverArt?.let { viewModel.getCoverUrl(it, 128) } }

    val frac = if (progress.durationMs > 0)
        (progress.positionMs.toFloat() / progress.durationMs).coerceIn(0f, 1f)
    else 0f

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surfaceContainerHigh),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .trackSwipe(player, current.id)
                .clickable(onClick = onExpand)
                .padding(start = 12.dp, end = 4.dp, top = 8.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            AsyncImage(
                model = ImageRequest.Builder(LocalContext.current)
                    .data(coverUrl)
                    .crossfade(true)
                    .build(),
                contentDescription = null,
                modifier = Modifier
                    .size(44.dp)
                    .clip(RoundedCornerShape(8.dp))
                    .background(MaterialTheme.colorScheme.surfaceContainerHighest),
                contentScale = ContentScale.Crop,
            )
            Spacer(Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                MarqueeText(
                    text = current.title,
                    style = MaterialTheme.typography.titleSmall,
                )
                MarqueeText(
                    text = current.artist,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.55f),
                )
            }
            // Also for a song not in the library yet: the sheet downloads it before saving it.
            if (current.canSaveInPlaylists()) SavedButton(savedState(current), { sheet = true })
            IconButton(onClick = { player.togglePlayPause() }) {
                Icon(
                    imageVector = if (isPlaying) Icons.Default.Pause else Icons.Default.PlayArrow,
                    contentDescription = if (isPlaying) "Pausar" else "Reproducir",
                    tint = MaterialTheme.colorScheme.primary,
                )
            }
        }
        // No gap and no end dot: Material's defaults drew a stray dot at the right end of the line.
        LinearProgressIndicator(progress = { frac }, modifier = Modifier.fillMaxWidth().height(2.dp),
            color = MaterialTheme.colorScheme.primary, trackColor = MaterialTheme.colorScheme.surfaceContainerHighest,
            gapSize = 0.dp, drawStopIndicator = {})
    }
}

@Composable
internal fun savedState(song: com.armonia.app.data.api.Song,
                       vm: com.armonia.app.ui.components.AddToPlaylistViewModel = hiltViewModel()): Boolean? {
    val revision by vm.revision.collectAsState()
    return key(song.id, revision) {
        produceState<Boolean?>(null) { value = runCatching { vm.saved(song.id) }.getOrNull() }.value
    }
}

@Composable
internal fun SavedButton(saved: Boolean?, open: () -> Unit) {
    IconButton(onClick = open) {
        Icon(if (saved == true) Icons.Default.CheckCircle else Icons.Outlined.AddCircleOutline,
            contentDescription = "Guardar en playlists",
            tint = if (saved == true) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface)
    }
}
