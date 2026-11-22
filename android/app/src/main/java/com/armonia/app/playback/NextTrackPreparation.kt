package com.armonia.app.playback

import com.armonia.app.data.repository.AuthSnapshot
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout

internal enum class PreparationResult { ACCEPTED, BUSY, UNAVAILABLE }

/** Asks the server to prepare one next track; never starts playback, downloads locally or submits listens.
 * Call update from the player's main thread. Session changes discard all private deduplication state.
 */
internal class NextTrackPreparation(
    private val scope: CoroutineScope,
    private val currentAuth: () -> AuthSnapshot,
    private val prepare: suspend (String, AuthSnapshot) -> PreparationResult,
    private val nowMs: () -> Long = { System.nanoTime() / 1_000_000 },
    private val debounceMs: Long = 300,
    private val timeoutMs: Long = 8_000,
    private val busyRetryDelaysMs: List<Long> = listOf(1_000, 3_000),
) {
    private var auth: AuthSnapshot? = null
    private var target: String? = null
    private var job: Job? = null
    private val completed = linkedMapOf<String, Long>()

    fun update(snapshot: AuthSnapshot, videoId: String?) {
        if (snapshot != auth) {
            cancel()
            completed.clear()
            auth = snapshot
        }
        val eligible = videoId?.takeIf {
            snapshot.sessionId.isNotBlank() && snapshot.userId.isNotBlank() &&
                snapshot.serverUrl.isNotBlank() && VIDEO_ID.matches(it)
        }
        if (eligible == null) { cancel(); return }
        if (target == eligible && job?.isActive == true) return
        cancel()
        val now = nowMs()
        completed.entries.removeAll { it.value <= now }
        if (eligible in completed) return
        target = eligible
        job = scope.launch {
            delay(debounceMs) // Changing the queue quickly must not start a request for every intermediate item.
            if (snapshot != currentAuth()) return@launch
            try {
                val accepted = withTimeout(timeoutMs) {
                    // Opening a list may still be preparing its first track. Retry that busy
                    // response twice without waiting for another player event. Never retry denial.
                    for (attempt in 0..busyRetryDelaysMs.size) {
                        if (snapshot != currentAuth()) return@withTimeout false
                        when (prepare(eligible, snapshot)) {
                            PreparationResult.ACCEPTED -> return@withTimeout true
                            PreparationResult.UNAVAILABLE -> return@withTimeout false
                            PreparationResult.BUSY -> if (attempt < busyRetryDelaysMs.size) {
                                delay(busyRetryDelaysMs[attempt])
                            }
                        }
                    }
                    false
                }
                if (snapshot == currentAuth()) remember(eligible, if (accepted) 120_000 else 30_000)
            } catch (_: TimeoutCancellationException) {
                if (snapshot == currentAuth()) remember(eligible, 30_000)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                // Optional optimization: no toast, retry loop or interruption of the current song.
                if (snapshot == currentAuth()) remember(eligible, 30_000)
            }
        }
    }

    private fun remember(id: String, ttl: Long) {
        completed[id] = nowMs() + ttl
        while (completed.size > 16) completed.remove(completed.keys.first())
    }

    fun cancel() {
        job?.cancel()
        job = null
        target = null
    }

    companion object {
        private val VIDEO_ID = Regex("[A-Za-z0-9_-]{11}")

        fun eligibleVideoId(mediaId: String?, active: Boolean, audition: Boolean,
                            repeatOne: Boolean, localFile: Boolean): String? {
            if (!active || audition || repeatOne || localFile) return null
            // Android Auto browsable IDs encode a normal track ID in the last segment.
            val id = if (mediaId?.startsWith("track|") == true) mediaId.split('|', limit = 4).last() else mediaId
            return id?.takeIf { it.startsWith("preview|") }?.removePrefix("preview|")
                ?.takeIf(VIDEO_ID::matches)
        }
    }
}
