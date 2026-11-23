package com.armonia.app.playback

import android.net.Uri
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.HttpDataSource
import androidx.media3.datasource.TransferListener
import java.io.IOException

/**
 * Which file of a song playback keeps: the light copy (the original without its embedded cover), the
 * data-saving copy (Opus 64 kbit/s, see DataSaving) or the original. Each one is kept under its own cache key, and the server
 * answers a variant always with the same bytes or with an error, never with another variant in its place
 * (middleware/services/stream_pacing.py, VARIANTS): so a song's header and its audio never come from two
 * different files.
 */
enum class Variant(val wire: String) {
    LIGERA("ligera"), AHORRO("ahorro"), ORIGINAL("original");

    fun key(base: String) = "$base#$wire"

    /** What to ask for when the server cannot give this one now. */
    val fallback: Variant? get() = when (this) { AHORRO -> LIGERA; LIGERA -> ORIGINAL; ORIGINAL -> null }

    companion object {
        fun ofKey(key: String?): Variant? {
            val wire = key?.substringAfterLast('#', "") ?: return null
            return entries.firstOrNull { it.wire == wire }
        }
    }
}

/** The listener's choice in Settings, "Ahorro de datos": never, on mobile data (the default) or always. */
enum class DataSaver(val pref: String) {
    NO("no"), DATOS("datos"), SIEMPRE("siempre");

    companion object {
        val DEFAULT = DATOS
        fun of(pref: String?) = entries.firstOrNull { it.pref == pref } ?: DEFAULT
    }
}

/**
 * When a song starts, whether to ask for the data-saving copy: when the listener chose it for this network,
 * and on any bad connection whatever the choice (the listener's decision, 18-11-2026), where the original
 * starts late or stops. A song already kept on the phone plays from there (VariantChooser).
 */
object DataSaving {
    @Volatile var choice: DataSaver = DataSaver.DEFAULT

    fun wanted(choice: DataSaver = this.choice, onMobileData: Boolean = PathRate.metered(), poor: Boolean = PathRate.poor()) =
        poor || choice == DataSaver.SIEMPRE || (choice == DataSaver.DATOS && onMobileData)
}

/**
 * Picks the variant when a song starts (its first byte is read) and keeps it for the rest of that song's
 * reads: seeks, and resumes after a dropped connection. So a change of network or of the connection's
 * quality applies from the next song, never in the middle of one. At the start, whichever variant this
 * phone already keeps more of from the beginning (nothing to download is always fastest), except that the
 * data-saving copy is never preferred when saving is not wanted (at home, the original quality); with
 * none, the data-saving copy when [lowWanted] and the light copy otherwise.
 */
class VariantChooser(
    private val keptFromStart: (String) -> Long,
    private val lowWanted: () -> Boolean,
    private val now: () -> Long = { System.nanoTime() / 1_000_000 },
    private val offlineCopy: (String) -> Variant? = { null },
) {
    private val chosen = object : LinkedHashMap<String, Variant>(64, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, Variant>?) = size > 512
    }
    private val unavailableUntil = HashMap<String, Long>()

    @Synchronized fun choose(base: String, position: Long): Variant {
        if (position > 0) chosen[base]?.let { return it }
        val usable = Variant.entries.filter { available(base, it) }
        val low = lowWanted()
        val kept = usable.filter { low || it != Variant.AHORRO }
            .map { it to keptFromStart(it.key(base)) }.filter { it.second > 0 }.maxByOrNull { it.second }?.first
        val pick = offlineCopy(base) ?: kept ?: when {
            low && Variant.AHORRO in usable -> Variant.AHORRO
            Variant.LIGERA in usable -> Variant.LIGERA
            else -> Variant.ORIGINAL
        }
        chosen[base] = pick
        return pick
    }

    /** The server could not give [variant] now (503 at the start): the next one for this song, if any. */
    @Synchronized fun failed(base: String, variant: Variant): Variant? {
        val t = now()
        unavailableUntil[variant.key(base)] = t + RETRY_AFTER_MS
        if (unavailableUntil.size > 256) unavailableUntil.entries.removeAll { it.value <= t }
        var next = variant.fallback
        while (next != null && !available(base, next)) next = next.fallback
        if (next != null) chosen[base] = next
        return next
    }

    private fun available(base: String, variant: Variant) = (unavailableUntil[variant.key(base)] ?: 0L) <= now()

    /**
     * Runs [attempt] with the variant chosen for this read; at the start of a song, while the server says it
     * cannot give one now ([unavailableNow]), with the next one. Mid-song never: the header already read
     * belongs to the chosen variant, and no other file can follow it.
     */
    fun <T> open(base: String, position: Long, unavailableNow: (IOException) -> Boolean, attempt: (Variant) -> T): T {
        var variant = choose(base, position)
        while (true) {
            try {
                return attempt(variant)
            } catch (e: IOException) {
                if (position != 0L || !unavailableNow(e)) throw e
                variant = failed(base, variant) ?: throw e
            }
        }
    }

    companion object {
        const val RETRY_AFTER_MS = 10 * 60_000L
    }
}

/**
 * Sits above the stream cache: gives every read of a song the key of its chosen variant (so the cache keeps
 * each variant apart and the request says which one it wants, see AuthenticatedMedia), and at the start of
 * a song moves to the next variant when the server cannot give one now.
 */
@UnstableApi
class VariantDataSource(
    private val cached: DataSource.Factory,
    private val chooser: VariantChooser,
    private val baseKey: (String) -> String,
    private val forget: (String) -> Unit = {},
) : DataSource {
    private var delegate: DataSource? = null
    private val listeners = mutableListOf<TransferListener>()

    override fun addTransferListener(transferListener: TransferListener) {
        listeners.add(transferListener)
        delegate?.addTransferListener(transferListener)
    }

    override fun open(dataSpec: DataSpec): Long {
        val base = baseKey(dataSpec.uri.toString())
        return chooser.open(base, dataSpec.position, ::unavailableNow) { variant ->
            val source = cached.createDataSource()
            listeners.forEach(source::addTransferListener)
            try {
                val length = source.open(dataSpec.buildUpon().setKey(variant.key(base)).build())
                if (servedWithoutVariants(variant, source.responseHeaders)) {
                    forget(variant.key(base)) // nothing read: only what the cache noted about its length
                    throw ServerWithoutVariants()
                }
                delegate = source
                length
            } catch (e: IOException) {
                runCatching { source.close() }
                throw e
            }
        }
    }

    override fun read(buffer: ByteArray, offset: Int, length: Int): Int = checkNotNull(delegate).read(buffer, offset, length)
    override fun getUri(): Uri? = delegate?.uri
    override fun getResponseHeaders(): Map<String, List<String>> = delegate?.responseHeaders ?: emptyMap()
    override fun close() {
        try { delegate?.close() } finally { delegate = null }
    }

    /** A server from before the data-saving copy (or one rolled back) answers "ahorro" with the original file. */
    class ServerWithoutVariants : IOException("server does not know this variant")

    companion object {
        /** The server's answer when a variant cannot be made or read this time (see middleware/routes/stream.py). */
        fun unavailableNow(e: IOException) =
            e is ServerWithoutVariants || (e is HttpDataSource.InvalidResponseCodeException && e.responseCode == 503)

        /**
         * The server says which file it sent; one that does not (older than the low copy) sent the original,
         * which must never be kept as the data-saving copy. [headers] are empty when everything came from the phone.
         */
        fun servedWithoutVariants(variant: Variant, headers: Map<String, List<String>>): Boolean =
            variant == Variant.AHORRO && headers.isNotEmpty() &&
                headers.none { (name, values) -> name.equals("X-Armonia-Variante", ignoreCase = true) && values.isNotEmpty() }
    }
}

/**
 * Keeps the start of the next song of the queue on the phone while the current one plays, so skipping to it
 * starts at once, as streaming services do. Only once the current song has enough in hand (it must never
 * wait for this), only songs from the server, and each song at most once in a while. On a slow path only
 * while the listener goes through the queue in order: on 18-11-2026 songs were picked from a list, both
 * preloads were for songs never played, and their bytes delayed the song that was.
 */
class NextSongPreload(private val now: () -> Long = { System.nanoTime() / 1_000_000 }) {
    private val tried = LinkedHashMap<String, Long>()
    var target: String? = null
        private set

    /** The song to start keeping now, or null. Call from the player's thread. */
    fun next(playing: Boolean, bufferedAheadMs: Long, loadedToEnd: Boolean, nextUri: String?,
             slow: Boolean = false, inOrder: Boolean = true): String? {
        if (!playing || nextUri == null || !nextUri.substringBefore('?').contains("/api/stream/")) return null
        if (slow && !inOrder) return null
        // Loaded to its end, the player itself goes on with the next song: nothing to add.
        if (bufferedAheadMs < AHEAD_MS || loadedToEnd) return null
        if (nextUri == target) return null
        val t = now()
        tried.entries.removeAll { it.value <= t }
        if (nextUri in tried) return null
        tried[nextUri] = t + AGAIN_AFTER_MS
        while (tried.size > 64) tried.remove(tried.keys.first())
        target = nextUri
        return nextUri
    }

    fun done(uri: String) {
        if (target == uri) target = null
    }

    companion object {
        const val AHEAD_MS = 20_000L
        const val AGAIN_AFTER_MS = 10 * 60_000L
        /** The header and the first seconds (≈5 s of a 128 kbit/s song, the whole library on 18-11-2026). */
        const val BYTES = 128 * 1024L
        /** Tells the server not to hurry (middleware/services/stream_pacing.py, rates). */
        const val HEADER = "X-Armonia-Precarga"
    }
}

/**
 * While a song is starting on a slow path, covers wait (a few seconds at most) so they do not take the
 * little the path carries: on 18-11-2026 a song's start on a slow path shared it with 740 KB of covers.
 */
object PlaybackStart {
    /** On a slow path covers go one at a time, each one whole before the next (see ArmoniaApplication). */
    val coverTurn = java.util.concurrent.Semaphore(1)

    @Volatile private var since = 0L

    fun begin(nowMs: Long = System.nanoTime() / 1_000_000) { since = nowMs }
    fun end() { since = 0L }

    /** Blocks the calling (network) thread until the starting song plays, at most [maxMs]. */
    fun awaitStarted(maxMs: Long = 4_000, now: () -> Long = { System.nanoTime() / 1_000_000 },
                     sleep: (Long) -> Unit = Thread::sleep) {
        val deadline = now() + maxMs
        while (true) {
            val started = since
            val t = now()
            // A start stuck for long is a problem of its own: covers do not wait on it.
            if (started == 0L || t - started > STUCK_MS || t >= deadline) return
            sleep(100)
        }
    }

    private const val STUCK_MS = 8_000L
}
