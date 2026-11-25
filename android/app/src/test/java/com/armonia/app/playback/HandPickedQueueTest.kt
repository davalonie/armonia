package com.armonia.app.playback

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import kotlin.random.Random

/**
 * A small model of the player's queue: song names in queue order, the shuffle order (or none),
 * the one playing and which were queued by hand, moved only through the same functions the
 * service uses (planQueueInsert, shuffledOrderStartingAt).
 */
class HandPickedQueueTest {
    private class Queue(songs: List<String>, var current: Int = 0) {
        val songs = songs.toMutableList()
        val handPicked = mutableSetOf<Int>()
        var shuffle: IntArray? = null

        val order: List<Int> get() = shuffle?.toList() ?: songs.indices.toList()

        /** What will play from the current song on, in order. */
        fun upcoming(): List<String> = order.drop(order.indexOf(current)).map { songs[it] }

        fun queue(song: String, next: Boolean = false) {
            val plan = planQueueInsert(order, current, songs.size, handPicked, next, shuffle != null)
            songs.add(plan.index, song)
            val moved = handPicked.map { if (it >= plan.index) it + 1 else it }
            handPicked.clear(); handPicked.addAll(moved); handPicked.add(plan.index)
            if (current >= plan.index) current++
            if (shuffle != null) shuffle = plan.shuffleOrder
        }

        fun advance() { current = order[order.indexOf(current) + 1] }

        fun shuffleOn(random: Random) {
            shuffle = shuffledOrderStartingAt(songs.size, current, random,
                next = handPickedRun(songs.indices.toList(), current, handPicked))
        }
    }

    private val playlist = listOf("1", "2", "3", "4", "5")

    @Test fun queuedSongsPlayNextInTheOrderTheyWereQueued() {
        val q = Queue(playlist)
        q.queue("A")
        assertEquals(listOf("1", "A", "2", "3", "4", "5"), q.upcoming())
        q.queue("B") // not first: second, behind A
        q.queue("C")
        assertEquals(listOf("1", "A", "B", "C", "2", "3", "4", "5"), q.upcoming())
    }

    @Test fun whileAQueuedSongPlaysTheNextOneQueuedGoesBehindTheOthers() {
        val q = Queue(playlist)
        q.queue("A"); q.queue("B")
        q.advance() // A playing
        assertEquals("A", q.songs[q.current])
        q.queue("C")
        assertEquals(listOf("A", "B", "C", "2", "3", "4", "5"), q.upcoming())
    }

    @Test fun onceTheQueuedSongsHavePlayedTheNextOneGoesRightAfterTheCurrentSong() {
        val q = Queue(playlist)
        q.queue("A")
        q.advance(); q.advance() // A, then 2 playing
        q.queue("B")
        assertEquals(listOf("2", "B", "3", "4", "5"), q.upcoming())
    }

    @Test fun playNextGoesFirstAndLaterQueuedSongsStillGoBehindAll() {
        val q = Queue(playlist)
        q.queue("A"); q.queue("B")
        q.queue("P", next = true)
        assertEquals(listOf("1", "P", "A", "B", "2", "3", "4", "5"), q.upcoming())
        q.queue("C")
        assertEquals(listOf("1", "P", "A", "B", "C", "2", "3", "4", "5"), q.upcoming())
    }

    @Test fun withShuffleOnQueuedSongsPlayNextInOrderAndTheRestKeepsItsTurn() {
        val q = Queue(playlist, current = 2)
        q.shuffleOn(Random(7))
        val before = q.upcoming()
        q.queue("A"); q.queue("B")
        assertEquals(listOf("3", "A", "B") + before.drop(1), q.upcoming())
        q.advance() // A playing
        q.queue("C")
        assertEquals(listOf("A", "B", "C") + before.drop(1), q.upcoming())
    }

    @Test fun turningShuffleOnKeepsTheQueuedSongsNext() {
        val q = Queue(playlist, current = 1)
        q.queue("A"); q.queue("B")
        repeat(20) { seed ->
            q.shuffleOn(Random(seed))
            val upcoming = q.upcoming()
            assertEquals(listOf("2", "A", "B"), upcoming.take(3))
            assertEquals(setOf("1", "3", "4", "5"), upcoming.drop(3).toSet())
        }
    }

    @Test fun suggestionsAndTheRestOfTheListAreNotQueuedByHand() {
        assertEquals(listOf(1, 2), handPickedRun(listOf(0, 1, 2, 3, 4), 0, setOf(1, 2, 4)))
        assertEquals(emptyList<Int>(), handPickedRun(listOf(0, 1, 2), 9, setOf(1)))
    }

    @Test fun anEmptyOrInconsistentQueueIsAppendedToWithoutAShuffleOrder() {
        val empty = planQueueInsert(emptyList(), -1, 0, emptySet(), next = false, shuffle = true)
        assertEquals(0, empty.index); assertNull(empty.shuffleOrder)
        val odd = planQueueInsert(listOf(0, 1), 5, 3, emptySet(), next = false, shuffle = true)
        assertEquals(3, odd.index); assertNull(odd.shuffleOrder)
    }

    @Test fun theShuffleOrderStaysAPermutationOfTheWholeQueue() {
        val plan = planQueueInsert(listOf(3, 0, 4, 1, 2), 0, 5, setOf(4), next = false, shuffle = true)
        assertEquals(5, plan.index)
        assertArrayEquals(intArrayOf(3, 0, 4, 5, 1, 2), plan.shuffleOrder)
    }
    @Test fun atTheEndGoesAfterTheWholeListAndIsNotQueuedNext() {
        val plain = planQueueAppend(listOf(0, 1, 2, 3), current = 1, count = 4, at = 4, shuffle = false)
        assertEquals(4, plain.index); assertNull(plain.shuffleOrder)
        // Ahead of two suggestions still waiting (indices 2 and 3), never before the next song.
        assertEquals(2, planQueueAppend(listOf(0, 1, 2, 3), 1, 4, at = 2, shuffle = false).index)
        assertEquals(2, planQueueAppend(listOf(0, 1, 2, 3), 1, 4, at = 0, shuffle = false).index)
        val shuffled = planQueueAppend(listOf(2, 0, 3, 1), current = 2, count = 4, at = 4, shuffle = true)
        assertArrayEquals(intArrayOf(2, 0, 3, 1, 4), shuffled.shuffleOrder)
        val q = Queue(listOf("1", "2", "3"))
        q.queue("A")
        val end = planQueueAppend(q.order, q.current, q.songs.size, q.songs.size, false)
        q.songs.add(end.index, "Z")
        q.queue("B") // still behind A, not behind Z
        assertEquals(listOf("1", "A", "B", "2", "3", "Z"), q.upcoming())
    }

    @Test fun queuedSongsStillToPlayCarryOverToANewListAfterItsFirstSong() {
        val q = Queue(playlist)
        q.queue("A"); q.queue("B")
        q.advance() // A playing: only B is still to play
        val carried = handPickedUpcoming(q.order, q.current, q.handPicked).map { q.songs[it] }
        assertEquals(listOf("B"), carried)
        assertEquals(listOf("x", "B", "y", "z"), withCarriedOver(listOf("x", "y", "z"), 0, carried))
        assertEquals(listOf("x", "y", "B", "z"), withCarriedOver(listOf("x", "y", "z"), 1, carried))
        // With shuffle, in the order they would have played; moved further down by hand, still kept.
        assertEquals(listOf(4, 1), handPickedUpcoming(listOf(0, 4, 2, 1, 3), 0, setOf(1, 4)))
        assertEquals(emptyList<Int>(), handPickedUpcoming(listOf(0, 1), 1, setOf(0)))
    }

    @Test
    fun `with shuffle on a song moves in the play order and the queue stays as it is`() {
        // Queue a b c d e playing in the order c a e b d (queue indices 2 0 4 1 3)
        val order = listOf(2, 0, 4, 1, 3)
        // e (index 4), third to play, dragged down to where d (index 3) is: last
        assertArrayEquals(intArrayOf(2, 0, 1, 3, 4), moveInPlayOrder(order, item = 4, target = 3))
        // d dragged up to where a is: right after the song playing
        assertArrayEquals(intArrayOf(2, 3, 0, 4, 1), moveInPlayOrder(order, item = 3, target = 0))
        // Nothing to move
        assertNull(moveInPlayOrder(order, item = 1, target = 1))
        assertNull(moveInPlayOrder(order, item = 7, target = 1))
    }
}
