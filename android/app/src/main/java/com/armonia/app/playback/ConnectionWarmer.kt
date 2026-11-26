package com.armonia.app.playback

import android.os.SystemClock
import android.util.Log
import com.armonia.app.data.repository.PreferencesRepository
import com.armonia.app.security.AuthenticatedMedia
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import okhttp3.Request
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Keeps the connection to the server open while the app is on screen.
 *
 * The phone reaches the server through Tailscale, whose direct path between the two comes and
 * goes. A song tapped while the path is being rebuilt used to open a brand-new connection whose
 * first packets were lost, and Android only retries those after 1, 2 and 4 s: 3–8 s of silence
 * (measured on the phone, 17-11-2026). A tiny request every [INTERVAL_MS] on the same HTTP/2
 * connection the audio uses keeps that connection alive and notices a broken path before the
 * tap, so the song request rides an open connection instead of opening one.
 *
 * Only while the app is visible (see web.LibraryActivity): in the background it would keep the mobile
 * radio awake for nothing, and the next song in a queue is fetched well before it is needed.
 */
@Singleton
class ConnectionWarmer @Inject constructor(
    private val prefs: PreferencesRepository,
    private val network: NetworkMonitor,
) {
    // Same connection pool as the audio; a bounded wait so a broken path cannot pile up calls.
    private val client by lazy { AuthenticatedMedia.client.newBuilder().callTimeout(20, TimeUnit.SECONDS).build() }

    /** One request now and one every [INTERVAL_MS] until the calling coroutine is cancelled. */
    suspend fun keepWarm() = withContext(Dispatchers.IO) {
        while (isActive) {
            val auth = prefs.cachedAuth
            warmTarget(auth.serverUrl, auth.sessionId, network.online)?.let(::ping)
            delay(INTERVAL_MS)
        }
    }

    private fun ping(url: String) {
        val started = SystemClock.elapsedRealtime()
        val code = runCatching {
            client.newCall(Request.Builder().url(url).get().build()).execute().use { response ->
                response.body.bytes()
                response.code
            }
        }.getOrNull()
        val ms = SystemClock.elapsedRealtime() - started
        // Only what helps to diagnose: slow or failed attempts. No address, account or song.
        if (ms >= SLOW_MS || code != 200) Log.i(TAG, "warm ms=$ms ok=${code == 200}")
    }

    companion object {
        const val INTERVAL_MS = 10_000L
        const val SLOW_MS = 500L
        private const val TAG = "ArmoniaConexion"
    }
}

/** The address to keep warm, or null when there is nothing to keep: signed out or no network. */
fun warmTarget(serverUrl: String, sessionId: String, online: Boolean): String? {
    val base = serverUrl.trim().trimEnd('/')
    if (!online || sessionId.isBlank()) return null
    if (!base.startsWith("https://") && !base.startsWith("http://")) return null
    return "$base/health"
}
