package com.armonia.app.ui.library

import com.armonia.app.ui.components.FastScroll
import com.armonia.app.ui.components.scrollInitial
import androidx.compose.runtime.remember
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Album
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import coil.compose.AsyncImage

/** Search field shared by the collection screens, in the style of Buscar. */
@Composable
fun CollectionSearchField(value: String, onChange: (String) -> Unit, hint: String, modifier: Modifier = Modifier) {
    TextField(
        value = value,
        onValueChange = onChange,
        placeholder = { Text(hint) },
        leadingIcon = { Icon(Icons.Default.Search, null) },
        trailingIcon = { if (value.isNotEmpty()) IconButton(onClick = { onChange("") }) { Icon(Icons.Default.Close, "Borrar la busqueda") } },
        singleLine = true,
        shape = RoundedCornerShape(28.dp),
        colors = TextFieldDefaults.colors(
            focusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
            unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
            focusedIndicatorColor = Color.Transparent,
            unfocusedIndicatorColor = Color.Transparent,
        ),
        modifier = modifier.fillMaxWidth(),
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CollectionTopBar(title: String, onBack: () -> Unit) {
    TopAppBar(
        title = { Text(title, style = MaterialTheme.typography.headlineMedium) },
        navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Volver") } },
        colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
    )
}

/** Albums of the library as a cover grid, as on the web: search, order, album artist under the title. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AlbumsScreen(onAlbumClick: (String) -> Unit, onBack: () -> Unit, embedded: Boolean = false, viewModel: CollectionViewModel = hiltViewModel()) {
    Scaffold(contentWindowInsets = WindowInsets(0), topBar = { if (!embedded) CollectionTopBar("Albumes", onBack) }) { padding ->
        PullToRefreshBox(isRefreshing = viewModel.isLoading, onRefresh = { viewModel.load() }, modifier = Modifier.padding(padding).fillMaxSize()) {
            val shown = viewModel.shownAlbums
            val state = androidx.compose.foundation.lazy.grid.rememberLazyGridState()
            val labels = remember(shown, viewModel.albumSort) { shown.map { when (viewModel.albumSort) {
                    "year" -> it.year?.toString() ?: "—"
                    "artist" -> scrollInitial(it.artist)
                    else -> scrollInitial(it.name)
                } } }
            LazyVerticalGrid(state = state,
                columns = GridCells.Adaptive(150.dp),
                contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 16.dp),
                horizontalArrangement = Arrangement.spacedBy(14.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
                modifier = Modifier.fillMaxSize(),
            ) {
                item(span = { GridItemSpan(maxLineSpan) }) {
                    Column {
                        CollectionSearchField(viewModel.albumQuery, { viewModel.albumQuery = it }, "Buscar en tus albumes")
                        Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            listOf("name" to "Nombre", "artist" to "Artista", "year" to "Mas recientes").forEach { (key, label) ->
                                FilterChip(selected = viewModel.albumSort == key, onClick = { viewModel.albumSort = key }, label = { Text(label) })
                            }
                        }
                        Text(
                            when {
                                viewModel.error != null -> viewModel.error!!
                                viewModel.isLoading && viewModel.albums.isEmpty() -> "Cargando tus albumes…"
                                viewModel.albums.isEmpty() -> "Todavia no hay albumes en tu biblioteca."
                                shown.isEmpty() -> "Ningun album coincide con «${viewModel.albumQuery.trim()}»."
                                else -> albumCount(shown.size)
                            },
                            style = MaterialTheme.typography.bodySmall,
                            color = if (viewModel.error != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                            modifier = Modifier.padding(top = 6.dp),
                        )
                    }
                }
                items(shown, key = { it.id }) { album ->
                    Column(Modifier.clip(RoundedCornerShape(10.dp)).clickable { onAlbumClick(album.id) }) {
                        Box(
                            Modifier.fillMaxWidth().aspectRatio(1f).clip(RoundedCornerShape(10.dp))
                                .background(MaterialTheme.colorScheme.surfaceContainerHighest),
                            contentAlignment = Alignment.Center,
                        ) {
                            Icon(Icons.Default.Album, null, tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.3f), modifier = Modifier.size(40.dp))
                            album.coverArt?.let {
                                AsyncImage(viewModel.cover(it), contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                            }
                        }
                        Text(album.name, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold,
                            maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 8.dp))
                        Text(
                            listOfNotNull(album.artist.takeIf { it.isNotBlank() }, album.year?.takeIf { it > 0 }?.toString()).joinToString(" · "),
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                            maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 2.dp, bottom = 4.dp),
                        )
                    }
                }
            }
            FastScroll(labels, { state.firstVisibleItemIndex }, state.isScrollInProgress, 1) { state.scrollToItem(it) }
        }
    }
}

/** Round picture for an artist: an album cover when there is one, the initial otherwise. */
@Composable
fun ArtistAvatar(name: String, coverUrl: String?, modifier: Modifier = Modifier) {
    val tints = listOf(Color(0xFF5B2DD6), Color(0xFF8E5BD6), Color(0xFF3F6FB5), Color(0xFF2F8F83), Color(0xFFB5527A), Color(0xFF7A6A2F))
    Box(
        modifier.clip(CircleShape).background(tints[(name.hashCode() and Int.MAX_VALUE) % tints.size]),
        contentAlignment = Alignment.Center,
    ) {
        Text(name.trim().take(1).uppercase().ifEmpty { "?" }, color = Color.White, fontWeight = FontWeight.Bold, fontSize = 22.sp)
        if (coverUrl != null) AsyncImage(coverUrl, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
    }
}
