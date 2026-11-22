package com.armonia.app.playback
import org.junit.Assert.assertArrayEquals
import org.junit.Test
class PlayNextOrderTest {
    @Test fun preservesShuffledOrderAndInsertsAfterCurrent() {
        assertArrayEquals(intArrayOf(2,0,1,3),orderWithNext(listOf(1,0,2),0,1))
    }
    @Test fun emptyQueueNeverNeedsAnAutoplayOperation() {
        assertArrayEquals(intArrayOf(0),orderWithNext(emptyList(),-1,0))
    }
}
