package com.armonia.app.ui.player

import org.junit.Assert.assertEquals
import org.junit.Test

class TrackSwipeTest {
    @Test fun thresholdDirectionFlingAndEdges() {
        fun step(dx: Int, speed: Int = 0, prev: Boolean = true, next: Boolean = true) =
            swipeStep(dx.toFloat(), 100f, speed.toFloat(), 900f, 10f, prev, next)
        assertEquals(0, step(4, 2000))
        assertEquals(0, step(-29))
        assertEquals(1, step(-30))
        assertEquals(-1, step(14, 1000))
        assertEquals(0, step(50, prev = false))
        assertEquals(0, step(-50, next = false))
    }
}
