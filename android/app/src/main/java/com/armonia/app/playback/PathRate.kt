package com.armonia.app.playback

import okhttp3.Interceptor
import okhttp3.Response
import okhttp3.ResponseBody.Companion.asResponseBody
import okio.Buffer
import okio.ForwardingSource
import okio.Source
import okio.buffer

/**
 * How fast songs actually reach this phone on its current network, so the server can pace them to fit
 * (see middleware/services/stream_pacing.py, rates()).
 *
 * Measured 18-11-2026: on a university network with excellent Wi-Fi signal the path to the server (a
 * Tailscale relay) carried only 25-220 KB/s; sending a song faster built a queue of seconds, then losses,
 * and the song took ~20 s to start. So the kind and quality of the phone's own network only give a first
 * guess; after that, how fast each song's first ~100 KB arrived replaces it.
 */
object PathRate {
    private const val MIN_KBPS = 64
    private const val MAX_KBPS = 1_000_000

    @Volatile private var networkKey: String? = null
    @Volatile private var guess: Int? = null
    @Volatile private var measured: Int? = null
    @Volatile private var meteredNow: Boolean = false

    /** What to tell the server, kbit/s; null when nothing is known yet. */
    fun hintKbps(): Int? = measured ?: guess

    /**
     * A path that cannot carry about 8 times a 256 kbit/s song: the songs that start slowly. On 18-11-2026
     * one measured at 1157 kbit/s took 9 s to start, and the relay paths measured 200-1800 kbit/s.
     * Then playback asks for the low copy (Variants.kt) and smaller covers that wait for the song to start.
     */
    fun slow(): Boolean = hintKbps()?.let { it < SLOW_KBPS } == true

    /**
     * A bad connection: below [POOR_KBPS] every song asks for the data-saving copy whatever the listener chose
     * (DataSaving). Measured 19-11-2026 in the lab (emulator behind a relay limiting speed, 60 ms each way,
     * AAC 128 songs of ~130 kbit/s): the original (ligera) started in 1.1-1.5 s down to 400 kbit/s, 2.3 s at
     * 250, 2.7 s at 200, 3.6 s at 150 and 4.4 s at 120, and below ~135 kbit/s it cannot keep up for a whole
     * song; an Opus 64 copy already made started in 0.7-1.9 s at every speed down to 120. Pending the
     * user's choice from that table.
     */
    fun poor(): Boolean = hintKbps()?.let { it < POOR_KBPS } == true

    /** Mobile data (or a network Android marks as metered, such as another phone's hotspot). */
    fun metered(): Boolean = meteredNow

    const val SLOW_KBPS = 2_000
    const val POOR_KBPS = 200

    fun currentNetwork(): String? = networkKey

    /** The phone's network changed (or its quality did): a new network starts again from its guess. */
    @Synchronized fun onNetwork(key: String?, guessKbps: Int?, metered: Boolean = false) {
        if (key != networkKey) {
            networkKey = key
            measured = null
        }
        guess = guessKbps?.coerceIn(MIN_KBPS, MAX_KBPS)
        meteredNow = key != null && metered
    }

    /** One song: [deliveredKbps] reached the phone while the server sent at [probeKbps]. */
    @Synchronized fun onDelivery(network: String?, deliveredKbps: Int, probeKbps: Int) {
        if (network != networkKey) return
        measured = next(measured ?: guess, deliveredKbps, probeKbps)
    }

    /**
     * If it arrived about as fast as it was sent, the path carries at least that much: keep the larger value,
     * so the next song (sent at twice the hint) probes higher. Otherwise the path is what arrived, averaged
     * with the previous value so one unlucky song does not swing it.
     */
    fun next(previous: Int?, deliveredKbps: Int, probeKbps: Int): Int {
        val value = when {
            deliveredKbps >= probeKbps * 0.85 -> maxOf(previous ?: 0, probeKbps)
            previous == null -> deliveredKbps
            else -> (previous + deliveredKbps) / 2
        }
        return value.coerceIn(MIN_KBPS, MAX_KBPS)
    }

    /**
     * First guess for a network from what Android estimates it carries downstream, which already
     * reflects its technology (5G, LTE, Wi-Fi link speed) and conditions: a quarter of it, since the
     * path through the server's own connection and Tailscale carries less than the phone's radio link,
     * and half of that again with a weak signal. Within 500 kbit/s (about 2x a song) and 16000.
     */
    fun guess(wifi: Boolean, cellular: Boolean, downstreamKbps: Int, signalDbm: Int?): Int? {
        if (downstreamKbps <= 0) return null
        var value = downstreamKbps / 4
        if (signalDbm != null && ((wifi && signalDbm < -75) || (cellular && signalDbm < -105))) value /= 2
        return value.coerceIn(500, 16_000)
    }
}

/**
 * Times how fast a song arrives while the server sends its start quickly (step 2 of its pacing, at the
 * rate it announces in X-Armonia-Ritmo: rapido=N): from the end of the first piece, which leaves at once,
 * to 128 KB, the least step 2 ever covers. Only playback responses (offline downloads are not paced) and
 * only network responses: this is a network interceptor, so songs read from the phone's cache never get here.
 */
class DeliveryMeter(
    private val now: () -> Long = System::nanoTime,
    private val network: () -> String? = PathRate::currentNetwork,
    private val report: (String?, Int, Int) -> Unit = PathRate::onDelivery,
) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val response = chain.proceed(chain.request())
        if (chain.request().header("X-Armonia-Variante") == null) return response
        val probe = probeKbps(response.header("X-Armonia-Ritmo")) ?: return response
        val body = response.body
        val timed = Timed(body.source(), probe, network(), now, report)
        return response.newBuilder().body(timed.buffer().asResponseBody(body.contentType(), body.contentLength())).build()
    }

    class Timed(
        source: Source, private val probe: Int, private val network: String?,
        private val now: () -> Long, private val report: (String?, Int, Int) -> Unit,
    ) : ForwardingSource(source) {
        private var total = 0L
        private var startAt = -1L
        private var startBytes = 0L
        private var done = false

        override fun read(sink: Buffer, byteCount: Long): Long {
            val n = super.read(sink, byteCount)
            if (n > 0 && !done) {
                total += n
                if (startAt < 0 && total >= FROM_BYTES) {
                    startAt = now()
                    startBytes = total
                } else if (startAt >= 0 && total >= TO_BYTES) {
                    done = true
                    val nanos = now() - startAt
                    if (nanos > 0) report(network, ((total - startBytes) * 8_000_000L / nanos).toInt(), probe)
                }
            }
            return n
        }
    }

    companion object {
        const val FROM_BYTES = 16 * 1024L
        const val TO_BYTES = 128 * 1024L

        fun probeKbps(header: String?): Int? =
            header?.split(';')?.map { it.trim() }?.firstOrNull { it.startsWith("rapido=") }
                ?.removePrefix("rapido=")?.toIntOrNull()?.takeIf { it > 0 }
    }
}
