package com.armonia.app.playback

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertNull
import org.junit.Assert.fail
import org.junit.Test
import java.io.IOException

@androidx.media3.common.util.UnstableApi
class VariantsTest {
    private val base = "acc:https://server/api/stream/t1"

    @Test fun keysKeepEachVariantApart() {
        assertEquals("$base#ahorro", Variant.AHORRO.key(base))
        assertEquals(Variant.AHORRO, Variant.ofKey("$base#ahorro"))
        assertEquals(Variant.LIGERA, Variant.ofKey(StreamCacheKeys.playbackKeyFor("https://server/api/stream/t1", "acc")))
        assertNull(Variant.ofKey(base))
        assertNull(Variant.ofKey("$base#otra"))
        assertNull(Variant.ofKey(null))
    }

    @Test fun aSlowPathStartsWithTheLowCopyAndAFastOneWithTheLightCopy() {
        var slow = true
        val chooser = VariantChooser(keptFromStart = { 0 }, lowWanted = { slow })
        assertEquals(Variant.AHORRO, chooser.choose(base, 0))
        slow = false
        assertEquals(Variant.LIGERA, chooser.choose(base, 0))
    }

    @Test fun whatThePhoneAlreadyKeepsWinsAndASongKeepsItsVariantPastTheStart() {
        val kept = mutableMapOf(Variant.LIGERA.key(base) to 300_000L)
        var slow = true
        val chooser = VariantChooser(keptFromStart = { kept[it] ?: 0 }, lowWanted = { slow })
        assertEquals(Variant.LIGERA, chooser.choose(base, 0)) // kept whole: no network at all
        kept.clear()
        kept[Variant.AHORRO.key(base)] = 262_144L // its start was preloaded while saving data
        assertEquals(Variant.AHORRO, chooser.choose(base, 0))
        kept.clear()
        slow = false
        // A seek or a resume mid-song stays with the header it read, whatever the path is now.
        assertEquals(Variant.AHORRO, chooser.choose(base, 5_000_000))
        assertEquals(Variant.LIGERA, chooser.choose(base, 0))
        slow = true
        assertEquals(Variant.LIGERA, chooser.choose(base, 1_000))
    }

    @Test fun aVariantTheServerCannotGiveNowIsSkippedForAWhile() {
        var clock = 0L
        val chooser = VariantChooser(keptFromStart = { 0 }, lowWanted = { true }, now = { clock })
        assertEquals(Variant.AHORRO, chooser.choose(base, 0))
        assertEquals(Variant.LIGERA, chooser.failed(base, Variant.AHORRO))
        assertEquals(Variant.LIGERA, chooser.choose(base, 0))
        assertEquals(Variant.LIGERA, chooser.choose(base, 9_000))
        assertEquals(Variant.ORIGINAL, chooser.failed(base, Variant.LIGERA))
        assertNull(chooser.failed(base, Variant.ORIGINAL))
        clock += VariantChooser.RETRY_AFTER_MS + 1
        assertEquals(Variant.AHORRO, chooser.choose(base, 0))
    }

    private class Refused(val status: Int) : IOException()

    /** Opens like the cache would: refuses the keys in [refused] with their status, records what it was asked. */
    private fun opener(refused: Map<String, Int>, asked: MutableList<String>, base: String) = { variant: Variant ->
        asked += variant.key(base)
        refused[variant.key(base)]?.let { throw Refused(it) }
        10L
    }

    private val unavailable: (IOException) -> Boolean = { it is Refused && it.status == 503 }

    @Test fun atTheStartA503MovesToTheNextVariantAndMidSongItDoesNot() {
        val asked = mutableListOf<String>()
        val chooser = VariantChooser(keptFromStart = { 0 }, lowWanted = { true })
        assertEquals(10L, chooser.open(base, 0, unavailable, opener(mapOf(Variant.AHORRO.key(base) to 503), asked, base)))
        assertEquals(listOf(Variant.AHORRO.key(base), Variant.LIGERA.key(base)), asked)

        val other = "acc:https://server/api/stream/t2"
        val midSong = VariantChooser(keptFromStart = { 0 }, lowWanted = { true }).also { it.choose(other, 0) }
        try {
            midSong.open(other, 4_000, unavailable, opener(mapOf(Variant.AHORRO.key(other) to 503), mutableListOf(), other))
            fail("a song's header and its audio must come from the same file")
        } catch (e: Refused) {
            assertEquals(503, e.status)
        }
    }

    @Test fun otherErrorsAreNotAReasonToChangeFile() {
        val asked = mutableListOf<String>()
        val chooser = VariantChooser(keptFromStart = { 0 }, lowWanted = { true })
        try {
            chooser.open(base, 0, unavailable, opener(mapOf(Variant.AHORRO.key(base) to 403), asked, base))
            fail()
        } catch (e: Refused) {
            assertEquals(403, e.status)
        }
        assertEquals(listOf(Variant.AHORRO.key(base)), asked)
    }

    @Test fun whenNoVariantCanBeHadTheErrorReachesThePlayer() {
        val all = Variant.entries.associate { it.key(base) to 503 }
        val asked = mutableListOf<String>()
        try {
            VariantChooser(keptFromStart = { 0 }, lowWanted = { true }).open(base, 0, unavailable, opener(all, asked, base))
            fail()
        } catch (e: Refused) {
            assertEquals(503, e.status)
        }
        assertEquals(Variant.entries.size, asked.size)
    }

    @Test fun aServerOlderThanTheLowCopyIsNotKeptAsIt() {
        val fromOldServer = mapOf<String, List<String>>("content-type" to listOf("audio/mp4"))
        val fromNewServer = mapOf<String, List<String>>("x-armonia-variante" to listOf("baja"))
        assertTrue(VariantDataSource.servedWithoutVariants(Variant.AHORRO, fromOldServer))
        assertFalse(VariantDataSource.servedWithoutVariants(Variant.AHORRO, fromNewServer))
        assertFalse(VariantDataSource.servedWithoutVariants(Variant.AHORRO, emptyMap())) // all from the phone
        assertFalse(VariantDataSource.servedWithoutVariants(Variant.LIGERA, fromOldServer))
        assertTrue(VariantDataSource.unavailableNow(VariantDataSource.ServerWithoutVariants()))
    }

    @Test fun theNextSongIsPreloadedOnceTheCurrentOneHasEnoughInHand() {
        var clock = 0L
        val preload = NextSongPreload(now = { clock })
        val next = "https://server/api/stream/t2"
        assertNull(preload.next(playing = true, bufferedAheadMs = 5_000, loadedToEnd = false, nextUri = next))
        assertNull(preload.next(playing = false, bufferedAheadMs = 60_000, loadedToEnd = false, nextUri = next))
        assertNull(preload.next(true, 60_000, false, "https://www.youtube.com/watch?v=x"))
        assertNull(preload.next(true, 60_000, false, "file:///music/a.m4a"))
        assertEquals(next, preload.next(true, 25_000, false, next))
        assertNull(preload.next(true, 25_000, false, next)) // already on it
        preload.done(next)
        assertNull(preload.next(true, 25_000, false, next)) // not again soon
        clock += NextSongPreload.AGAIN_AFTER_MS + 1
        // Loaded to its end, the player goes on with the next song itself.
        assertNull(preload.next(true, 60_000, true, next))
        // On a slow path only while going through the queue in order, not while picking songs from a list.
        assertNull(preload.next(true, 25_000, false, next, slow = true, inOrder = false))
        assertEquals(next, preload.next(true, 25_000, false, next, slow = true, inOrder = true))
    }

    @Test fun coversWaitForAStartingSongButNotForever() {
        var clock = 1_000L
        val sleep: (Long) -> Unit = { clock += it }
        PlaybackStart.end()
        PlaybackStart.awaitStarted(4_000, { clock }, sleep)
        assertEquals(1_000L, clock) // nothing starting: no wait
        PlaybackStart.begin(clock)
        PlaybackStart.awaitStarted(4_000, { clock }, sleep)
        assertEquals(5_000L, clock) // at most the limit
        clock += 10_000 // stuck for long: a problem of its own, covers go on
        PlaybackStart.awaitStarted(4_000, { clock }, sleep)
        assertEquals(15_000L, clock)
        PlaybackStart.end()
    }

    @Test fun dataSavingFollowsTheChoiceAndAlwaysOnABadConnection() {
        // No: only a bad connection.
        assertEquals(false, DataSaving.wanted(DataSaver.NO, onMobileData = true, poor = false))
        assertEquals(true, DataSaving.wanted(DataSaver.NO, onMobileData = false, poor = true))
        // Con datos: on mobile data, or a bad Wi-Fi.
        assertEquals(true, DataSaving.wanted(DataSaver.DATOS, onMobileData = true, poor = false))
        assertEquals(false, DataSaving.wanted(DataSaver.DATOS, onMobileData = false, poor = false))
        assertEquals(true, DataSaving.wanted(DataSaver.DATOS, onMobileData = false, poor = true))
        // Siempre: everywhere.
        assertEquals(true, DataSaving.wanted(DataSaver.SIEMPRE, onMobileData = false, poor = false))
        assertEquals(DataSaver.DATOS, DataSaver.of(null))
        assertEquals(DataSaver.SIEMPRE, DataSaver.of("siempre"))
    }

    @Test fun theSavingCopyKeptOnThePhoneIsNotPlayedAtHome() {
        val base = "ns:https://s/api/stream/t"
        val kept = mutableMapOf(Variant.AHORRO.key(base) to 2_000_000L)
        var low = false
        val chooser = VariantChooser(keptFromStart = { kept[it] ?: 0L }, lowWanted = { low })
        // On Wi-Fi without saving: the light copy (original quality), even with the saving copy on the phone.
        assertEquals(Variant.LIGERA, chooser.choose(base, 0))
        // Saving: the copy on the phone, nothing to download.
        low = true
        assertEquals(Variant.AHORRO, chooser.choose(base, 0))
        // Saving, but the whole light copy is on the phone (kept on Wi-Fi): that one, no data at all.
        kept[Variant.LIGERA.key(base)] = 3_500_000L
        assertEquals(Variant.LIGERA, chooser.choose(base, 0))
    }

    @Test fun badConnectionAndMobileDataComeFromTheNetwork() {
        PathRate.onNetwork("movil:1", 3_000, metered = true)
        assertEquals(true, PathRate.metered())
        assertEquals(false, PathRate.poor())
        repeat(6) { PathRate.onDelivery("movil:1", deliveredKbps = 100, probeKbps = 6_000) }
        assertEquals(true, PathRate.poor())
        PathRate.onNetwork("wifi:2", 16_000, metered = false)
        assertEquals(false, PathRate.metered())
        assertEquals(false, PathRate.poor()) // a new network starts again from its guess
        PathRate.onNetwork(null, null)
    }
}
