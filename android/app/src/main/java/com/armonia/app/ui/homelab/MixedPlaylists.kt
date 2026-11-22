package com.armonia.app.ui.homelab

import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.QueueMusic
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.armonia.app.ui.components.PlayAndShuffle
import com.armonia.app.ui.playlists.songCount

/**
 * Playlists that mix library songs with external ones: the lists as rows, and the open one
 * with the same round Play and shuffle as any other playlist. The less common actions live
 * in a menu instead of a wall of text buttons.
 */
fun LazyListScope.mixedPlaylists(vm: HomelabViewModel, onDelete: () -> Unit) {
    item(key = "mixed-create") { CreateMixedPlaylist(enabled = !vm.busy, onCreate = vm::create) }
    if (vm.lists.isEmpty()) item(key = "mixed-empty") {
        Text(
            "Todavía no tienes ninguna. Crea una y añade la canción que esté sonando.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
        )
    }
    items(vm.lists, key = { "mixed-list-${it.id}" }) { list ->
        val open = vm.selected?.id == list.id
        Row(
            modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
                .background(if (open) MaterialTheme.colorScheme.surfaceContainerHigh else MaterialTheme.colorScheme.surface)
                .clickable(enabled = !vm.busy) { vm.select(list.id) }
                .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.AutoMirrored.Filled.QueueMusic, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(28.dp))
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(list.name, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(songCount(list.itemCount), style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f))
            }
        }
    }
    mixedContents(vm, onDelete)
}

private fun LazyListScope.mixedContents(vm: HomelabViewModel, onDelete: () -> Unit) {
    vm.selected?.let { playlist ->
        item(key = "mixed-open") { OpenMixedPlaylist(vm, onDelete) }
        items(playlist.items.size, key = { "mixed-song-${playlist.items[it].id}" }) { index ->
            val track = playlist.items[index].track
            Row(
                modifier = Modifier.fillMaxWidth().clickable {
                    vm.player.playQueue(playlist.items.map { it.track.toSong() }, index, playlistId = playlist.id, playlistKind = "mixed")
                }.padding(vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("${index + 1}", style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f), modifier = Modifier.width(32.dp))
                Column(Modifier.weight(1f)) {
                    Text(track.title, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(track.artist, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f))
                }
                Menu("Opciones de ${track.title}") { close ->
                    DropdownMenuItem(text = { Text("Subir") }, enabled = index > 0 && !vm.busy, onClick = { close(); vm.move(index, -1) })
                    DropdownMenuItem(text = { Text("Bajar") }, enabled = index < playlist.items.lastIndex && !vm.busy, onClick = { close(); vm.move(index, 1) })
                    DropdownMenuItem(text = { Text("Quitar de la lista") }, enabled = !vm.busy, onClick = { close(); vm.remove(index) })
                }
            }
        }
    }
}

@Composable
private fun CreateMixedPlaylist(enabled: Boolean, onCreate: (String) -> Unit) {
    var name by remember { mutableStateOf("") }
    Row(verticalAlignment = Alignment.CenterVertically) {
        OutlinedTextField(value = name, onValueChange = { name = it }, label = { Text("Nueva playlist") },
            singleLine = true, modifier = Modifier.weight(1f))
        Spacer(Modifier.width(12.dp))
        FilledTonalButton(onClick = { onCreate(name.trim()); name = "" }, enabled = enabled && name.isNotBlank()) { Text("Crear") }
    }
}

@Composable
private fun OpenMixedPlaylist(vm: HomelabViewModel, onDelete: () -> Unit) {
    val playlist = vm.selected ?: return
    var renaming by remember { mutableStateOf(false) }
    if (renaming) {
        var name by remember { mutableStateOf(playlist.name) }
        AlertDialog(
            onDismissRequest = { renaming = false },
            title = { Text("Renombrar playlist") },
            text = { OutlinedTextField(value = name, onValueChange = { name = it }, singleLine = true, label = { Text("Nombre") }) },
            confirmButton = { TextButton(onClick = { renaming = false; vm.rename(name.trim()) }, enabled = name.isNotBlank()) { Text("Guardar") } },
            dismissButton = { TextButton(onClick = { renaming = false }) { Text("Cancelar") } },
        )
    }
    Column {
        HorizontalDivider(Modifier.padding(vertical = 8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(playlist.name, style = MaterialTheme.typography.titleLarge, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text(songCount(playlist.items.size), style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f))
            }
            Menu("Opciones de la playlist") { close ->
                DropdownMenuItem(text = { Text("Añadir la canción que suena") }, enabled = !vm.busy, onClick = { close(); vm.addCurrent() })
                DropdownMenuItem(text = { Text("Renombrar") }, enabled = !vm.busy, onClick = { close(); renaming = true })
                DropdownMenuItem(text = { Text("Descargar en este teléfono") }, enabled = !vm.busy, onClick = { close(); vm.pin() })
                DropdownMenuItem(text = { Text("Exportar copia a Navidrome") }, enabled = !vm.busy, onClick = { close(); vm.export() })
                DropdownMenuItem(text = { Text("Eliminar playlist") }, enabled = !vm.busy, onClick = { close(); onDelete() })
            }
            PlayAndShuffle(
                enabled = playlist.items.isNotEmpty(),
                onPlay = { vm.playList() },
                player = vm.player,
                playLabel = "Reproducir la playlist",
            )
        }
    }
}

@Composable
private fun Menu(label: String, content: @Composable (close: () -> Unit) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        IconButton(onClick = { open = true }) { Icon(Icons.Default.MoreVert, label) }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) { content { open = false } }
    }
}

@Composable
fun MixedDetail(id: String, back: () -> Unit, vm: HomelabViewModel = androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel()) {
    var delete by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf(false) }
    androidx.compose.runtime.LaunchedEffect(id) { vm.select(id) }
    // Once the list is deleted there is nothing left to show: back to Biblioteca. A failure stays on screen.
    androidx.compose.runtime.LaunchedEffect(deleting, vm.busy) {
        if (deleting && !vm.busy) { deleting = false; if (vm.error == null) back() }
    }
    androidx.compose.foundation.lazy.LazyColumn(Modifier.fillMaxSize().statusBarsPadding().padding(horizontal = 16.dp)) {
        item { IconButton(onClick = back) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Volver") } }
        vm.error?.let { item { Text(it) } }
        mixedContents(vm) { delete = true }
    }
    if (delete) androidx.compose.material3.AlertDialog(onDismissRequest = { delete = false },
        title = { Text("¿Eliminar la playlist?") }, confirmButton = { TextButton(onClick = { delete = false; if (!vm.busy) { deleting = true; vm.delete() } }) { Text("Eliminar") } },
        dismissButton = { TextButton(onClick = { delete = false }) { Text("Cancelar") } })
}
