package com.armonia.app.ui.main

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.PlaylistPlay
import androidx.compose.material.icons.automirrored.filled.QueueMusic
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import com.armonia.app.ui.library.AlbumDetailScreen
import com.armonia.app.ui.library.ArtistDetailScreen
import com.armonia.app.ui.library.ArtistsScreen
import com.armonia.app.ui.library.LibraryScreen
import com.armonia.app.ui.player.ExpandedPlayerScreen
import com.armonia.app.ui.player.MiniPlayer
import com.armonia.app.ui.player.QueueSheet
import com.armonia.app.ui.playlists.PlaylistDetailScreen
import com.armonia.app.ui.playlists.PlaylistsScreen
import com.armonia.app.ui.downloads.DownloadsScreen
import com.armonia.app.ui.offline.OfflineScreen
import com.armonia.app.ui.settings.SettingsScreen
import com.armonia.app.ui.ytmusic.YtAlbumScreen
import com.armonia.app.ui.ytmusic.YtArtistScreen
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument

sealed class Screen(val route: String, val label: String, val icon: ImageVector) {
    object Homelab : Screen("homelab", "Inicio", Icons.Default.Home)
    object Search : Screen("search", "Buscar", Icons.Default.Search)
    object Library : Screen("library", "Biblioteca", Icons.Default.LibraryMusic)
    object Downloads : Screen("downloads", "Descargas", Icons.Default.Download)
    object Playlists : Screen("playlists", "Playlists", Icons.AutoMirrored.Filled.PlaylistPlay)
    object Favorites : Screen("favorites", "Favoritos", Icons.Default.Favorite)
    object Artists : Screen("artists", "Artistas", Icons.Default.Person)
    object Settings : Screen("settings", "Ajustes", Icons.Default.Settings)
    object Offline : Screen("offline", "Musica sin conexion", Icons.Default.CloudOff)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(
    viewModel: MainViewModel = hiltViewModel()
) {
    val navController = rememberNavController()
    var libraryTab by rememberSaveable { mutableStateOf("Playlists") }
    fun openOfflineLibrary() {
        libraryTab = "En el telefono"
        navController.navigate(Screen.Library.route) { launchSingleTop = true }
    }
    var searchSeed by remember { mutableStateOf("") }
    val navItems = listOf(
        Screen.Homelab,
        Screen.Search,
        Screen.Library,
    )

    var expandedPlayerOpen by rememberSaveable { mutableStateOf(false) }
    var moreSheetOpen by remember { mutableStateOf(false) }
    var queueSheetOpen by remember { mutableStateOf(false) }

    // Back while the player is open is handled inside PlayerPane. A handler here is registered
    // before the NavHost's own and loses to it, which made Back navigate behind the player.
    // A field left focused underneath would keep the keyboard up over the player.
    val focusManager = LocalFocusManager.current
    LaunchedEffect(expandedPlayerOpen) { if (expandedPlayerOpen) focusManager.clearFocus(force = true) }

    val currentSong by viewModel.musicPlayer.currentSong.collectAsState()
    if (currentSong == null && expandedPlayerOpen) {
        expandedPlayerOpen = false
    }

    // Playback failures (a preview the server couldn't fetch, a dropped
    // connection, ...) used to fail silently; surface them.
    val snackbarHostState = remember { SnackbarHostState() }
    val playbackError by viewModel.musicPlayer.playbackError.collectAsState()
    LaunchedEffect(playbackError) {
        val message = playbackError ?: return@LaunchedEffect
        snackbarHostState.showSnackbar(message, duration = SnackbarDuration.Long)
        viewModel.musicPlayer.dismissPlaybackError()
    }
    // Background library work that failed (e.g. a delete the server refused).
    LaunchedEffect(Unit) {
        // Failures stay up long enough to read; successes below stay short.
        viewModel.libraryRepository.messages.collect { snackbarHostState.showSnackbar(it, duration = SnackbarDuration.Long) }
    }
    // What playback did by itself (e.g. passed over songs that are not on the phone, offline).
    LaunchedEffect(Unit) {
        viewModel.playbackNotices.messages.collect {
            viewModel.musicPlayer.dismissPlaybackError()
            snackbarHostState.showSnackbar(it, duration = SnackbarDuration.Long)
        }
    }
    // One notice per insertion, each with its own undo; a newer one replaces the one showing.
    LaunchedEffect(Unit) {
        viewModel.musicPlayer.queued.collectLatest { queued ->
            val result = snackbarHostState.showSnackbar(
                message = when {
                    queued.next -> "«${queued.song.title}» sonara a continuacion"
                    queued.atEnd -> "«${queued.song.title}» añadida al final de la cola"
                    else -> "«${queued.song.title}» añadida a la cola"
                },
                actionLabel = "Deshacer",
                duration = SnackbarDuration.Short,
            )
            if (result == SnackbarResult.ActionPerformed) viewModel.musicPlayer.undoQueued(queued)
        }
    }
    // Server downloads finishing, wherever they were started.
    LaunchedEffect(Unit) {
        viewModel.downloadTracker.events.collect { event ->
            when (event) {
                is com.armonia.app.data.repository.DownloadEvent.Added ->
                    snackbarHostState.showSnackbar("«${event.title}» ya esta en tu biblioteca")
                is com.armonia.app.data.repository.DownloadEvent.Failed ->
                    snackbarHostState.showSnackbar("No se pudo descargar «${event.title}»: ${event.reason}", duration = SnackbarDuration.Long)
            }
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        // Touches are stopped by the player itself (PlayerPane.blocksTouchesBehind).
        com.armonia.app.ui.player.UnderPlayer(covered = expandedPlayerOpen) {
        Scaffold(
            contentWindowInsets = WindowInsets(0),
            snackbarHost = { SnackbarHost(snackbarHostState) },
            bottomBar = {
                Column {
                    MiniPlayer(onExpand = { expandedPlayerOpen = true })
                    NavigationBar(
                        containerColor = MaterialTheme.colorScheme.background,
                        tonalElevation = 0.dp,
                    ) {
                        val navBackStackEntry by navController.currentBackStackEntryAsState()
                        val currentDestination = navBackStackEntry?.destination
                        navItems.forEach { screen ->
                            NavigationBarItem(
                                icon = { Icon(screen.icon, contentDescription = null, modifier = Modifier.size(28.dp)) },
                                label = { Text(screen.label, fontSize = 10.sp) },
                                selected = currentDestination?.hierarchy?.any { it.route == screen.route } == true,
                                onClick = {
                                    navController.navigate(screen.route) {
                                        popUpTo(navController.graph.findStartDestination().id) {
                                            saveState = true
                                        }
                                        launchSingleTop = true
                                        restoreState = true
                                    }
                                },
                                colors = NavigationBarItemDefaults.colors(
                                    selectedIconColor = MaterialTheme.colorScheme.primary,
                                    selectedTextColor = MaterialTheme.colorScheme.primary,
                                    unselectedIconColor = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                                    unselectedTextColor = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                                    indicatorColor = MaterialTheme.colorScheme.secondary
                                )
                            )
                        }
                        NavigationBarItem(
                            icon = { Icon(Icons.Default.MoreHoriz, contentDescription = null) },
                            label = { Text("Mas", fontSize = 10.sp) },
                            selected = currentDestination?.hierarchy?.any {
                                it.route == Screen.Downloads.route ||
                                it.route in listOf("manual-inbox", "listening") ||
                                it.route == Screen.Settings.route
                            } == true,
                            onClick = { moreSheetOpen = true },
                            colors = NavigationBarItemDefaults.colors(
                                    selectedIconColor = MaterialTheme.colorScheme.primary,
                                    selectedTextColor = MaterialTheme.colorScheme.primary,
                                    unselectedIconColor = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                                    unselectedTextColor = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                                    indicatorColor = MaterialTheme.colorScheme.secondary
                                )
                        )
                    }
                }
            }
        ) { innerPadding ->
            // Ordinary screens with a short, quiet change: the 700 ms default cross-fade left
            // both screens on top of each other and read as a window laid over the previous one.
            NavHost(
                navController,
                startDestination = Screen.Homelab.route,
                Modifier.padding(innerPadding),
                enterTransition = { fadeIn(tween(160)) + slideInHorizontally(tween(200)) { it / 14 } },
                exitTransition = { fadeOut(tween(90)) },
                popEnterTransition = { fadeIn(tween(160)) },
                popExitTransition = { fadeOut(tween(110)) + slideOutHorizontally(tween(160)) { it / 14 } },
            ) {
                composable(Screen.Homelab.route) { com.armonia.app.ui.homelab.HomeScreen(onOpen={route->navController.navigate(route)}) }
                composable(Screen.Search.route) {
                    LibraryScreen(
                        startWithSearch = true,
                        initialSearch = searchSeed,
                        // Tapping a song just plays it (mini player); don't auto-open the
                        // expanded player — the user can tap the mini player to expand.
                        onSongClick = {},
                        onOpenSettings = { navController.navigate(Screen.Settings.route) },
                        onOpenOffline = ::openOfflineLibrary,
                        onArtistClick = { channelId -> navController.navigate("ytartist/$channelId") },
                    )
                }
                composable(Screen.Library.route) {
                    LibraryHome(libraryTab, { libraryTab = it }, { navController.navigate(it) })
                }
                composable("songs") { LibraryScreen(onSongClick = {}, onOpenOffline = ::openOfflineLibrary) }
                composable("mixed/{id}") { entry ->
                    com.armonia.app.ui.homelab.MixedDetail(entry.arguments?.getString("id").orEmpty(), back = { navController.popBackStack() })
                }
                composable("listening") { com.armonia.app.ui.homelab.ListeningScreen(open = { navController.navigate(it) }) }
                composable(Screen.Favorites.route) {
                    LibraryScreen(isFavorites = true, onSongClick = {}, onOpenOffline = ::openOfflineLibrary)
                }
                composable(Screen.Artists.route) {
                    ArtistsScreen(
                        onArtistClick = { artist -> navController.navigate("artist/${artist.id}") },
                        onBack = { navController.popBackStack() },
                    )
                }
                composable("albums") {
                    com.armonia.app.ui.library.AlbumsScreen(
                        onAlbumClick = { id -> navController.navigate("album/$id") },
                        onBack = { navController.popBackStack() },
                    )
                }
                composable(Screen.Downloads.route) {
                    DownloadsScreen()
                }
                composable(Screen.Offline.route) {
                    OfflineScreen()
                }
                composable(Screen.Settings.route) {
                    SettingsScreen(onLogout = { viewModel.logout {} })
                }

                composable("imports") { com.armonia.app.ui.playlists.ImportReviewScreen(
                    onBack={navController.popBackStack()},onInbox={navController.navigate("manual-inbox")}) }
                composable("manual-inbox") { com.armonia.app.ui.playlists.ManualInboxScreen(
                    onBack={navController.popBackStack()},onLibrary={navController.navigate("songs")}) }
                composable(Screen.Playlists.route) {
                    PlaylistsScreen(
                        onImport = { navController.navigate("imports") },
                        onPlaylistClick = { id -> navController.navigate("playlist/$id") },
                    )
                }
                composable(
                    route = "artist/{id}",
                    arguments = listOf(navArgument("id") { type = NavType.StringType }),
                ) {
                    ArtistDetailScreen(
                        onBack = { navController.popBackStack() },
                        onAlbumClick = { albumId -> navController.navigate("album/$albumId") },
                    )
                }
                composable(
                    route = "album/{id}",
                    arguments = listOf(navArgument("id") { type = NavType.StringType }),
                ) {
                    AlbumDetailScreen(
                        onBack = { navController.popBackStack() },
                    )
                }
                composable(
                    route = "playlist/{id}",
                    arguments = listOf(navArgument("id") { type = NavType.StringType }),
                ) {
                    PlaylistDetailScreen(
                        onBack = { navController.popBackStack() },
                        onAddSongs = { navController.navigate("playlist/${it.arguments?.getString("id")}/add") },
                    )
                }
                composable(
                    route = "playlist/{id}/add",
                    arguments = listOf(navArgument("id") { type = NavType.StringType }),
                ) { entry ->
                    // Shares the playlist screen's state, so what is added here is there on return.
                    val owner = remember(entry) { navController.getBackStackEntry("playlist/{id}") }
                    com.armonia.app.ui.playlists.AddSongsScreen(
                        onBack = { navController.popBackStack() },
                        viewModel = hiltViewModel(owner),
                    )
                }
                // YT Music exploration (distinct prefixes from local-library artist/album)
                composable(
                    route = "ytartist/{channelId}",
                    arguments = listOf(navArgument("channelId") { type = NavType.StringType }),
                ) {
                    YtArtistScreen(
                        onBack = { navController.popBackStack() },
                        onAlbumClick = { browseId -> navController.navigate("ytalbum/$browseId") },
                    )
                }
                composable(
                    route = "ytalbum/{browseId}",
                    arguments = listOf(navArgument("browseId") { type = NavType.StringType }),
                ) {
                    YtAlbumScreen(
                        onBack = { navController.popBackStack() },
                    )
                }
            }
        }
        }

        AnimatedVisibility(
            visible = expandedPlayerOpen,
            enter = slideInVertically(
                initialOffsetY = { it },
                animationSpec = tween(durationMillis = 300),
            ),
            exit = slideOutVertically(
                targetOffsetY = { it },
                animationSpec = tween(durationMillis = 300),
            ),
        ) {
            ExpandedPlayerScreen(
                onClose = { expandedPlayerOpen = false },
                onViewArtist = { artistId ->
                    expandedPlayerOpen = false
                    navController.navigate("artist/$artistId")
                },
            )
        }
    }

    if (moreSheetOpen) {
        MoreSheet(
            onDismiss = { moreSheetOpen = false },
            onNavigate = { route ->
                moreSheetOpen = false
                navController.navigate(route) {
                    popUpTo(navController.graph.findStartDestination().id) { saveState = true }
                    launchSingleTop = true
                    restoreState = true
                }
            },
        )
    }

    if (queueSheetOpen) {
        QueueSheet(onDismiss = { queueSheetOpen = false })
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MoreSheet(
    onDismiss: () -> Unit,
    onNavigate: (String) -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val vm: MainViewModel = hiltViewModel()
    var failures by remember { mutableStateOf(0) }
    LaunchedEffect(Unit) { failures = vm.failedDownloads() }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        containerColor = MaterialTheme.colorScheme.surface,
    ) {
        Column(modifier = Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(bottom = 16.dp)) {
            Text(
                text = "Mas",
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
            )
            MoreSection("Tu actividad")
            MoreRow(label = "Historial y estadisticas", icon = Icons.Default.BarChart, onClick = { onNavigate("listening") })
            MoreRow(label = "Pendientes de añadir", icon = Icons.Default.Add, onClick = { onNavigate("manual-inbox") })
            if (failures > 0) MoreRow(
                label = if (failures == 1) "1 descarga ha fallado" else "$failures descargas han fallado",
                icon = Icons.Default.Download, onClick = { onNavigate(Screen.Downloads.route) },
            )
            MoreSection("Cuenta y ajustes")
            MoreRow(label = "Ajustes y cuenta", icon = Icons.Default.Settings, onClick = { onNavigate(Screen.Settings.route) })
        }
    }
}

@Composable
private fun MoreSection(title: String) {
    Text(
        text = title.uppercase(),
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.55f),
        modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 18.dp, bottom = 6.dp),
    )
}

/** Biblioteca: one place for favourites, playlists, albums, artists, songs and what is kept on the phone. */
@Composable
private fun LibraryHome(tab: String, select: (String) -> Unit, onNavigate: (String) -> Unit) {
    var create by rememberSaveable { mutableStateOf(false) }
    val playlists: com.armonia.app.ui.playlists.PlaylistsViewModel = hiltViewModel()
    // Back from a detail (for example after deleting a mixed list): ask for the mixed lists again, not on the first visit.
    var returning by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(Unit) { if (returning) playlists.refreshMixed(); returning = true }
    Column(Modifier.fillMaxSize().statusBarsPadding()) {
        Text("Biblioteca", fontSize = 30.sp, fontWeight = FontWeight.ExtraBold, modifier = Modifier.padding(horizontal = 16.dp))
        Row(Modifier.padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            AssistChip(onClick = { create = true }, label = { Text("Nueva playlist") })
            AssistChip(onClick = { onNavigate("imports") }, label = { Text("Importar playlist") })
        }
        Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("Playlists", "Albumes", "Artistas", "Canciones", "En el telefono").forEach {
                FilterChip(selected = tab == it, onClick = { select(it) }, label = { Text(it) })
            }
        }
        when (tab) {
            "Playlists" -> PlaylistsScreen(onPlaylistClick = { onNavigate("playlist/$it") },
                onFavorites = { onNavigate("favorites") }, onMixed = { onNavigate("mixed/$it") }, viewModel = playlists)
            "Albumes" -> com.armonia.app.ui.library.AlbumsScreen({ onNavigate("album/$it") }, {}, embedded = true)
            "Artistas" -> ArtistsScreen({ onNavigate("artist/${it.id}") }, embedded = true)
            "Canciones" -> LibraryScreen(embedded = true, onSongClick = {}, onOpenOffline = { select("En el telefono") },
                onArtistClick = { onNavigate("ytartist/$it") })
            "En el telefono" -> OfflineScreen(embedded = true)
        }
    }
    if (create) com.armonia.app.ui.playlists.NameDialog(title = "Nueva playlist", confirmLabel = "Crear",
        initialName = "", onConfirm = { playlists.create(it); create = false; select("Playlists") }, onDismiss = { create = false })
}

@Composable
private fun MoreRow(
    label: String,
    icon: ImageVector,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
        )
        Spacer(Modifier.width(16.dp))
        Text(text = label, style = MaterialTheme.typography.bodyLarge)
    }
    HorizontalDivider(color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.06f))
}

