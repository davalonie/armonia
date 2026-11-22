package com.armonia.app.playback

import okio.Buffer
import org.junit.Assert.*
import org.junit.Test

class PathRateTest {
    @Test fun `a path that keeps up lets the next song probe higher`() {
        assertEquals(4000, PathRate.next(2000, deliveredKbps = 3900, probeKbps = 4000))
        assertEquals(16000, PathRate.next(16000, deliveredKbps = 16000, probeKbps = 16000))
    }

    @Test fun `a slower path is what arrived, smoothed with the previous measure`() {
        assertEquals(800, PathRate.next(null, deliveredKbps = 800, probeKbps = 16000))
        assertEquals(1400, PathRate.next(2000, deliveredKbps = 800, probeKbps = 4000))
        assertEquals(64, PathRate.next(null, deliveredKbps = 3, probeKbps = 1000))
    }

    @Test fun `first guess follows the kind and quality of the network`() {
        // Good 5G (Android estimates hundreds of Mbit/s): the top rate.
        assertEquals(16000, PathRate.guess(wifi = false, cellular = true, downstreamKbps = 300_000, signalDbm = -85))
        // Same 5G with weak signal: half.
        assertEquals(16000, PathRate.guess(false, true, 300_000, -110))
        assertEquals(5000, PathRate.guess(false, true, 40_000, -110))
        // Poor LTE: the floor, about twice a song.
        assertEquals(500, PathRate.guess(false, true, 1_500, null))
        // Wi-Fi with a fair link and weak signal.
        assertEquals(6250, PathRate.guess(true, false, 50_000, -80))
        assertNull(PathRate.guess(true, false, 0, null))
    }

    @Test fun `a new network starts again from its guess, measures from another network are dropped`() {
        PathRate.onNetwork("wifi:100", 16000)
        PathRate.onDelivery("wifi:100", deliveredKbps = 900, probeKbps = 16000)
        assertEquals(8450, PathRate.hintKbps())
        PathRate.onNetwork("wifi:100", 12000)  // same network, its quality changed: the measure stays
        assertEquals(8450, PathRate.hintKbps())
        PathRate.onNetwork("movil:101", 3000)
        assertEquals(3000, PathRate.hintKbps())
        PathRate.onDelivery("wifi:100", deliveredKbps = 100, probeKbps = 16000)  // a song that began on Wi-Fi
        assertEquals(3000, PathRate.hintKbps())
        PathRate.onNetwork(null, null)
        assertNull(PathRate.hintKbps())
    }

    @Test fun `the meter times from the first piece to 128 KB`() {
        val reports = mutableListOf<Triple<String?, Int, Int>>()
        var clock = 0L
        val data = Buffer().write(ByteArray(300 * 1024))
        val timed = DeliveryMeter.Timed(data, probe = 4000, network = "wifi:1", now = { clock },
            report = { n, kbps, probe -> reports += Triple(n, kbps, probe) })
        val sink = Buffer()
        // 16 KB arrive at once, then 8 KB every 16 ms (4096 kbit/s).
        timed.read(sink, 16 * 1024)
        do clock += 16_000_000 while (timed.read(sink, 8 * 1024) > 0)
        assertEquals(1, reports.size)
        val (network, kbps, probe) = reports.single()
        assertEquals("wifi:1", network)
        assertEquals(4000, probe)
        assertEquals(4096, kbps)
    }

    @Test fun `the probe rate is read from the server's answer`() {
        assertEquals(2000, DeliveryMeter.probeKbps("rapido=2000; sostenido=500"))
        assertNull(DeliveryMeter.probeKbps("sostenido=500"))
        assertNull(DeliveryMeter.probeKbps(null))
        assertNull(DeliveryMeter.probeKbps("rapido=x"))
    }
}
