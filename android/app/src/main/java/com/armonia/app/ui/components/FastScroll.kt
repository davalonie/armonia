package com.armonia.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.text.Normalizer
import java.util.Locale
import kotlin.math.roundToInt

internal fun scrollInitial(value: String): String {
    val initial = value.trimStart().take(1).uppercase(Locale.ROOT)
    if (initial == "Ñ") return initial
    return Normalizer.normalize(initial, Normalizer.Form.NFD).firstOrNull()
        ?.takeIf { it.isLetter() }?.toString() ?: "#"
}

private val months = "ene feb mar abr may jun jul ago sep oct nov dic".split(" ")
internal fun scrollMonth(date: String?): String {
    val parts = date.orEmpty().take(10).split('-')
    val month = parts.getOrNull(1)?.toIntOrNull()?.let { months.getOrNull(it - 1) }
    return if (month == null) "—" else "$month ${parts.first()}"
}

@Composable
internal fun BoxScope.FastScroll(labels: List<String>, first: () -> Int, moving: Boolean,
                                headerCount: Int, jump: suspend (Int) -> Unit) {
    if (labels.size <= 50) return
    var visible by remember { mutableStateOf(false) }
    var target by remember(labels) { mutableStateOf<Int?>(null) }
    val scope = rememberCoroutineScope()
    val latestJump by rememberUpdatedState(jump)
    LaunchedEffect(moving, target != null) {
        if (moving || target != null) visible = true else { delay(1500); visible = false }
    }
    if (!visible) return
    BoxWithConstraints(Modifier.align(Alignment.CenterEnd).fillMaxHeight().width(88.dp)) {
        val thumb = 44.dp
        val travel = (maxHeight - thumb).coerceAtLeast(0.dp)
        val index = target ?: (first() - headerCount).coerceIn(labels.indices)
        Row(Modifier.align(Alignment.TopEnd).offset(y = travel * (index.toFloat() / labels.lastIndex)),
            verticalAlignment = Alignment.CenterVertically) {
            target?.let { Text(labels[it], Modifier.background(MaterialTheme.colorScheme.surfaceVariant,
                RoundedCornerShape(8.dp)).padding(4.dp), style = MaterialTheme.typography.labelSmall) }
            Box(Modifier.width(28.dp).height(thumb).pointerInput(labels, headerCount, travel) {
                var position = 0f
                var job: Job? = null
                detectVerticalDragGestures(
                    onDragStart = { position = (first() - headerCount).coerceIn(labels.indices).toFloat(); target = position.toInt() },
                    onDragCancel = { target = null }, onDragEnd = { target = null },
                ) { change, dy ->
                    change.consume()
                    position = (position + dy * labels.lastIndex / travel.toPx().coerceAtLeast(1f))
                        .coerceIn(0f, labels.lastIndex.toFloat())
                    val next = position.roundToInt()
                    if (next != target) {
                        target = next
                        job?.cancel()
                        job = scope.launch { latestJump(next + headerCount) }
                    }
                }
            }, contentAlignment = Alignment.CenterEnd) {
                Spacer(Modifier.width(7.dp).fillMaxHeight().background(MaterialTheme.colorScheme.primary, RoundedCornerShape(4.dp)))
            }
        }
    }
}
