package com.armonia.app.offline

import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.ComponentName
import android.content.Context
import android.util.Log
import androidx.media3.common.util.UnstableApi
import com.armonia.app.data.repository.LibraryRepository
import com.armonia.app.data.repository.PreferencesRepository
import com.armonia.app.homelab.MusicApi
import com.armonia.app.playback.PathRate
import com.armonia.app.playback.PlaybackStart
import com.armonia.app.playback.StreamCache
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * On Wi-Fi (or another unmetered network) and with battery, keeps on the phone what the listener plays most:
 * the weekly list, the favourites and the most played songs, in that order, within [SHARE] of the playback
 * cache, so on mobile data they play from the phone without data (the listener's choice, 18-11-2026). They go
 * into the playback cache like any song played (least recently used first out), so nothing here is a second
 * copy, and a new limit or «Vaciar cache» applies to them too. Android runs it a few times a day, only on
 * an unmetered network; it stops when Android asks or after [RUN_MS] and goes on in the next run.
 */
@UnstableApi
@AndroidEntryPoint
class CachePrefillJob : JobService() {
    @Inject lateinit var prefs: PreferencesRepository
    @Inject lateinit var repository: LibraryRepository
    @Inject lateinit var musicApi: MusicApi
    @Inject lateinit var streamCache: StreamCache

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var running: Job? = null

    override fun onStartJob(params: JobParameters): Boolean {
        running = scope.launch {
            try {
                run()
            } catch (e: Exception) {
                Log.i(TAG, "stopped error=${e.javaClass.simpleName}")
            } finally {
                jobFinished(params, false)
            }
        }
        return true
    }

    override fun onStopJob(params: JobParameters): Boolean {
        running?.cancel()
        return false // periodic: the next run goes on
    }

    private suspend fun CoroutineScope.run() {
        if (!prefs.keepOnWifi.first() || prefs.cachedAuth.sessionId.isBlank() || PathRate.metered()) return
        val deadline = System.currentTimeMillis() + RUN_MS
        val budget = prefs.cacheMaxMb.first() * 1024L * 1024L * SHARE_PERCENT / 100
        val songs = repository.getSongs().getOrNull().orEmpty()
        val bySize = songs.associate { it.id to (it.size ?: 0L) }
        val wanted = PrefillOrder.of(
            weekly = runCatching { musicApi.homePlaylist("weekly").body()?.items.orEmpty() }.getOrDefault(emptyList())
                .filter { it.track.source == "navidrome" }.map { it.track.sourceId },
            favourites = repository.getFavorites().getOrNull()?.starred?.song.orEmpty().map { it.id },
            mostPlayed = songs.filter { (it.playCount ?: 0) > 0 }.sortedByDescending { it.playCount }.map { it.id },
        )
        var used = 0L
        var kept = 0
        var bytes = 0L
        for (id in wanted) {
            if (!isActive || System.currentTimeMillis() > deadline || PathRate.metered()) break
            val url = repository.getStreamUrl(id)
            val size = bySize[id] ?: 0L
            if (streamCache.isOnPhone(url)) { used += size; continue }
            if (used + size > budget) break
            PlaybackStart.awaitStarted() // a song someone is waiting for goes first
            val read = streamCache.keepWhole(url) { isActive && System.currentTimeMillis() <= deadline && !PathRate.metered() }
            if (read <= 0) continue
            used += size
            bytes += read
            kept++
        }
        Log.i(TAG, "kept songs=$kept bytes=$bytes candidates=${wanted.size}")
    }

    companion object {
        private const val TAG = "ArmoniaPrefill"
        private const val JOB_ID = 4_217
        const val SHARE_PERCENT = 40L
        const val RUN_MS = 8 * 60_000L
        private const val EVERY_MS = 6 * 60 * 60_000L

        /** Once per app start: keeps the existing schedule if there is one. */
        fun schedule(context: Context) {
            val scheduler = context.getSystemService(JobScheduler::class.java) ?: return
            if (scheduler.getPendingJob(JOB_ID) != null) return
            runCatching {
                scheduler.schedule(JobInfo.Builder(JOB_ID, ComponentName(context, CachePrefillJob::class.java))
                    .setRequiredNetworkType(JobInfo.NETWORK_TYPE_UNMETERED)
                    .setRequiresBatteryNotLow(true)
                    .setPeriodic(EVERY_MS)
                    .build())
            }
        }
    }
}

/** Weekly list first, then favourites, then most played; each song once. */
object PrefillOrder {
    fun of(weekly: List<String>, favourites: List<String>, mostPlayed: List<String>): List<String> =
        (weekly + favourites + mostPlayed).filter { it.isNotBlank() }.distinct()
}
