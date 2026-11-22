package com.armonia.app.ui.homelab

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import coil.compose.AsyncImage
import com.armonia.app.data.api.Artist
import com.armonia.app.data.repository.LibraryRepository
import com.armonia.app.homelab.*
import com.armonia.app.playback.MusicPlayer
import dagger.hilt.android.lifecycle.HiltViewModel
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import javax.inject.Inject
import kotlinx.coroutines.launch

@HiltViewModel
class ListeningViewModel @Inject constructor(val api: MusicApi, val search: com.armonia.app.data.api.ArmoniaApi, val library: LibraryRepository,
    val player: MusicPlayer, val outbox: ListenOutbox) : ViewModel()

private fun listenTime(seconds: Double): String {
    val minutes = seconds.toInt() / 60
    return if (minutes < 60) "$minutes min" else "${minutes / 60} h ${minutes % 60} min"
}

/** First and last day of the chart, as «21 oct», «17 nov 2025» or «nov 2025» (months for Siempre). */
private fun chartDate(iso: String?, period: String): String = iso?.let {
    val pattern = when (period) { "week", "month" -> "d MMM"; "year" -> "d MMM yyyy"; else -> "MMM yyyy" }
    LocalDate.parse(it).format(DateTimeFormatter.ofPattern(pattern, Locale.forLanguageTag("es")))
}.orEmpty()

private fun whenHeard(at: Long): String {
    val date = Instant.ofEpochSecond(at).atZone(ZoneId.systemDefault())
    val prefix = when (date.toLocalDate()) {
        LocalDate.now() -> "hoy "
        LocalDate.now().minusDays(1) -> "ayer "
        else -> ""
    }
    return prefix + date.format(DateTimeFormatter.ofPattern(if (prefix.isEmpty()) "d MMM" else "HH:mm", Locale.forLanguageTag("es")))
}

@Composable
fun ListeningScreen(open: (String) -> Unit, vm: ListeningViewModel = hiltViewModel()) {
    var period by rememberSaveable { mutableStateOf("month") }
    var kind by rememberSaveable { mutableStateOf("Artistas") }
    var retry by remember { mutableIntStateOf(0) }
    var failed by remember { mutableStateOf(false) }
    var data by remember(period) { mutableStateOf<ListeningSummary?>(null) }
    var directory by remember { mutableStateOf<Map<String, Artist>>(emptyMap()) }
    LaunchedEffect(Unit) {
        directory = vm.library.getArtists().getOrNull()?.artists?.index.orEmpty().flatMap { it.artist }.associateBy { it.name.lowercase() }
    }
    LaunchedEffect(period, retry) {
        failed = false
        try { data = vm.api.summary(period).checked() }
        catch (e: kotlinx.coroutines.CancellationException) { throw e }
        catch (_: Exception) { failed = true }
    }
    val scope = rememberCoroutineScope()
    var artistError by remember { mutableStateOf<String?>(null) }
    fun openArtist(name: String) {
        artistError = null
        directory[name.lowercase()]?.let { open("artist/${it.id}"); return }
        scope.launch {
            val result = runCatching { vm.search.search(com.armonia.app.data.api.SearchRequest(name)).body() }.getOrNull()
            val match = result?.artists.orEmpty().singleOrNull { it.name.equals(name, ignoreCase = true) }
            if (match != null) open("ytartist/${android.net.Uri.encode(match.channelId)}")
            else artistError = "No se ha encontrado la página de $name"
        }
    }
    val problem by vm.outbox.persistenceProblem.collectAsState()
    val accent = MaterialTheme.colorScheme.primary
    fun cover(track: MusicTrack, size: Int) = when (track.source) {
        "navidrome" -> vm.library.getCoverArtUrl(track.sourceId, size)
        "youtube" -> "https://i.ytimg.com/vi/${track.sourceId}/mqdefault.jpg"
        else -> null
    }
    val snapshot = data
    LazyColumn(Modifier.fillMaxSize().statusBarsPadding(), contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { Text("Historial y estadísticas", style = MaterialTheme.typography.headlineMedium) }
        artistError?.let { item { Text(it) } }
        problem?.let { item { Text(it, color = MaterialTheme.colorScheme.error) } }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                mapOf("week" to "Semana", "month" to "Mes", "year" to "Año", "always" to "Siempre").forEach { (id, label) ->
                    FilterChip(period == id, { period = id }, { Text(label) })
                }
            }
        }
        when {
            failed -> item { TextButton(onClick = { retry++ }) { Text("Reintentar carga de estadísticas") } }
            snapshot == null -> item { LinearProgressIndicator() }
            snapshot.count == 0 -> item { Text("Todavía no hay escuchas en este periodo") }
            else -> {
                item {
                    Column(Modifier.fillMaxWidth().background(Color(0xff4b298c), RoundedCornerShape(16.dp)).padding(18.dp)) {
                        Text(listenTime(snapshot.seconds), style = MaterialTheme.typography.displayLarge, color = Color.White)
                        Text("${snapshot.count} escuchas · ${snapshot.distinct} artistas", style = MaterialTheme.typography.headlineSmall, color = Color.White)
                        Spacer(Modifier.height(18.dp))
                        Canvas(Modifier.fillMaxWidth().height(88.dp)) {
                            val max = snapshot.series.maxOfOrNull { it.seconds }?.coerceAtLeast(1.0) ?: 1.0
                            val step = size.width / snapshot.series.size.coerceAtLeast(1)
                            snapshot.series.forEachIndexed { index, point ->
                                val h = (point.seconds / max * size.height).toFloat()
                                drawRect(Color(0xffd6baff), Offset(index * step, size.height - h), Size(step * .8f, h))
                            }
                        }
                        Text("${chartDate(snapshot.series.firstOrNull()?.date, period)} — ${chartDate(snapshot.series.lastOrNull()?.date, period)}",
                            color = Color.White)
                    }
                }
                snapshot.artists.firstOrNull()?.let { lead -> item {
                    val artist = directory[lead.name.lowercase()]
                    Column(Modifier.clickable { openArtist(lead.name) }) {
                        AsyncImage(artist?.coverArt?.let { vm.library.getCoverArtUrl(it, 500) } ?: cover(lead.track, 500),
                            null, Modifier.fillMaxWidth().height(160.dp).clip(RoundedCornerShape(16.dp)), contentScale = ContentScale.Crop)
                        Spacer(Modifier.height(8.dp))
                        Text("Artista n.º 1 · ${lead.name}", style = MaterialTheme.typography.headlineSmall)
                    }
                } }
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { listOf("Artistas", "Canciones", "Álbumes").forEach {
                        FilterChip(kind == it, { kind = it }, { Text(it) })
                    } }
                }
                val ranking = when (kind) { "Artistas" -> snapshot.artists; "Canciones" -> snapshot.songs; else -> snapshot.albums }
                itemsIndexed(ranking) { index, row ->
                    if (index == 0) Text("Top 5", style = MaterialTheme.typography.titleLarge)
                    if (index == 5) Text("Resto del ranking", style = MaterialTheme.typography.titleLarge)
                    ListItem(headlineContent = { Text("${index+1}. ${row.name}") },
                        leadingContent = { AsyncImage(cover(row.track, 128), null, Modifier.size(44.dp)) },
                        supportingContent = { Column {
                            Text("${listenTime(row.seconds)} · ${row.count} escuchas")
                            LinearProgressIndicator(progress = { (row.seconds / ranking.first().seconds).toFloat() }, color = accent,
                                trackColor = Color.Transparent, gapSize = 0.dp, drawStopIndicator = {})
                        } }, colors = ListItemDefaults.colors(containerColor = if (index < 5) MaterialTheme.colorScheme.secondaryContainer else Color.Transparent),
                        modifier = Modifier.clickable(enabled = kind == "Canciones" || kind == "Artistas") {
                            if (kind == "Canciones") vm.player.play(row.track.toSong()) else openArtist(row.name)
                        })
                }
                item { Text("Escuchado recientemente", style = MaterialTheme.typography.titleLarge) }
                items(snapshot.recent) { row -> ListItem(headlineContent = { Text(row.track.title) },
                    supportingContent = { Text("${row.track.artist} · ${whenHeard(row.at)}") },
                    modifier = Modifier.clickable { vm.player.play(row.track.toSong()) }) }
            }
        }
    }
}
