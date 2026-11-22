package com.armonia.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.QueueMusic
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Search
import androidx.compose.foundation.selection.toggleable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import coil.compose.AsyncImage
import com.armonia.app.data.api.Song
import com.armonia.app.data.api.Playlist
import com.armonia.app.data.repository.LibraryRepository
import com.armonia.app.data.repository.PreferencesRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.*
import javax.inject.Inject

@HiltViewModel
class AddToPlaylistViewModel @Inject constructor(
    private val repository: LibraryRepository,
    private val prefs: PreferencesRepository,
) : ViewModel() {
    private val account = prefs.cachedAuth
    private var loading: Job? = null
    var playlists by mutableStateOf<List<Playlist>>(emptyList()); private set
    var included by mutableStateOf<Set<String>>(emptySet()); private set
    var selected by mutableStateOf<Set<String>>(emptySet()); private set
    var isLoading by mutableStateOf(false); private set
    var busy by mutableStateOf(false); private set
    var message by mutableStateOf<String?>(null); private set
    var ready by mutableStateOf(false); private set
    /** The song is not in the library yet: saving it downloads it first («Descargar y guardar»). */
    var needsDownload by mutableStateOf(false); private set
    val revision = repository.membershipRevision
    suspend fun saved(id: String) = repository.isSaved(id)
    fun cover(id: String) = repository.getCoverArtUrl(id)
    fun load(song: Song) {
        ready = false; loading?.cancel(); selected = emptySet(); included = emptySet(); message = null
        needsDownload = song.downloadsOnSave() && repository.localCopy(song.id) == null
        loading = viewModelScope.launch {
            isLoading = true
            try {
                check(account == prefs.cachedAuth)
                playlists = repository.getPlaylists().getOrThrow().playlists?.playlist.orEmpty()
                    .filter { it.owner == account.username }
                // A preview already downloaded shows the lists and favourite of its library copy. If that copy was
                // deleted since, it is forgotten and saving downloads the song again.
                val membership = repository.copyMembership(song, account)
                needsDownload = song.downloadsOnSave() && repository.localCopy(song.id) == null
                check(account == prefs.cachedAuth)
                included = membership?.playlists.orEmpty().toSet() + (if (membership?.favorite == true) setOf(FAVORITES) else emptySet())
                selected = included
                ready = true
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { message = e.message ?: "No se pudieron comprobar las playlists" }
            finally { isLoading = false }
        }
    }
    fun toggle(id: String) { selected = if (id in selected) selected - id else selected + id }
    fun create(name: String) {
        if (busy || name.isBlank()) return
        busy = true
        viewModelScope.launch {
            try {
                check(account == prefs.cachedAuth)
                val before = playlists.map { it.id }.toSet()
                repository.createPlaylist(name.trim()).getOrThrow()
                playlists = repository.getPlaylists().getOrThrow().playlists?.playlist.orEmpty().filter { it.owner == account.username }
                playlists.singleOrNull { it.id !in before && it.name == name.trim() }?.let { selected = selected + it.id }
                message = "Playlist creada y marcada. Pulsa Guardar para añadir la canción."
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { message = e.message }
            finally { busy = false }
        }
    }
    fun confirm(song: Song, onDone: () -> Unit) {
        if (busy) return
        busy = true; message = null
        viewModelScope.launch {
            val failures = mutableListOf<String>()
            try {
                // A playlist only holds library songs, so one not downloaded yet is downloaded first, wherever
                // it is saved from. Sending its preview id instead used to save nothing while saying it had.
                val localId = repository.localCopy(song.id) ?: run {
                    check(song.downloadsOnSave()) { "Esta canción no se puede guardar en una playlist" }
                    // The download can take a while: say so instead of leaving the sheet silently disabled.
                    message = "Descargando «${song.title}»…"
                    repository.downloadForPlaylist(song, account).also { message = null; needsDownload = false }
                }
                for (id in (selected - included) + (included - selected)) {
                    check(account == prefs.cachedAuth)
                    val add = id in selected
                    runCatching {
                        if (id == FAVORITES) {
                            (if (add) repository.star(localId) else repository.unstar(localId)).getOrThrow()
                        } else repository.setMembership(id, localId, add, account)
                    }.onSuccess { included = if (add) included + id else included - id }
                        .onFailure { failures += "No se pudo guardar el cambio" }

                }
                if (failures.isEmpty()) onDone() else message = failures.joinToString(" · ")
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { message = e.message }
            finally { busy = false }
        }
    }
}

/**
 * Choose one or several playlists to save a song in (the opposite direction of "Añadir
 * canciones", which picks songs for one playlist): search, covers, and a new playlist in place.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddToPlaylistSheet(song: Song, onDismiss: () -> Unit, viewModel: AddToPlaylistViewModel = hiltViewModel()) {
    var query by rememberSaveable(song.id) { mutableStateOf("") }
    var name by rememberSaveable(song.id) { mutableStateOf("") }
    var creating by rememberSaveable(song.id) { mutableStateOf(false) }
    var byCount by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(song.id) { viewModel.load(song) }
    val muted = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
    ModalBottomSheet(onDismissRequest = { if (!viewModel.busy) onDismiss() },
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.fillMaxWidth().heightIn(max = 640.dp).padding(horizontal = 16.dp).padding(bottom = 12.dp)) {
            Text("Guardar en una playlist", style = MaterialTheme.typography.titleLarge)
            Text("${song.title} · ${song.artist}", style = MaterialTheme.typography.bodySmall, color = muted,
                maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 2.dp, bottom = 10.dp))
            TextField(
                value = query, onValueChange = { query = it },
                placeholder = { Text("Buscar playlist") },
                leadingIcon = { Icon(Icons.Default.Search, null) },
                singleLine = true, shape = RoundedCornerShape(28.dp),
                colors = TextFieldDefaults.colors(
                    focusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHighest,
                    unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHighest,
                    focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent,
                ),
                modifier = Modifier.fillMaxWidth(),
            )
            Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = { creating = !creating }, enabled = !viewModel.busy) {
                    Icon(Icons.Default.Add, null, Modifier.size(18.dp)); Spacer(Modifier.width(6.dp)); Text("Nueva playlist")
                }
                Spacer(Modifier.weight(1f))
                TextButton(onClick = { byCount = !byCount }) { Text(if (byCount) "Orden: más canciones" else "Orden: nombre") }
            }
            if (creating) Row(Modifier.fillMaxWidth().padding(bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(name, { name = it.take(150) }, label = { Text("Nombre de la playlist nueva") }, singleLine = true, modifier = Modifier.weight(1f))
                Spacer(Modifier.width(8.dp))
                Button(onClick = { viewModel.create(name); name = ""; creating = false },
                    enabled = !viewModel.busy && !viewModel.isLoading && name.isNotBlank()) { Text("Crear") }
            }
            if (viewModel.isLoading || viewModel.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            viewModel.message?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(vertical = 4.dp))
            }
            LazyColumn(Modifier.weight(1f, fill = false)) {
                if (song.canSaveInPlaylists()) item(key = FAVORITES) {
                    // Laid out like a playlist row, with Inicio's favourites cover.
                    val checked = FAVORITES in viewModel.selected
                    val enabled = viewModel.ready && !viewModel.busy
                    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp))
                        .toggleable(value = checked, enabled = enabled, role = Role.Checkbox) { viewModel.toggle(FAVORITES) }
                        .padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        FavoritesCover(Modifier.size(48.dp).clip(RoundedCornerShape(6.dp)))
                        Column(Modifier.weight(1f).padding(horizontal = 12.dp)) {
                            Text("Tus favoritos", style = MaterialTheme.typography.titleSmall, maxLines = 1)
                            if (FAVORITES in viewModel.included) Text("Ya está en tus favoritos",
                                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
                        }
                        Checkbox(checked = checked, onCheckedChange = null, enabled = enabled)
                    }
                }
                val filtered = viewModel.playlists.filter { matchesSearch(query, it.name) }
                if (filtered.isEmpty() && !viewModel.isLoading) item {
                    Text(if (viewModel.playlists.isEmpty()) "Todavía no tienes playlists. Crea una con «Nueva playlist»." else "Ninguna playlist coincide con «${query.trim()}».",
                        color = muted, modifier = Modifier.padding(vertical = 16.dp))
                }
                items(if (byCount) filtered.sortedByDescending { it.songCount } else filtered.sortedBy { it.name.lowercase() }, key = { it.id }) { p ->
                    val included = p.id in viewModel.included
                    val enabled = !viewModel.busy && viewModel.ready
                    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp))
                        .toggleable(value = p.id in viewModel.selected, enabled = enabled, role = Role.Checkbox) { viewModel.toggle(p.id) }
                        .padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(48.dp).clip(RoundedCornerShape(6.dp))
                            .background(MaterialTheme.colorScheme.surfaceContainerHighest), contentAlignment = Alignment.Center) {
                            // The note shows through while the cover loads and for a playlist without one.
                            Icon(Icons.AutoMirrored.Filled.QueueMusic, contentDescription = null,
                                tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.45f))
                            p.coverArt?.let {
                                AsyncImage(viewModel.cover(it), contentDescription = null,
                                    contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                            }
                        }
                        Column(Modifier.weight(1f).padding(horizontal = 12.dp)) {
                            Text(p.name, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(if (included) "Ya está en esta playlist" else if (p.songCount == 1) "1 canción" else "${p.songCount} canciones",
                                style = MaterialTheme.typography.bodySmall, color = if (included) MaterialTheme.colorScheme.primary else muted)
                        }
                        Checkbox(checked = p.id in viewModel.selected, onCheckedChange = null, enabled = enabled)
                    }
                }
            }
            Row(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.End, verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = onDismiss, enabled = !viewModel.busy) { Text("Cancelar") }
                Spacer(Modifier.width(8.dp))
                Button(onClick = { viewModel.confirm(song, onDismiss) },
                    enabled = !viewModel.busy && viewModel.ready && viewModel.selected != viewModel.included) {
                    Text(if (viewModel.needsDownload) "Descargar y guardar" else "Guardar")
                }
            }
        }
    }
}

private const val FAVORITES = ":favoritos"

/** A song found outside the library (YouTube) that saving it in a playlist downloads first. */
internal fun Song.downloadsOnSave() = id.startsWith("preview|")

/** Library songs and songs from YouTube can go in a playlist or favourites; songs from other external sources cannot. */
internal fun Song.canSaveInPlaylists() = !id.startsWith("external|")
