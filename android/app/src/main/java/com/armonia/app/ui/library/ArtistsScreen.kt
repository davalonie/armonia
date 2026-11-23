package com.armonia.app.ui.library

import com.armonia.app.ui.components.FastScroll
import com.armonia.app.ui.components.scrollInitial
import androidx.compose.runtime.remember
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import com.armonia.app.data.api.Artist

/** Artists who sign albums of the library: search, order by name or by number of albums. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ArtistsScreen(onArtistClick: (Artist) -> Unit, onBack: () -> Unit = {}, embedded: Boolean = false, viewModel: CollectionViewModel = hiltViewModel()) {
    Scaffold(contentWindowInsets = WindowInsets(0), topBar = { if (!embedded) CollectionTopBar("Artistas", onBack) }) { padding ->
        PullToRefreshBox(isRefreshing = viewModel.isLoading, onRefresh = { viewModel.load() }, modifier = Modifier.padding(padding).fillMaxSize()) {
            val shown = viewModel.shownArtists
            val state = androidx.compose.foundation.lazy.rememberLazyListState()
            val labels = remember(shown, viewModel.artistSort) { shown.map { if (viewModel.artistSort == "albums") albumCount(it.albums) else scrollInitial(it.artist.name) } }
            LazyColumn(state = state, modifier = Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 16.dp)) {
                item {
                    Column(Modifier.padding(horizontal = 16.dp)) {
                        CollectionSearchField(viewModel.artistQuery, { viewModel.artistQuery = it }, "Buscar en tus artistas")
                        Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            listOf("name" to "Nombre", "albums" to "Mas albumes").forEach { (key, label) ->
                                FilterChip(selected = viewModel.artistSort == key, onClick = { viewModel.artistSort = key }, label = { Text(label) })
                            }
                        }
                        Text(
                            when {
                                viewModel.error != null -> viewModel.error!!
                                viewModel.isLoading && viewModel.artists.isEmpty() -> "Cargando tus artistas…"
                                viewModel.artists.isEmpty() -> "Todavia no hay artistas en tu biblioteca."
                                shown.isEmpty() -> "Ningun artista coincide con «${viewModel.artistQuery.trim()}»."
                                else -> if (shown.size == 1) "1 artista" else "${shown.size} artistas"
                            },
                            style = MaterialTheme.typography.bodySmall,
                            color = if (viewModel.error != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                            modifier = Modifier.padding(top = 6.dp, bottom = 4.dp),
                        )
                    }
                }
                items(shown, key = { it.artist.id }) { entry ->
                    Row(
                        modifier = Modifier.fillMaxWidth().clickable { onArtistClick(entry.artist) }.padding(horizontal = 16.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        ArtistAvatar(entry.artist.name, entry.cover?.let { viewModel.cover(it, 128) }, Modifier.size(56.dp))
                        Spacer(Modifier.width(14.dp))
                        Column(Modifier.weight(1f)) {
                            Text(entry.artist.name, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(albumCount(entry.albums), style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f))
                        }
                    }
                }
            }
            FastScroll(labels, { state.firstVisibleItemIndex }, state.isScrollInProgress, 1) { state.scrollToItem(it) }
        }
    }
}
