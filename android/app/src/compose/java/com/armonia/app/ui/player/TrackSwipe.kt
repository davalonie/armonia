package com.armonia.app.ui.player

import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.util.VelocityTracker
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.armonia.app.playback.MusicPlayer
import kotlin.math.abs

internal fun swipeStep(offset: Float, width: Float, velocity: Float, fling: Float,
                       minimum: Float, previous: Boolean, next: Boolean): Int {
    if (width <= 0 || abs(offset) < minimum) return 0
    if (abs(offset) / width < .3f && (abs(velocity) < fling || velocity * offset <= 0)) return 0
    return when {
        offset < 0 && next -> 1
        offset > 0 && previous -> -1
        else -> 0
    }
}

internal fun Modifier.trackSwipe(player: MusicPlayer, id: String): Modifier = composed {
    var drag by remember(id) { mutableFloatStateOf(0f) }
    semantics {
        customActions = listOf(CustomAccessibilityAction("Siguiente") { player.step(1) },
            CustomAccessibilityAction("Anterior") { player.step(-1) })
    }.pointerInput(player, id) {
        val velocity = VelocityTracker()
        detectHorizontalDragGestures(
            onDragStart = { velocity.resetTracking(); drag = 0f },
            onDragCancel = { drag = 0f },
            onDragEnd = {
                val step = swipeStep(drag, size.width.toFloat(), velocity.calculateVelocity().x,
                    900.dp.toPx(), 10.dp.toPx(), player.canStep(-1), player.canStep(1))
                if (step != 0) player.step(step)
                drag = 0f
            },
        ) { change, dx ->
            velocity.addPosition(change.uptimeMillis, change.position)
            change.consume()
            drag = (drag + dx).coerceIn(-size.width.toFloat(), size.width.toFloat())
        }
    }.graphicsLayer { translationX = drag }
}
