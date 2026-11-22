package com.armonia.app.security

import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.ResolvingDataSource
import androidx.media3.datasource.okhttp.OkHttpDataSource
import com.armonia.app.data.repository.PreferencesRepository
import com.armonia.app.playback.StreamCacheKeys
import com.armonia.app.playback.Variant
import okhttp3.OkHttpClient
import java.io.IOException
import java.util.concurrent.TimeUnit

@UnstableApi
object AuthenticatedMedia {
    /**
     * One client, so one connection pool, for every audio request and for ConnectionWarmer: over
     * HTTP/2 they share a single open connection to the server, and a song tapped after a pause
     * reuses it instead of opening a new one (see ConnectionWarmer for why that matters).
     */
    val client: OkHttpClient by lazy {
        OkHttpClient.Builder().followRedirects(false).followSslRedirects(false)
            .connectTimeout(15, TimeUnit.SECONDS).readTimeout(45, TimeUnit.SECONDS)
            .addNetworkInterceptor(com.armonia.app.playback.DeliveryMeter())
            .build()
    }

    /**
     * [download]: an offline download wants the whole original file as fast as it comes. Playback
     * asks for the light copy (no embedded cover) and tells the server how fast songs reach this
     * phone, so it paces them to fit (see middleware/services/stream_pacing.py and PathRate).
     */
    fun factory(prefs: PreferencesRepository, download: Boolean = false): DataSource.Factory {
        // Which file: the variant the stream cache keeps this song's bytes under (see Variants.kt).
        fun transfer(key: String?): Map<String, String> = if (download) mapOf("X-Armonia-Transfer" to "download")
            else buildMap {
                put("X-Armonia-Variante", (Variant.ofKey(key) ?: Variant.LIGERA).wire)
                com.armonia.app.playback.PathRate.hintKbps()?.let { put("X-Armonia-Ritmo", it.toString()) }
                // On mobile data the server sends at most 30 s of song ahead of playback (stream_pacing.py).
                if (com.armonia.app.playback.PathRate.metered()) put("X-Armonia-Datos", "1")
            }
        return ResolvingDataSource.Factory(OkHttpDataSource.Factory(client)) { spec ->
            val auth = prefs.cachedAuth
            val url = spec.uri.toString()
            if (!AccountScope.sameOrigin(url, auth.serverUrl) || auth.sessionId.isBlank())
                throw IOException("Authenticated music server required")
            val base = StreamCacheKeys.keyFor(url, auth.namespace)
            val expected = setOf(base) + if (download) emptySet() else Variant.entries.map { it.key(base) }
            if (spec.key != null && spec.key !in expected) throw IOException("Download belongs to another account")
            spec.withRequestHeaders(spec.httpRequestHeaders + transfer(spec.key) + mapOf("X-Session-Id" to auth.sessionId,"X-Music-Owner" to auth.userId))
        }
    }
}
