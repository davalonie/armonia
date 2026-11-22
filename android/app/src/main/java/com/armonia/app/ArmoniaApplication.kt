package com.armonia.app

import android.app.Application
import coil.ImageLoader
import coil.ImageLoaderFactory
import com.armonia.app.data.repository.PreferencesRepository
import com.armonia.app.security.AccountScope
import dagger.hilt.android.HiltAndroidApp
import okhttp3.OkHttpClient
import okhttp3.ResponseBody.Companion.toResponseBody
import javax.inject.Inject

@HiltAndroidApp
class ArmoniaApplication : Application(), ImageLoaderFactory {
    @Inject lateinit var prefs: PreferencesRepository

    @androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
    override fun onCreate() {
        super.onCreate()
        // On Wi-Fi, a few times a day, keep what is played most (see CachePrefillJob).
        com.armonia.app.offline.CachePrefillJob.schedule(this)
    }
    override fun newImageLoader(): ImageLoader = ImageLoader.Builder(this)
        // Covers are kept on the phone for good (the server lets it since 0.5.3; before, it said no-store and
        // none was kept): 300 MB holds every cover of a 2000-song library at the three sizes the app uses.
        .diskCache {
            coil.disk.DiskCache.Builder()
                .directory(cacheDir.resolve("image_cache"))
                .maxSizeBytes(300L * 1024 * 1024)
                .build()
        }
        .okHttpClient(OkHttpClient.Builder().followRedirects(false).followSslRedirects(false)
            .addInterceptor { chain ->
                val r = chain.request()
                val b = r.newBuilder().removeHeader("X-Session-Id")
                val account = prefs.cachedAuth
                val releaseCover = r.url.encodedPath.matches(Regex("/api/home/releases/[0-9a-f-]{36}/cover")) &&
                    r.url.queryParameter("account") == account.namespace
                if (AccountScope.sameOrigin(r.url.toString(), account.serverUrl) &&
                    (r.url.encodedPath == "/api/library/getCoverArt" || releaseCover) && account.sessionId.isNotBlank()) {
                    b.header("X-Session-Id", account.sessionId)
                    if (releaseCover) b.header("X-Music-Owner", account.userId)
                    // On a slow path a song that is starting goes first, and covers go one at a time,
                    // each read whole before the next, so together they never take the whole path
                    // (see PlaybackStart). On 18-11-2026 ~3 MB of covers and library data shared a slow
                    // path with a song that then took 10 s to get its first byte.
                    if (com.armonia.app.playback.PathRate.slow()) {
                        com.armonia.app.playback.PlaybackStart.awaitStarted()
                        val turn = com.armonia.app.playback.PlaybackStart.coverTurn
                        val mine = turn.tryAcquire(10, java.util.concurrent.TimeUnit.SECONDS)
                        try {
                            val response = chain.proceed(b.build())
                            val body = response.body
                            val bytes = body.bytes()
                            return@addInterceptor response.newBuilder()
                                .body(bytes.toResponseBody(body.contentType()))
                                .build()
                        } finally {
                            if (mine) turn.release()
                        }
                    }
                }
                chain.proceed(b.build())
            }.build())
        .build()
}
