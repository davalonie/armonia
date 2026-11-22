package com.armonia.app.ui.components

import org.junit.Assert.assertEquals
import org.junit.Test

class SwipeToQueueTest {
    @Test fun aSwipedRowFollowsTheFingerButStaysOnScreenAndNeverGoesLeft() {
        assertEquals(40f, swipeOffset(10f, 30f, limit = 100f))
        assertEquals(100f, swipeOffset(90f, 30f, limit = 100f))
        assertEquals(0f, swipeOffset(10f, -30f, limit = 100f))
    }
}
