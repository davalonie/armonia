package com.armonia.app.ui.components

import androidx.compose.animation.core.animate
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.QueueMusic
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import kotlin.math.roundToInt

/** How far a row must be pulled before letting go queues the song. */
const val SWIPE_TO_QUEUE_THRESHOLD_DP = 72

/** Where a swipe ends up: the row follows the finger, with a stop so it never leaves the screen. */
fun swipeOffset(current: Float, delta: Float, limit: Float): Float = (current + delta).coerceIn(0f, limit)

/**
 * Pull a song row to the right and let go: it is added to the queue, as in Spotify after the song
 * playing and the songs already queued by hand (playback/HandPickedQueue). Nothing starts playing
 * and the queue is not replaced. The row follows the finger, says what letting go will do, and
 * ticks once when it has been pulled far enough; a short pull springs back and does nothing.
 *
 * The outer box owns the gesture and stays put; the inner one slides. A gesture read on the node
 * that moves sees the finger standing still. Nothing is consumed before the horizontal touch
 * slop, so taps on the row and vertical scrolling of the list work as before.
 */
@Composable
fun SwipeToQueue(
    onQueue: () -> Unit,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    val density = LocalDensity.current
    val threshold = with(density) { SWIPE_TO_QUEUE_THRESHOLD_DP.dp.toPx() }
    val limit = with(density) { 132.dp.toPx() }
    var offset by remember { mutableFloatStateOf(0f) }
    var armed by remember { mutableStateOf(false) }
    val haptics = LocalHapticFeedback.current
    Box(
        modifier
            .draggable(
                orientation = Orientation.Horizontal,
                state = rememberDraggableState { delta ->
                    offset = swipeOffset(offset, delta, limit)
                    val far = offset >= threshold
                    if (far != armed) {
                        armed = far
                        if (far) haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                    }
                },
                onDragStopped = {
                    if (armed) onQueue()
                    armed = false
                    animate(initialValue = offset, targetValue = 0f) { value, _ -> offset = value }
                },
            )
            .semantics {
                customActions = listOf(CustomAccessibilityAction("Añadir a la cola") { onQueue(); true })
            }
            .testTag("swipe-to-queue"),
    ) {
        if (offset > 0f) {
            Row(
                Modifier
                    .matchParentSize()
                    .background(MaterialTheme.colorScheme.primary.copy(alpha = if (armed) 0.30f else 0.12f))
                    .padding(start = 20.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.AutoMirrored.Filled.QueueMusic, null, tint = MaterialTheme.colorScheme.primary)
                if (offset > threshold * 0.6f) {
                    Spacer(Modifier.width(8.dp))
                    Text(
                        if (armed) "Suelta" else "A la cola",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.primary,
                        maxLines = 1,
                    )
                }
            }
        }
        Box(
            Modifier
                .offset { IntOffset(offset.roundToInt(), 0) }
                .then(if (offset > 0f) Modifier.background(MaterialTheme.colorScheme.background) else Modifier),
        ) { content() }
    }
}
