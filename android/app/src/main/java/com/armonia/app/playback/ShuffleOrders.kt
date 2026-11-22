package com.armonia.app.playback

import kotlin.random.Random

/**
 * A random play order over [count] items that starts at [current], so enabling shuffle
 * mid-queue plays every other track exactly once instead of stopping wherever the
 * current track happened to land in a blind permutation. The songs queued by hand that
 * were coming next ([next], see HandPickedQueue) keep coming next, in their order.
 */
fun shuffledOrderStartingAt(count: Int, current: Int, random: Random = Random, next: List<Int> = emptyList()): IntArray {
    if (count <= 0) return IntArray(0)
    val start = current.coerceIn(0, count - 1)
    val kept = next.filter { it in 0 until count && it != start }.distinct()
    val rest = (0 until count).filter { it != start && it !in kept }.shuffled(random)
    return (listOf(start) + kept + rest).toIntArray()
}

/** Preserve the existing traversal, inserting [inserted] (a new queue index) to play right after [after]. */
fun orderWithNext(order: List<Int>, after: Int, inserted: Int): IntArray {
    val adjusted = order.map { if (it >= inserted) it + 1 else it }.toMutableList()
    val afterAdjusted = if (after >= inserted) after + 1 else after
    adjusted.add((adjusted.indexOf(afterAdjusted) + 1).coerceAtLeast(0), inserted)
    return adjusted.toIntArray()
}
