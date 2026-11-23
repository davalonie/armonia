package com.armonia.app.ui.player

import org.junit.Assert.assertEquals
import org.junit.Test

class VisibleQueueTest {
    @Test fun historyIsHiddenAndRestoredInPlaybackOrder() {
        val ids = listOf("a", "b", "a", "c")
        val shuffled = listOf(2, 0, 3, 1)
        val start = visibleQueueRows(ids, shuffled, 2)
        assertEquals(listOf(2, 0, 3, 1), start.map { it.index })
        assertEquals(4, start.map { it.key }.distinct().size)
        assertEquals(start.drop(2), visibleQueueRows(ids, shuffled, 3))
        assertEquals(start.drop(1), visibleQueueRows(ids, shuffled, 0))
        assertEquals(listOf(2, 3), visibleQueueRows(ids, ids.indices.toList(), 2).map { it.index })
    }
}
