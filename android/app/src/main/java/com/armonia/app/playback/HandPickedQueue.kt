package com.armonia.app.playback

/**
 * The queue works as in Spotify: songs queued by hand (swipe to the right, «Añadir a la cola»)
 * play right after the song playing, ahead of the rest of the list it was started from, and
 * among themselves in the order they were queued: the second one queued plays second. «Reproducir
 * a continuacion» puts its song first among them.
 *
 * Queue indices throughout. [order] is the order they play in: the queue itself, or the shuffle
 * order when shuffle is on (so with shuffle on, songs queued by hand are not shuffled either).
 */

/** The songs queued by hand that come right after [current], in the order they will play. */
fun handPickedRun(order: List<Int>, current: Int, handPicked: Set<Int>): List<Int> {
    val at = order.indexOf(current)
    if (at < 0) return emptyList()
    return order.drop(at + 1).takeWhile { it in handPicked }
}

/** Where a song queued by hand goes in a queue of [count] songs, and with shuffle on the new play order. */
class QueueInsert(val index: Int, val shuffleOrder: IntArray?)

fun planQueueInsert(
    order: List<Int>,
    current: Int,
    count: Int,
    handPicked: Set<Int>,
    next: Boolean,
    shuffle: Boolean,
): QueueInsert {
    if (count == 0) return QueueInsert(0, null)
    if (current !in order || order.size != count) return QueueInsert(count, null)
    val after = if (next) current else handPickedRun(order, current, handPicked).lastOrNull() ?: current
    val index = after + 1
    return QueueInsert(index, if (shuffle) orderWithNext(order, after, index) else null)
}

/**
 * «Añadir al final de la cola»: at [at] (the controller asks for the end of the queue, ahead of
 * suggestions still waiting), never before the song after [current]; with shuffle on, last in the
 * play order. It is not one of the songs queued by hand that come next.
 */
fun planQueueAppend(order: List<Int>, current: Int, count: Int, at: Int, shuffle: Boolean): QueueInsert {
    if (count == 0) return QueueInsert(0, null)
    val index = at.coerceIn((current + 1).coerceIn(0, count), count)
    if (!shuffle || order.size != count) return QueueInsert(index, null)
    return QueueInsert(index, (order.map { if (it >= index) it + 1 else it } + index).toIntArray())
}

/**
 * Songs queued by hand still to play, in the order they would play: as in Spotify they stay queued
 * when another list starts, right after its first song.
 */
fun handPickedUpcoming(order: List<Int>, current: Int, handPicked: Set<Int>): List<Int> {
    val at = order.indexOf(current)
    if (at < 0) return emptyList()
    return order.drop(at + 1).filter { it in handPicked }
}

/** [songs] with [carried] put right after [start] (the song that starts the new list). */
fun <T> withCarriedOver(songs: List<T>, start: Int, carried: List<T>): List<T> =
    songs.take(start + 1) + carried + songs.drop(start + 1)
