package com.armonia.app.ui.player

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Button
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.click
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.longClick
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.TouchInjectionScope
import androidx.compose.ui.test.swipeDown
import androidx.compose.ui.test.swipeLeft
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.armonia.app.playback.PlaybackProgress
import com.armonia.app.playback.RepeatMode
import com.armonia.app.ui.theme.ArmoniaTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Reported: with the expanded player open, touching it acted on the screen behind.
 *
 * The screen behind is a fictitious one whose every pixel is an action that counts its taps
 * (a full-screen target plus rows and a favourite button, like a playlist); no account data.
 */
@RunWith(AndroidJUnit4::class)
class PlayerPaneTouchTest {
    @get:Rule val rule = createComposeRule()

    private var behind = 0
    private var behindBack = 0
    private val calls = mutableMapOf<String, Int>()
    private var seeks = mutableListOf<Float>()
    private var open by mutableStateOf(true)

    private fun count(name: String): () -> Unit = { calls[name] = (calls[name] ?: 0) + 1 }

    private fun show(overlay: @androidx.compose.runtime.Composable () -> Unit = { pane() }) {
        rule.setContent {
            ArmoniaTheme {
                Box(Modifier.fillMaxSize()) {
                    UnderPlayer(covered = open) {
                        // Like the navigation of the real screen: Back there leaves the screen.
                        androidx.activity.compose.BackHandler { behindBack++ }
                        Box(Modifier.fillMaxSize().clickable { behind++ }) {
                            Column(Modifier.fillMaxSize()) {
                                repeat(12) { row ->
                                    Box(Modifier.fillMaxWidth().height(64.dp).clickable { behind++ }) {
                                        Text("Canción ficticia $row")
                                        IconButton(onClick = { behind++ }) { Text("♥") }
                                    }
                                }
                                Button(onClick = { behind++ }) { Text("Acción de detrás") }
                            }
                        }
                    }
                    if (open) overlay()
                }
            }
        }
    }

    @androidx.compose.runtime.Composable
    private fun pane() = PlayerPane(
        state = PlayerPaneState(
            title = "Título de laboratorio", artist = "Artista ficticio", context = "Lista de prueba",
            playing = true, liked = false, shuffle = false, repeat = RepeatMode.OFF,
        ),
        progress = { PlaybackProgress(30_000, 180_000, 90_000) },
        actions = PlayerPaneActions(
            minimize = count("minimize"), menu = count("menu"), playPause = count("playPause"),
            previous = count("previous"), next = count("next"), shuffle = count("shuffle"),
            repeat = count("repeat"), like = count("like"), seek = { seeks += it },
            queue = count("queue"), addToPlaylist = count("addToPlaylist"),
        ),
        cover = { Box(it.background(Color(0xFF8E5BD6))) },
    )

    /** Taps on a grid over the whole screen: cover, gaps, edges and corners included. */
    private fun tapEverywhere() {
        rule.onRoot().performTouchInput {
            for (ix in 0..8) for (iy in 0..17) {
                click(Offset(1f + (width - 2f) * ix / 8f, 1f + (height - 2f) * iy / 17f))
            }
        }
        rule.waitForIdle()
    }

    /**
     * A tap as a finger makes it: it never lifts exactly where it landed. A synthetic click has
     * no movement at all, and that hid a player whose controls ignored every real tap.
     */
    private fun TouchInjectionScope.fingerTap(at: Offset = center) {
        down(at)
        moveBy(Offset(3f, 2f), delayMillis = 16)
        moveBy(Offset(-1f, 2f), delayMillis = 16)
        moveBy(Offset(1f, -1f), delayMillis = 16)
        up()
    }

    private fun fingerTapEverywhere() {
        rule.onRoot().performTouchInput {
            for (ix in 0..8) for (iy in 0..17) {
                fingerTap(Offset(6f + (width - 12f) * ix / 8f, 6f + (height - 12f) * iy / 17f))
            }
        }
        rule.waitForIdle()
    }

    @Test fun theFictitiousScreenIsReachableWithoutThePlayer() {
        open = false
        show()
        tapEverywhere()
        assertTrue("positive control: the taps must reach the screen when nothing covers it", behind > 100)
    }

    /** The defect as it was: the old player was a full-screen box with only a background. */
    @Test fun aFullScreenBackgroundAloneLetsTapsThrough() {
        show(overlay = {
            Box(Modifier.fillMaxSize().background(Color.Black)) {
                Column { Text("Portada"); Text("Título") }
            }
        })
        tapEverywhere()
        assertTrue("reproduction: a plain background does not take the touches", behind > 100)
    }

    @Test fun noTapOnThePlayerReachesTheScreenBehind() {
        show()
        tapEverywhere()
        assertEquals(0, behind)
    }

    @Test fun pressesAndSwipesOnTheCoverDoNotReachTheScreenBehind() {
        show()
        rule.onNodeWithTag("player-cover").performTouchInput { click(center) }
        rule.onNodeWithTag("player-cover").performTouchInput { longClick(center) }
        rule.onNodeWithTag("player-cover").performTouchInput { swipeLeft() }
        rule.onNodeWithText("Título de laboratorio").performTouchInput { click(center) }
        rule.waitForIdle()
        assertEquals(0, behind)
        assertTrue("the cover and the title are not buttons", calls.isEmpty())
    }

    @Test fun eachControlRunsItsOwnActionExactlyOnce() {
        show()
        listOf(
            "Pausar" to "playPause", "Anterior" to "previous", "Siguiente" to "next", "Aleatorio" to "shuffle",
            "Repetir" to "repeat", "Guardar en playlists" to "addToPlaylist",
            "Más opciones" to "menu", "Minimizar el reproductor" to "minimize",
        ).forEach { (label, action) ->
            rule.onNodeWithContentDescription(label).performClick()
            rule.waitForIdle()
            assertEquals("$label → $action", 1, calls[action])
        }
        rule.onNodeWithText("Cola").performClick()
        rule.waitForIdle()
        assertEquals(1, calls["queue"])
        assertEquals("one tap, one action", 10, calls.values.sum())
        assertEquals(0, behind)
    }

    /** Reported on the phone after 0.4.4: the player looked like a still image. */
    @Test fun aRealFingerTapRunsEachControlExactlyOnce() {
        show()
        listOf(
            "Pausar" to "playPause", "Anterior" to "previous", "Siguiente" to "next", "Aleatorio" to "shuffle",
            "Repetir" to "repeat", "Guardar en playlists" to "addToPlaylist",
            "Más opciones" to "menu", "Minimizar el reproductor" to "minimize",
        ).forEach { (label, action) ->
            rule.onNodeWithContentDescription(label).performTouchInput { fingerTap() }
            rule.waitForIdle()
            assertEquals("$label → $action", 1, calls[action])
        }
        rule.onNodeWithText("Cola").performTouchInput { fingerTap() }
        rule.waitForIdle()
        assertEquals(1, calls["queue"])
        assertEquals("one tap, one action", 10, calls.values.sum())
        assertEquals(0, behind)
    }

    @Test fun realFingerTapsDoNotReachTheScreenBehindEither() {
        show()
        fingerTapEverywhere()
        assertEquals(0, behind)
    }

    @Test fun realFingerTapsReachTheFictitiousScreenWithoutThePlayer() {
        open = false
        show()
        fingerTapEverywhere()
        assertTrue("positive control for finger taps", behind > 100)
    }

    @Test fun draggingTheProgressBarSeeksOnceOnReleaseAndNowhereElse() {
        show()
        rule.onNodeWithTag("player-seek").performTouchInput {
            down(Offset(width * 0.2f, centerY))
            moveTo(Offset(width * 0.5f, centerY))
            moveTo(Offset(width * 0.75f, centerY))
            up()
        }
        rule.waitForIdle()
        assertEquals("the player seeks when the finger lifts, not at every step", 1, seeks.size)
        assertTrue("near three quarters: ${seeks[0]}", seeks[0] in 0.65f..0.85f)
        assertEquals(0, behind)
        assertTrue(calls.isEmpty())
    }

    @Test fun pullingThePlayerDownMinimizesIt() {
        show()
        rule.onNodeWithTag("player-cover").performTouchInput { swipeDown(startY = centerY, endY = centerY + 900f) }
        rule.waitForIdle()
        assertEquals(1, calls["minimize"])
        assertEquals(0, behind)
    }

    /** A real finger starts slowly: many movements shorter than the touch slop. */
    @Test fun aSlowPullMinimizesItToo() {
        show()
        rule.onNodeWithTag("player-cover").performTouchInput {
            down(center)
            repeat(150) { moveBy(Offset(0f, 4f), delayMillis = 8) }
            up()
        }
        rule.waitForIdle()
        assertEquals(1, calls["minimize"])
        assertEquals(0, behind)
    }

    @Test fun aShortPullSpringsBackWithoutMinimizing() {
        show()
        rule.onNodeWithTag("player-cover").performTouchInput {
            down(center)
            repeat(20) { moveBy(Offset(0f, 3f), delayMillis = 16) }
            up()
        }
        rule.waitForIdle()
        assertTrue(calls.isEmpty())
        assertEquals(0, behind)
    }

    @Test fun backClosesThePlayerAndDoesNotGoBackBehindIt() {
        show()
        androidx.test.espresso.Espresso.pressBack()
        rule.waitForIdle()
        assertEquals(1, calls["minimize"])
        assertEquals("Back must not reach the screen under the player", 0, behindBack)
    }

    @Test fun theScreenBehindIsHiddenFromTheScreenReaderOnlyWhileCovered() {
        show()
        rule.onAllNodesWithText("Acción de detrás").assertCountEquals(0)
        rule.onAllNodesWithText("Canción ficticia 3").assertCountEquals(0)
        open = false
        rule.waitForIdle()
        rule.onAllNodesWithText("Acción de detrás").assertCountEquals(1)
        rule.onNodeWithText("Acción de detrás").performClick()
        assertEquals("and it works again once the player is minimized", 1, behind)
    }
}
