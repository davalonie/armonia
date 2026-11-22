package com.armonia.app.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.armonia.app.ui.theme.ArmoniaTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Reported: pulling a song to queue it did nothing, the row did not even move. Fictitious rows. */
@RunWith(AndroidJUnit4::class)
class SwipeToQueueTest {
    @get:Rule val rule = createComposeRule()

    private val queued = mutableListOf<Int>()
    private val played = mutableListOf<Int>()
    private lateinit var list: LazyListState

    private fun show() = rule.setContent {
        ArmoniaTheme {
            list = rememberLazyListState()
            LazyColumn(Modifier.fillMaxSize(), state = list) {
                items(40) { row ->
                    SwipeToQueue(onQueue = { queued += row }) {
                        Box(Modifier.fillMaxWidth().height(72.dp).clickable { played += row }) { Text("Canción ficticia $row") }
                    }
                }
            }
        }
    }

    private fun left(row: Int) = rule.onNodeWithText("Canción ficticia $row").getUnclippedBoundsInRoot().left

    /** A finger: lands, creeps past the touch slop in small steps, then keeps going. */
    private fun pull(row: Int, distance: Float, release: Boolean = true) {
        rule.onNodeWithText("Canción ficticia $row").performTouchInput {
            down(Offset(40f, centerY))
            val steps = (distance / 6f).toInt()
            repeat(steps) { moveBy(Offset(6f, if (it % 2 == 0) 1f else -1f), delayMillis = 8) }
            if (release) up()
        }
        rule.waitForIdle()
    }

    @Test fun pullingARowFarEnoughQueuesThatSongOnceAndPlaysNothing() {
        show()
        pull(2, distance = with(rule.density) { 110.dp.toPx() })
        assertEquals(listOf(2), queued)
        assertTrue(played.isEmpty())
        assertEquals("the row springs back", left(1), left(2))
    }

    @Test fun theRowFollowsTheFingerWhileItIsPulled() {
        show()
        val before = left(3)
        pull(3, distance = with(rule.density) { 60.dp.toPx() }, release = false)
        assertTrue("moved with the finger: ${left(3)} from $before", left(3) > before + 20.dp)
        assertTrue("nothing is queued before letting go", queued.isEmpty())
        rule.onNodeWithText("Canción ficticia 3").performTouchInput { up() }
    }

    @Test fun aShortPullSpringsBackAndQueuesNothing() {
        show()
        pull(1, distance = with(rule.density) { 40.dp.toPx() })
        assertTrue(queued.isEmpty())
        assertTrue(played.isEmpty())
        assertEquals(left(0), left(1))
    }

    @Test fun aFingerTapStillPlaysTheRow() {
        show()
        rule.onNodeWithText("Canción ficticia 4").performTouchInput {
            down(center); moveBy(Offset(3f, 2f), delayMillis = 16); moveBy(Offset(-1f, 1f), delayMillis = 16); up()
        }
        rule.waitForIdle()
        assertEquals(listOf(4), played)
        assertTrue(queued.isEmpty())
    }

    @Test fun theListStillScrollsVertically() {
        show()
        rule.onNodeWithText("Canción ficticia 5").performTouchInput {
            down(center)
            repeat(60) { moveBy(Offset(if (it % 2 == 0) 1f else -1f, -12f), delayMillis = 8) }
            up()
        }
        rule.waitForIdle()
        assertTrue("scrolled: first visible ${list.firstVisibleItemIndex}", list.firstVisibleItemIndex > 2)
        assertTrue(queued.isEmpty())
        assertTrue(played.isEmpty())
    }
}
