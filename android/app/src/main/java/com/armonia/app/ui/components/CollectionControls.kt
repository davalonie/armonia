package com.armonia.app.ui.components

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DownloadDone
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material.icons.outlined.DownloadForOffline
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.armonia.app.offline.OfflineProgress

/**
 * The controls of a playlist or an album, the same in both: download to the phone on the left,
 * shuffle and a round Play on the right.
 */
@Composable
fun CollectionControls(
    songs: Int,
    isPinnedOffline: Boolean,
    offlineProgress: OfflineProgress?,
    onToggleOffline: () -> Unit,
    showingPause: Boolean,
    onPlay: () -> Unit,
    player: com.armonia.app.playback.MusicPlayer,
    playLabel: String,
    modifier: Modifier = Modifier,
) {
    val toggleOffline = rememberOfflineToggle(isPinnedOffline, onToggleOffline)
    val downloading = isPinnedOffline && offlineProgress?.running == true
    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(
            onClick = toggleOffline,
            enabled = songs > 0 || isPinnedOffline,
            modifier = Modifier.offset(x = (-12).dp).semantics {
                contentDescription = when {
                    downloading -> "Descargando en el teléfono. Toca para cancelar y quitar la descarga"
                    isPinnedOffline -> "Descargada en este teléfono. Toca para quitar la descarga"
                    else -> "Descargar en este teléfono para escucharla sin conexión"
                }
            },
        ) {
            when {
                downloading -> CircularProgressIndicator(
                    progress = { (offlineProgress?.let { if (it.total > 0) it.done.toFloat() / it.total else 0f } ?: 0f) },
                    modifier = Modifier.size(24.dp), strokeWidth = 2.5.dp,
                )
                isPinnedOffline -> Icon(Icons.Default.DownloadDone, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(28.dp))
                else -> Icon(Icons.Outlined.DownloadForOffline, null, tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.75f), modifier = Modifier.size(28.dp))
            }
        }
        Spacer(Modifier.weight(1f))
        PlayAndShuffle(enabled = songs > 0, showingPause = showingPause, onPlay = onPlay, player = player, playLabel = playLabel)
    }
}

/** Shuffle and a round Play, side by side: the pair every list of songs offers. */
@Composable
fun PlayAndShuffle(
    enabled: Boolean,
    onPlay: () -> Unit,
    player: com.armonia.app.playback.MusicPlayer,
    playLabel: String,
    showingPause: Boolean = false,
) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        GlobalShuffle(player)
        Spacer(Modifier.width(8.dp))
        FilledIconButton(
            onClick = onPlay,
            enabled = enabled,
            modifier = Modifier.size(56.dp),
            colors = IconButtonDefaults.filledIconButtonColors(
                containerColor = MaterialTheme.colorScheme.primary,
                contentColor = Color.Black,
            ),
        ) {
            Icon(
                if (showingPause) Icons.Default.Pause else Icons.Default.PlayArrow,
                contentDescription = if (showingPause) "Pausar" else playLabel,
                modifier = Modifier.size(32.dp),
            )
        }
    }
}

@Composable
fun GlobalShuffle(player: com.armonia.app.playback.MusicPlayer) {
    val active = player.shuffleOn.collectAsState().value
    com.armonia.app.ui.player.ModeButton(Icons.Default.Shuffle, "Aleatorio",
        if (active) "Activado" else "Desactivado", active, player::toggleShuffle)
}
