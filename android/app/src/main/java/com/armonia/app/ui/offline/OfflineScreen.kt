package com.armonia.app.ui.offline

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DownloadDone
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import coil.compose.AsyncImage
import com.armonia.app.data.api.Song
import com.armonia.app.offline.OfflineCollection
import com.armonia.app.offline.OfflineProgress
import com.armonia.app.ui.components.NowPlayingBars

/** Albums and playlists kept on the phone; works without the server. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OfflineScreen(embedded: Boolean = false, viewModel: OfflineViewModel = hiltViewModel()) {
    val persistenceProblem by viewModel.persistenceProblem.collectAsState()
    val selected = viewModel.selected
    BackHandler(enabled = selected != null) { viewModel.select(null) }

    Scaffold(
        contentWindowInsets = WindowInsets(0),
        topBar = {
            if (!embedded || selected != null) TopAppBar(
                title = {
                    Text(
                        selected?.title ?: "Música sin conexión",
                        color = Color.White,
                        style = MaterialTheme.typography.headlineMedium,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                },
                navigationIcon = {
                    if (selected != null) {
                        IconButton(onClick = { viewModel.select(null) }) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Volver")
                        }
                    }
                },
                actions = {
                    if (selected != null) {
                        IconButton(onClick = { viewModel.remove(selected.key) }) {
                            Icon(Icons.Default.Delete, contentDescription = "Quitar de sin conexión")
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
        },
    ) { padding ->
        Column(modifier = Modifier.padding(padding).fillMaxSize()) {
            persistenceProblem?.let { Text(it, Modifier.padding(12.dp), color=MaterialTheme.colorScheme.error) }
            if (selected != null) {
                CollectionDetail(selected, viewModel)
            } else {
                CollectionList(viewModel)
            }
        }
    }
}

@Composable
private fun CollectionList(viewModel: OfflineViewModel) {
    val collections = viewModel.catalog.collections.sortedByDescending { it.pinnedAt }
    val all = remember(viewModel.catalog) { viewModel.catalog.allSongs() }
    if (collections.isEmpty()) {
        Column(
            modifier = Modifier.fillMaxSize().padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Icon(Icons.Default.CloudOff, contentDescription = null, modifier = Modifier.size(48.dp),
                tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.4f))
            Spacer(Modifier.height(12.dp))
            Text("Todavía no has guardado nada sin conexión", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(4.dp))
            Text(
                "Abre un álbum o una playlist y toca el icono de descarga. Sonará aquí sin conexión.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
            )
        }
        return
    }
    LazyColumn(modifier = Modifier.fillMaxSize()) {
        item {
            Row(
                modifier = Modifier.fillMaxWidth().padding(16.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                com.armonia.app.ui.components.PlayAndShuffle(
                    enabled = all.isNotEmpty(), player = viewModel.musicPlayer, playLabel = "Reproducir todo",
                    onPlay = { viewModel.play(all, viewModel.musicPlayer.collectionStart(all)) },
                )
            }
            HorizontalDivider()
        }
        itemsIndexed(collections, key = { _, c -> c.key }) { _, c ->
            CollectionRow(c, viewModel.progress[c.key], viewModel::getCoverUrl) {
                // A song kept on its own just plays; albums and playlists open.
                if (c.isSong) viewModel.play(c.songs, viewModel.musicPlayer.collectionStart(c.songs)) else viewModel.select(c)
            }
        }
    }
}

@Composable
private fun CollectionRow(
    c: OfflineCollection,
    progress: OfflineProgress?,
    getCoverUrl: (String) -> String,
    onClick: () -> Unit,
) {
    val coverUrl = remember(c.coverArt) { c.coverArt?.let(getCoverUrl) }
    Row(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        AsyncImage(
            model = coverUrl,
            contentDescription = null,
            modifier = Modifier.size(56.dp).clip(RoundedCornerShape(6.dp)).background(MaterialTheme.colorScheme.surfaceVariant),
            contentScale = ContentScale.Crop,
        )
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(c.title, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(c.subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f), maxLines = 1, overflow = TextOverflow.Ellipsis)
            val status = when {
                progress?.running == true -> if (c.isSong) "Descargando…" else "Descargando ${progress.done}/${progress.total}"
                (progress?.failed ?: 0) > 0 -> if (c.isSong) "La descarga ha fallado" else "${com.armonia.app.ui.playlists.songCount(c.songs.size)} · ${progress!!.failed} con error"
                c.isSong -> "Canción"
                else -> com.armonia.app.ui.playlists.songCount(c.songs.size)
            }
            Text(status, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f))
        }
        if (progress?.running == true) {
            CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
        } else {
            Icon(Icons.Default.DownloadDone, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
        }
    }
}

@Composable
private fun CollectionDetail(c: OfflineCollection, viewModel: OfflineViewModel) {
    val currentSong by viewModel.musicPlayer.currentSong.collectAsState()
    val isPlaying by viewModel.musicPlayer.isPlaying.collectAsState()
    LazyColumn(modifier = Modifier.fillMaxSize()) {
        item {
            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    com.armonia.app.ui.playlists.songCount(c.songs.size),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
                    modifier = Modifier.weight(1f),
                )
                com.armonia.app.ui.components.PlayAndShuffle(
                    enabled = c.songs.isNotEmpty(),
                    onPlay = { viewModel.play(c.songs, viewModel.musicPlayer.collectionStart(c.songs)) },
                    player = viewModel.musicPlayer,
                    playLabel = "Reproducir todo",
                )
            }
            HorizontalDivider()
        }
        itemsIndexed(c.songs, key = { i, s -> "$i:${s.id}" }) { index, song ->
            OfflineSongRow(
                song = song,
                cached = song.id in viewModel.cachedIds,
                isCurrent = currentSong?.id == song.id,
                isPlayingNow = currentSong?.id == song.id && isPlaying,
                coverUrl = song.coverArt?.let(viewModel::getCoverUrl),
                onClick = { viewModel.play(c.songs, index) },
                onQueue = { viewModel.musicPlayer.addToQueue(song) },
            )
        }
    }
}

@Composable
private fun OfflineSongRow(
    song: Song,
    cached: Boolean,
    isCurrent: Boolean,
    isPlayingNow: Boolean,
    coverUrl: String?,
    onClick: () -> Unit,
    onQueue: () -> Unit,
) = com.armonia.app.ui.components.SwipeToQueue(onQueue = onQueue) {
    Row(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(modifier = Modifier.size(44.dp)) {
            AsyncImage(
                model = coverUrl,
                contentDescription = null,
                modifier = Modifier.fillMaxSize().clip(RoundedCornerShape(4.dp)).background(MaterialTheme.colorScheme.surfaceVariant),
                contentScale = ContentScale.Crop,
            )
            if (isPlayingNow) {
                Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.55f), RoundedCornerShape(4.dp)), contentAlignment = Alignment.Center) {
                    NowPlayingBars(color = MaterialTheme.colorScheme.primary, modifier = Modifier.height(16.dp))
                }
            }
        }
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                song.title,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = if (isCurrent) FontWeight.SemiBold else FontWeight.Normal,
                color = if (isCurrent) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
            Text(song.artist, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f), maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        if (cached) {
            Icon(Icons.Default.DownloadDone, contentDescription = "Disponible sin conexión", tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(18.dp))
        } else {
            Icon(Icons.Default.CloudOff, contentDescription = "Aún sin descargar", tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.35f), modifier = Modifier.size(18.dp))
        }
    }
}
