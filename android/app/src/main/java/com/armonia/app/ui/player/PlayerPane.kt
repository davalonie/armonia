package com.armonia.app.ui.player

import androidx.compose.animation.core.animate
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.Orientation
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsDraggedAsState
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.PlaylistAdd
import androidx.compose.material.icons.automirrored.filled.QueueMusic
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Repeat
import androidx.compose.material.icons.filled.RepeatOne
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material.icons.outlined.FavoriteBorder
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.paneTitle
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.armonia.app.playback.PlaybackProgress
import com.armonia.app.playback.RepeatMode
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * A full-screen layer drawn over other content. A background alone does not take touches in
 * Compose: without this, a tap on the cover or on an empty area reached the screen underneath.
 *
 * Being a pointer target is what stops them: once this layer is hit, what lies under it is not
 * offered the touch. It must NOT consume anything. A button gives up its tap when it finds a
 * movement consumed, and a real finger always moves a little between landing and lifting, so
 * a version that consumed every event left the whole player dead on a phone (0.4.4) while
 * synthetic taps, which do not move, kept working.
 */
fun Modifier.blocksTouchesBehind(): Modifier = pointerInput(Unit) { }

/**
 * What lies under the expanded player. While the player is [covered] over it, it is not there for
 * a screen reader either: its buttons cannot take accessibility focus through the player.
 */
@Composable
fun UnderPlayer(covered: Boolean, content: @Composable () -> Unit) {
    Box(Modifier.fillMaxSize().then(if (covered) Modifier.clearAndSetSemantics { } else Modifier)) { content() }
}

fun formatPlaybackTime(ms: Long): String {
    if (ms <= 0L) return "0:00"
    val totalSec = ms / 1000
    val h = totalSec / 3600
    val m = (totalSec % 3600) / 60
    val s = totalSec % 60
    return if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%d:%02d".format(m, s)
}

/** What the expanded player shows. [liked] is null while unknown or when the song cannot be saved (external source). */
data class PlayerPaneState(
    val title: String,
    val artist: String,
    val context: String? = null,
    val automatic: Boolean = false,
    val playing: Boolean = false,
    val buffering: Boolean = false,
    val liked: Boolean? = false,
    val shuffle: Boolean = false,
    val repeat: RepeatMode = RepeatMode.OFF,
    val canAddToPlaylist: Boolean = true,
)

class PlayerPaneActions(
    val minimize: () -> Unit = {},
    val menu: () -> Unit = {},
    val playPause: () -> Unit = {},
    val previous: () -> Unit = {},
    val next: () -> Unit = {},
    val shuffle: () -> Unit = {},
    val repeat: () -> Unit = {},
    val like: () -> Unit = {},
    val seek: (Float) -> Unit = {},
    val queue: () -> Unit = {},
    val addToPlaylist: () -> Unit = {},
)

/**
 * The expanded player without its data sources, so it can be laid over anything and tested.
 * [progress] is read only by the seek bar: a position tick redraws the bar, not the cover or backdrop.
 */
@Composable
fun PlayerPane(
    state: PlayerPaneState,
    progress: () -> PlaybackProgress,
    actions: PlayerPaneActions,
    modifier: Modifier = Modifier,
    backdrop: @Composable BoxScope.() -> Unit = {},
    menu: @Composable () -> Unit = {},
    cover: @Composable (Modifier) -> Unit,
) {
    // Registered when the player opens, so after the navigation of the screen underneath:
    // the newest handler wins, and Back closes the player instead of going back behind it.
    BackHandler(onBack = actions.minimize)
    // Plain state written synchronously by the gesture: the release decides with the distance
    // really travelled, not with whatever queued updates had run by then.
    var pull by remember { mutableFloatStateOf(0f) }
    val dismissAt = with(LocalDensity.current) { 120.dp.toPx() }
    // Two boxes on purpose. The outer one stays put and owns the gesture; the inner one is what
    // slides. With both on one node the pane moved under the finger, the finger looked still to
    // the gesture, and a slow pull travelled half the distance and never reached the threshold.
    Box(
        modifier = modifier
            .fillMaxSize()
            .draggable(
                orientation = Orientation.Vertical,
                state = rememberDraggableState { delta -> pull = (pull + delta).coerceAtLeast(0f) },
                onDragStopped = { velocity ->
                    if (pull > dismissAt || velocity > 1600f) actions.minimize()
                    else animate(initialValue = pull, targetValue = 0f) { value, _ -> pull = value }
                },
            )
            .blocksTouchesBehind()
            .semantics { paneTitle = "Reproductor" }
            .testTag("player-pane"),
    ) {
      Box(Modifier.fillMaxSize().graphicsLayer { translationY = pull }.background(Color(0xFF0D0B10))) {
        backdrop()
        // Readable on any cover: light at the top, nearly opaque where the controls sit.
        Box(
            Modifier.fillMaxSize().background(
                Brush.verticalGradient(
                    0f to Color.Black.copy(alpha = 0.35f),
                    0.45f to Color.Black.copy(alpha = 0.55f),
                    1f to Color.Black.copy(alpha = 0.88f),
                )
            )
        )
        Column(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .navigationBarsPadding()
                .padding(horizontal = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = actions.minimize, modifier = Modifier.offset(x = (-12).dp)) {
                    Icon(Icons.Default.KeyboardArrowDown, "Minimizar el reproductor", tint = Color.White, modifier = Modifier.size(30.dp))
                }
                Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(
                        text = when {
                            state.automatic -> "CONTINUACIÓN AUTOMÁTICA"
                            state.context != null -> "REPRODUCIENDO DESDE"
                            else -> "REPRODUCIENDO"
                        },
                        color = Color.White.copy(alpha = 0.7f),
                        fontSize = 11.sp,
                        fontWeight = FontWeight.SemiBold,
                        letterSpacing = 1.sp,
                        maxLines = 1,
                    )
                    val detail = if (state.automatic) "Música similar" else state.context
                    if (detail != null) Text(
                        text = detail,
                        color = Color.White,
                        fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        textAlign = TextAlign.Center,
                    )
                }
                Box(Modifier.offset(x = 12.dp)) {
                    IconButton(onClick = actions.menu) {
                        Icon(Icons.Default.MoreVert, "Más opciones", tint = Color.White)
                    }
                    menu()
                }
            }

            // The cover takes whatever height the controls leave: it shrinks on a small
            // screen or with large text instead of pushing the controls off the screen.
            BoxWithConstraints(
                modifier = Modifier.weight(1f).fillMaxWidth().padding(vertical = 16.dp),
                contentAlignment = Alignment.Center,
            ) {
                val side = minOf(maxWidth, maxHeight)
                if (side >= 96.dp) cover(
                    Modifier
                        .size(side)
                        .clip(RoundedCornerShape(14.dp))
                        .background(Color.White.copy(alpha = 0.06f))
                        .testTag("player-cover")
                )
            }

            Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = state.title,
                        color = Color.White,
                        fontSize = 22.sp,
                        lineHeight = 27.sp,
                        fontWeight = FontWeight.Bold,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        text = state.artist,
                        color = Color.White.copy(alpha = 0.72f),
                        fontSize = 15.sp,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.padding(top = 2.dp),
                    )
                }
                if (state.canAddToPlaylist) SavedButton(state.liked, actions.addToPlaylist)
            }

            Spacer(Modifier.height(10.dp))
            SeekBar(progress = progress, onSeek = actions.seek)

            Spacer(Modifier.height(8.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                ModeButton(Icons.Default.Shuffle, "Aleatorio", if (state.shuffle) "Activado" else "Desactivado", state.shuffle, actions.shuffle)
                IconButton(onClick = actions.previous, modifier = Modifier.size(56.dp)) {
                    Icon(Icons.Default.SkipPrevious, "Anterior", tint = Color.White, modifier = Modifier.size(38.dp))
                }
                Box(contentAlignment = Alignment.Center, modifier = Modifier.size(80.dp)) {
                    if (state.buffering) CircularProgressIndicator(
                        modifier = Modifier.fillMaxSize().semantics { contentDescription = "Cargando" },
                        color = MaterialTheme.colorScheme.primary,
                        strokeWidth = 3.dp,
                    )
                    FilledIconButton(
                        onClick = actions.playPause,
                        modifier = Modifier.size(68.dp),
                        colors = IconButtonDefaults.filledIconButtonColors(
                            containerColor = MaterialTheme.colorScheme.primary,
                            contentColor = Color.Black,
                        ),
                    ) {
                        Icon(
                            imageVector = if (state.playing) Icons.Default.Pause else Icons.Default.PlayArrow,
                            contentDescription = if (state.playing) "Pausar" else "Reproducir",
                            modifier = Modifier.size(36.dp),
                        )
                    }
                }
                IconButton(onClick = actions.next, modifier = Modifier.size(56.dp)) {
                    Icon(Icons.Default.SkipNext, "Siguiente", tint = Color.White, modifier = Modifier.size(38.dp))
                }
                ModeButton(
                    icon = if (state.repeat == RepeatMode.ONE) Icons.Default.RepeatOne else Icons.Default.Repeat,
                    label = "Repetir",
                    stateLabel = when (state.repeat) {
                        RepeatMode.OFF -> "Desactivado"
                        RepeatMode.ONE -> "Esta canción"
                        RepeatMode.ALL -> "Toda la cola"
                    },
                    active = state.repeat != RepeatMode.OFF,
                    onClick = actions.repeat,
                )
            }

            Row(
                modifier = Modifier.fillMaxWidth().padding(top = 4.dp, bottom = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Spacer(Modifier.weight(1f))
                TextButton(onClick = actions.queue, modifier = Modifier.offset(x = 12.dp)) {
                    Icon(Icons.AutoMirrored.Filled.QueueMusic, null, tint = Color.White.copy(alpha = 0.8f))
                    Spacer(Modifier.width(8.dp))
                    Text("Cola", color = Color.White.copy(alpha = 0.8f))
                }
            }
        }
      }
    }
}

/** Shuffle / repeat: accent colour and a dot when on, and the state spoken by the screen reader. */
@Composable
internal fun ModeButton(icon: ImageVector, label: String, stateLabel: String, active: Boolean, onClick: () -> Unit) {
    IconButton(onClick = onClick, modifier = Modifier.semantics { stateDescription = stateLabel }) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(icon, label, tint = if (active) MaterialTheme.colorScheme.primary else Color.White.copy(alpha = 0.7f))
            Box(
                Modifier.padding(top = 2.dp).size(4.dp)
                    .background(if (active) MaterialTheme.colorScheme.primary else Color.Transparent, CircleShape)
            )
        }
    }
}

/**
 * Thin progress line with a 44 dp touch target. Dragging only moves the thumb and the time
 * label; the player seeks once, on release. The lighter stretch is what is already buffered.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SeekBar(progress: () -> PlaybackProgress, onSeek: (Float) -> Unit, modifier: Modifier = Modifier) {
    val now = progress()
    val duration = now.durationMs
    var dragged by remember { mutableStateOf<Float?>(null) }
    // After release the old position would flash until the player reports the new one.
    var settling by remember { mutableStateOf<Float?>(null) }
    LaunchedEffect(settling) { if (settling != null) { delay(1500); settling = null } }
    val real = if (duration > 0) (now.positionMs.toFloat() / duration).coerceIn(0f, 1f) else 0f
    val shown = dragged ?: settling ?: real
    val buffered = if (duration > 0) (now.bufferedMs.toFloat() / duration).coerceIn(0f, 1f) else 0f
    val interaction = remember { MutableInteractionSource() }
    val held = interaction.collectIsDraggedAsState().value || interaction.collectIsPressedAsState().value
    val thumb by animateDpAsState(if (held || dragged != null) 18.dp else 12.dp, label = "thumb")
    val shownMs = (shown * duration).toLong()

    Column(modifier.fillMaxWidth()) {
        Slider(
            value = shown,
            onValueChange = { dragged = it },
            onValueChangeFinished = {
                dragged?.let { settling = it; onSeek(it) }
                dragged = null
            },
            enabled = duration > 0,
            interactionSource = interaction,
            modifier = Modifier
                .fillMaxWidth()
                .height(44.dp)
                .semantics {
                    contentDescription = "Posición en la canción"
                    stateDescription = "${formatPlaybackTime(shownMs)} de ${formatPlaybackTime(duration)}"
                }
                .testTag("player-seek"),
            thumb = {
                Box(Modifier.size(20.dp), contentAlignment = Alignment.Center) {
                    Box(Modifier.size(thumb).background(Color.White, CircleShape))
                }
            },
            track = {
                Canvas(Modifier.fillMaxWidth().height(4.dp)) {
                    val radius = CornerRadius(size.height / 2)
                    drawRoundRect(Color.White.copy(alpha = 0.22f), size = size, cornerRadius = radius)
                    if (buffered > shown) drawRoundRect(
                        Color.White.copy(alpha = 0.38f), topLeft = Offset.Zero,
                        size = Size(size.width * buffered, size.height), cornerRadius = radius,
                    )
                    drawRoundRect(Color.White, size = Size(size.width * shown, size.height), cornerRadius = radius)
                }
            },
        )
        Row(Modifier.fillMaxWidth().offset(y = (-6).dp)) {
            Text(
                formatPlaybackTime(shownMs),
                color = if (dragged != null) Color.White else Color.White.copy(alpha = 0.7f),
                fontSize = 12.sp,
                fontWeight = if (dragged != null) FontWeight.SemiBold else FontWeight.Normal,
            )
            Spacer(Modifier.weight(1f))
            Text(formatPlaybackTime(duration), color = Color.White.copy(alpha = 0.7f), fontSize = 12.sp)
        }
    }
}
