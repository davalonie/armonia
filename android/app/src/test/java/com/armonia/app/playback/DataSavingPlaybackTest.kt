package com.armonia.app.playback

import androidx.media3.common.util.UnstableApi
import com.armonia.app.offline.PrefillOrder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

@UnstableApi
class DataSavingPlaybackTest {
    @Test fun onMobileDataAtMostThirtySecondsAhead() {
        var mobile = true
        val control = DataSavingLoadControl { mobile }
        assertFalse(control.farEnough(10_000_000L))
        assertTrue(control.farEnough(30_000_000L))
        mobile = false // on Wi-Fi, ExoPlayer's own limit (50 s)
        assertFalse(control.farEnough(30_000_000L))
    }

    @Test fun theNextSongsAreAskedForOnceAndOnlyWhenNotOnThePhone() {
        val asked = mutableListOf<List<String>>()
        val prep = SavingPreparation { asked += it }
        val next = listOf("https://s/api/stream/a?x=1", "https://s/api/stream/b%20c", "https://s/api/stream/d")
        prep.update(wanted = false, nextUris = next) { false }
        assertEquals(emptyList<List<String>>(), asked) // not saving: nothing
        prep.update(wanted = true, nextUris = next) { it.endsWith("/a?x=1") }
        assertEquals(listOf(listOf("b c")), asked) // two next songs, the one on the phone left out
        prep.update(wanted = true, nextUris = next) { false }
        assertEquals(1, asked.size) // same songs: asked already
        assertEquals(null, SavingPreparation.trackId("https://s/api/external/x"))
        assertEquals("a+b", SavingPreparation.trackId("https://s/api/stream/a+b"))
    }

    @Test fun keptOnWifiInOrderWeeklyFavouritesMostPlayed() {
        assertEquals(listOf("w1", "f1", "w2", "p1"),
            PrefillOrder.of(weekly = listOf("w1", ""), favourites = listOf("f1", "w1"), mostPlayed = listOf("w2", "p1", "f1")).let {
                listOf(it[0], it[1], it[2], it[3])
            })
    }

    @Test fun theMonthStartsOnItsFirstDayAtMidnight() {
        val start = DataUsage.monthStart(java.util.Calendar.getInstance().apply { set(2026, 10, 19, 13, 5, 7) }.timeInMillis)
        val c = java.util.Calendar.getInstance().apply { timeInMillis = start }
        assertEquals(listOf(2026, 10, 1, 0, 0, 0), listOf(c.get(1), c.get(2), c.get(5), c.get(11), c.get(12), c.get(13)))
    }
}
