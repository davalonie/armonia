package com.armonia.app.ui.playlists

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.PlaylistPlay
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.pulltorefresh.rememberPullToRefreshState
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import com.armonia.app.R
import com.armonia.app.data.api.ImportStatusResponse
import com.armonia.app.data.api.Playlist

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlaylistsScreen(
    onPlaylistClick: (String) -> Unit,
    onFavorites: (() -> Unit)? = null,
    onMixed: (String) -> Unit = {},
    onImport: (() -> Unit)? = null,
    viewModel: PlaylistsViewModel = hiltViewModel(),
) {
    var coverTarget by rememberSaveable { mutableStateOf<ArrayList<String>?>(null) }
    val resolverContext = androidx.compose.ui.platform.LocalContext.current
    val resolver = resolverContext.contentResolver
    val picker = androidx.activity.compose.rememberLauncherForActivityResult(androidx.activity.result.contract.ActivityResultContracts.GetContent()) { uri ->
        val target = coverTarget
        coverTarget = null
        if (uri != null && target != null) viewModel.uploadCover(target[0], target[1], target[2]) { resolver.openInputStream(uri) }
    }
    fun chooseCover(kind: String, id: String) {
        coverTarget = arrayListOf(kind, id, viewModel.ownerId)
        picker.launch("image/*")
    }
    var createOpen by remember { mutableStateOf(false) }
    var renameTarget by remember { mutableStateOf<Playlist?>(null) }
    var deleteTarget by remember { mutableStateOf<Playlist?>(null) }

    var importOpen by remember { mutableStateOf(false) }
    var importStep by remember { mutableStateOf("source") }  // source | url | progress
    var importUrl by remember { mutableStateOf("") }

    // Once the import job is registered, jump the dialog to the progress view.
    LaunchedEffect(viewModel.importProgress) {
        if (viewModel.importProgress != null) importStep = "progress"
    }

    LaunchedEffect(viewModel.error) {
        viewModel.error?.let { android.widget.Toast.makeText(resolverContext, it, android.widget.Toast.LENGTH_LONG).show() }
    }
    Box(modifier = Modifier.fillMaxSize()) {
    Scaffold(
        contentWindowInsets = WindowInsets(0),
        topBar = {
            if (onFavorites == null) TopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            painter = painterResource(id = R.drawable.ic_armonia),
                            contentDescription = null,
                            modifier = Modifier.size(40.dp),
                            tint = Color.Unspecified
                        )
                        Spacer(Modifier.width(6.dp))
                        Text(
                            "Playlists",
                            color = Color.White,
                            style = MaterialTheme.typography.headlineMedium
                        )
                    }
                },
                actions = {
                    IconButton(onClick = {
                        if(onImport!=null){onImport();return@IconButton}
                        importStep = if (viewModel.importProgress != null) "progress" else "source"
                        importUrl = ""
                        viewModel.importStartError = null
                        importOpen = true
                    }) {
                        Icon(Icons.Default.Download, contentDescription = "Importar playlist")
                    }
                    IconButton(onClick = { createOpen = true }) {
                        Icon(Icons.Default.Add, contentDescription = "Nueva playlist")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
            )
        }
    ) { padding ->
        Column(modifier = Modifier.padding(padding).fillMaxSize()) {
            OutlinedTextField(
                value = viewModel.filter,
                onValueChange = { viewModel.filter = it },
                placeholder = { Text("Buscar en tus playlists…") },
                leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            )

            val pullState = rememberPullToRefreshState()
            PullToRefreshBox(
                isRefreshing = viewModel.isLoading,
                onRefresh = { viewModel.load(pulled = true) },
                state = pullState,
                modifier = Modifier.fillMaxSize(),
            ) {
                when {
                    onFavorites == null && viewModel.isLoading && viewModel.filtered.isEmpty() -> CircularProgressIndicator(modifier = Modifier.align(Alignment.Center))
                    onFavorites == null && viewModel.error != null -> Text(
                        text = viewModel.error!!,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.align(Alignment.Center),
                    )
                    onFavorites == null && viewModel.filtered.isEmpty() -> Text(
                        text = if (viewModel.filter.isBlank()) "Todavia no hay playlists" else "Sin coincidencias",
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                        modifier = Modifier.align(Alignment.Center),
                    )
                    else -> LazyColumn(modifier = Modifier.fillMaxSize()) {
                        if (viewModel.stale) item(key = "saved-copy") { com.armonia.app.ui.components.SavedCopyNotice() }
                        if (onFavorites != null) {
                            item(key = "favorites") {
                                Row(Modifier.fillMaxWidth().clickable(onClick = onFavorites).padding(horizontal = 16.dp, vertical = 8.dp),
                                    verticalAlignment = Alignment.CenterVertically) {
                                    com.armonia.app.ui.components.FavoritesCover(Modifier.size(48.dp).clip(RoundedCornerShape(8.dp)))
                                    Spacer(Modifier.width(12.dp))
                                    Text("Tus favoritos", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Medium)
                                }
                            }
                            if (viewModel.error != null) item { Text("No se pudieron cargar tus playlists", Modifier.padding(horizontal = 16.dp)) }
                        }
                        // The same playlists as the Playlists screen of 0.5: also those other accounts share with this one.
                        items(viewModel.filtered, key = { it.id }) { p ->
                            PlaylistRow(
                                playlist = p, coverUrl = p.coverArt?.let(viewModel::coverUrl),
                                onCover = if (p.owner == viewModel.username) ({ chooseCover("local", p.id) }) else null,
                                onClick = { onPlaylistClick(p.id) },
                                onRename = { renameTarget = p },
                                onDelete = { deleteTarget = p },
                            )
                        }
                        if (onFavorites != null) items(viewModel.mixed.filter {
                            com.armonia.app.ui.components.matchesSearch(viewModel.filter, it.name)
                        }, key = { "mixed:${it.id}" }) { mixed ->
                            Row(Modifier.fillMaxWidth().clickable { onMixed(mixed.id) }.padding(horizontal = 16.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically) {
                                Box(Modifier.size(48.dp).clip(RoundedCornerShape(8.dp)).background(MaterialTheme.colorScheme.surfaceVariant),
                                    contentAlignment = Alignment.Center) {
                                    if (mixed.coverArt != null) coil.compose.AsyncImage(viewModel.coverUrl(mixed.coverArt), null, Modifier.fillMaxSize())
                                    else Icon(Icons.AutoMirrored.Filled.PlaylistPlay, contentDescription = null,
                                        tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f))
                                }
                                Spacer(Modifier.width(12.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(mixed.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Medium,
                                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    Text("con canciones externas", style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f))
                                }
                                IconButton(onClick = { chooseCover("mixed", mixed.id) }) { Icon(Icons.Default.Edit, "Cambiar portada") }
                            }
                        }
                    }
                }
            }
        }
    }

        // Re-entry pill while an import keeps running after "Ejecutar en segundo plano".
        val importProg = viewModel.importProgress
        if (importProg != null && !importOpen) {
            ImportPill(
                progress = importProg,
                onClick = { importStep = "progress"; importOpen = true },
                modifier = Modifier.align(Alignment.BottomEnd).padding(16.dp),
            )
        }
    }

    if (importOpen) {
        ImportDialog(
            step = importStep,
            url = importUrl,
            onUrlChange = { importUrl = it },
            starting = viewModel.importStarting,
            startError = viewModel.importStartError,
            progress = viewModel.importProgress,
            onPickSpotify = { importStep = "url"; viewModel.importStartError = null },
            onBack = { importStep = "source" },
            onStart = { viewModel.startImport(importUrl) },
            onRunInBackground = { importOpen = false },
            onDone = { viewModel.dismissImport(); importOpen = false },
            onDismiss = { importOpen = false },
        )
    }

    if (createOpen) {
        NameDialog(
            title = "Nueva playlist",
            confirmLabel = "Crear",
            initialName = "",
            onConfirm = { name ->
                viewModel.create(name)
                createOpen = false
            },
            onDismiss = { createOpen = false },
        )
    }

    renameTarget?.let { target ->
        NameDialog(
            title = "Renombrar playlist",
            confirmLabel = "Guardar",
            initialName = target.name,
            onConfirm = { name ->
                viewModel.rename(target.id, name)
                renameTarget = null
            },
            onDismiss = { renameTarget = null },
        )
    }

    deleteTarget?.let { target ->
        AlertDialog(
            onDismissRequest = { deleteTarget = null },
            title = { Text("¿Eliminar la playlist?") },
            text = { Text("«${target.name}» se eliminara para siempre. Sus canciones siguen en tu biblioteca.") },
            confirmButton = {
                TextButton(onClick = {
                    viewModel.delete(target.id)
                    deleteTarget = null
                }) {
                    Text("Eliminar", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { deleteTarget = null }) { Text("Cancelar") }
            },
        )
    }
}

@Composable
private fun PlaylistRow(
    playlist: Playlist,
    coverUrl: String?,
    onCover: (() -> Unit)?,
    onClick: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
) {
    var menuOpen by remember { mutableStateOf(false) }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(48.dp)
                .clip(RoundedCornerShape(8.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant),
            contentAlignment = Alignment.Center,
        ) {
            if (coverUrl != null) coil.compose.AsyncImage(coverUrl, null, Modifier.fillMaxSize())
            else Icon(
                Icons.AutoMirrored.Filled.PlaylistPlay,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
            )
        }
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = playlist.name,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Medium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = songCount(playlist.songCount),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
            )
        }
        Box {
            IconButton(onClick = { menuOpen = true }) {
                Icon(Icons.Default.MoreVert, contentDescription = "Mas opciones")
            }
            DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                if (onCover != null) DropdownMenuItem(text = { Text("Cambiar portada") }, onClick = { menuOpen = false; onCover() })
                DropdownMenuItem(
                    text = { Text("Renombrar") },
                    leadingIcon = { Icon(Icons.Default.Edit, null) },
                    onClick = { menuOpen = false; onRename() },
                )
                HorizontalDivider()
                DropdownMenuItem(
                    text = { Text("Eliminar", color = MaterialTheme.colorScheme.error) },
                    leadingIcon = {
                        Icon(Icons.Default.Delete, null, tint = MaterialTheme.colorScheme.error)
                    },
                    onClick = { menuOpen = false; onDelete() },
                )
            }
        }
    }
}

@Composable
internal fun NameDialog(
    title: String,
    confirmLabel: String,
    initialName: String,
    onConfirm: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var name by remember { mutableStateOf(initialName) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            OutlinedTextField(
                value = name,
                onValueChange = { name = it },
                placeholder = { Text("Nombre de la playlist") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { onConfirm(name) }),
            )
        },
        confirmButton = {
            TextButton(
                onClick = { onConfirm(name) },
                enabled = name.trim().isNotBlank(),
            ) { Text(confirmLabel) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancelar") } },
    )
}

@Composable
private fun ImportPill(
    progress: ImportStatusResponse,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        onClick = onClick,
        modifier = modifier,
        shape = RoundedCornerShape(50),
        color = MaterialTheme.colorScheme.surfaceVariant,
        shadowElevation = 6.dp,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            when (progress.status) {
                "running" -> {
                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.primary)
                    Spacer(Modifier.width(8.dp))
                    Text("Importando ${progress.current}/${progress.total}", style = MaterialTheme.typography.labelLarge)
                }
                "done" -> {
                    Icon(Icons.Default.CheckCircle, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Text("Importacion completada", style = MaterialTheme.typography.labelLarge)
                }
                else -> {
                    Icon(Icons.Default.Error, null, tint = MaterialTheme.colorScheme.error, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Text("La importacion ha fallado", style = MaterialTheme.typography.labelLarge)
                }
            }
        }
    }
}

@Composable
private fun ImportDialog(
    step: String,
    url: String,
    onUrlChange: (String) -> Unit,
    starting: Boolean,
    startError: String?,
    progress: ImportStatusResponse?,
    onPickSpotify: () -> Unit,
    onBack: () -> Unit,
    onStart: () -> Unit,
    onRunInBackground: () -> Unit,
    onDone: () -> Unit,
    onDismiss: () -> Unit,
) {
    val muted = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Importar playlist") },
        text = {
            when (step) {
                "source" -> Column {
                    Text("Importar desde", style = MaterialTheme.typography.bodySmall, color = muted)
                    Spacer(Modifier.height(8.dp))
                    Surface(
                        onClick = onPickSpotify,
                        shape = RoundedCornerShape(12.dp),
                        color = MaterialTheme.colorScheme.surfaceVariant,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.MusicNote, null, tint = Color(0xFF1DB954))
                            Spacer(Modifier.width(12.dp))
                            Text("Spotify", fontWeight = FontWeight.Medium)
                        }
                    }
                }
                "url" -> Column {
                    Text("Pega el enlace de una playlist publica de Spotify", style = MaterialTheme.typography.bodySmall, color = muted)
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = url,
                        onValueChange = onUrlChange,
                        placeholder = { Text("https://open.spotify.com/playlist/…") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    startError?.let {
                        Spacer(Modifier.height(8.dp))
                        Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                    }
                }
                else -> Column {
                    Text(progress?.name ?: "", fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Spacer(Modifier.height(8.dp))
                    when (progress?.status) {
                        "done" -> {
                            Text(
                                "Importadas ${progress.downloaded + progress.existing} de ${progress.total} canciones" +
                                    if (progress.playlistId != null) " — playlist creada." else "",
                                style = MaterialTheme.typography.bodySmall, color = muted,
                            )
                            Spacer(Modifier.height(4.dp))
                            Text(
                                "${progress.downloaded} descargadas · ${progress.existing} ya estaban" +
                                    if (progress.failed > 0) " · ${progress.failed} sin encontrar" else "",
                                style = MaterialTheme.typography.bodySmall, color = muted,
                            )
                            if (progress.failures.isNotEmpty()) {
                                Spacer(Modifier.height(8.dp))
                                Text("No se ha encontrado:", style = MaterialTheme.typography.labelMedium)
                                Column(Modifier.heightIn(max = 140.dp).verticalScroll(rememberScrollState())) {
                                    progress.failures.forEach {
                                        Text("• $it", style = MaterialTheme.typography.bodySmall, color = muted)
                                    }
                                }
                            }
                        }
                        "error" -> Text(progress.error ?: "La importacion ha fallado", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                        else -> {
                            Text(
                                if (progress == null) "Iniciando…" else "Importando ${progress.current} de ${progress.total}…",
                                style = MaterialTheme.typography.bodySmall, color = muted,
                            )
                            Spacer(Modifier.height(8.dp))
                            val frac = if (progress != null && progress.total > 0) progress.current.toFloat() / progress.total else 0f
                            LinearProgressIndicator(progress = { frac }, modifier = Modifier.fillMaxWidth())
                            progress?.let {
                                Spacer(Modifier.height(8.dp))
                                Text(
                                    "${it.downloaded} nuevas · ${it.existing} ya estaban" + if (it.failed > 0) " · ${it.failed} con error" else "",
                                    style = MaterialTheme.typography.bodySmall, color = muted,
                                )
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            when (step) {
                "url" -> TextButton(onClick = onStart, enabled = url.isNotBlank() && !starting) {
                    Text(if (starting) "Iniciando…" else "Importar")
                }
                "progress" -> {
                    if (progress == null || progress.status == "running") {
                        TextButton(onClick = onRunInBackground) { Text("Ejecutar en segundo plano") }
                    } else {
                        TextButton(onClick = onDone) { Text("Hecho") }
                    }
                }
                else -> {}
            }
        },
        dismissButton = {
            when (step) {
                "source" -> TextButton(onClick = onDismiss) { Text("Cancelar") }
                "url" -> TextButton(onClick = onBack) { Text("Volver") }
                else -> {}
            }
        },
    )
}
