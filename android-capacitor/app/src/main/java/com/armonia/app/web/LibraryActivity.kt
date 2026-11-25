package com.armonia.app.web

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import androidx.activity.addCallback
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.lifecycleScope
import coil.fetch.SourceResult
import coil.imageLoader
import coil.request.Options
import com.armonia.app.R
import com.armonia.app.AppEntry
import com.armonia.app.data.repository.AuthSnapshot
import com.armonia.app.data.repository.PreferencesRepository
import com.armonia.app.offline.OfflineManager
import com.armonia.app.playback.MusicPlayer
import com.armonia.app.playback.CoverSizes
import com.getcapacitor.BridgeActivity
import com.getcapacitor.BridgeWebViewClient
import com.getcapacitor.CapConfig
import com.google.gson.Gson
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import java.io.FilterInputStream
import javax.inject.Inject

@AndroidEntryPoint
class LibraryActivity : BridgeActivity() {
    @Inject lateinit var listenOutbox: com.armonia.app.homelab.ListenOutbox
    private var requestingNotifications = false
    private val notifications = registerForActivityResult(androidx.activity.result.contract.ActivityResultContracts.RequestPermission()) {
        requestingNotifications = false
    }

    fun showDownloadNotifications() {
        if (android.os.Build.VERSION.SDK_INT >= 33 && !requestingNotifications &&
            checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            requestingNotifications = true
            notifications.launch(android.Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    @Inject lateinit var downloadTracker: com.armonia.app.data.repository.DownloadTracker
    @Inject lateinit var warmer: com.armonia.app.playback.ConnectionWarmer
    @Inject lateinit var notices: com.armonia.app.playback.PlaybackNotices
    @Inject lateinit var prefs: PreferencesRepository
    @Inject lateinit var player: MusicPlayer
    @Inject lateinit var library: com.armonia.app.data.repository.LibraryRepository
    @Inject lateinit var streamCache: com.armonia.app.playback.StreamCache
    @Inject lateinit var musicApi: com.armonia.app.homelab.MusicApi
    @Inject lateinit var autoConnections: com.armonia.app.auto.AutoConnectionLog
    @Inject lateinit var offline: OfflineManager
    @Inject lateinit var http: OkHttpClient
    @Inject lateinit var gson: Gson
    @Inject lateinit var network: com.armonia.app.playback.NetworkMonitor
    val account: String get() = intent.getStringExtra("account").orEmpty()

    fun auth(): AuthSnapshot = prefs.cachedAuth.also {
        check(it.namespace == account && it.sessionId.isNotBlank())
    }

    // Chromium reads these encoded bytes directly. Coil owns freshness, disk keys and network scheduling.
    private fun coverResponse(url: String): WebResourceResponse {
        val loader = imageLoader
        val options = Options(applicationContext, diskCacheKey = url)
        val fetcher = requireNotNull(loader.components.newFetcher(Uri.parse(url), options, loader)).first
        val result = runBlocking { fetcher.fetch() } as SourceResult
        try {
            auth()
            val type = result.mimeType
            require(type in setOf("image/png", "image/jpeg", "image/webp", "image/gif", "image/avif"))
            val stream = object : FilterInputStream(result.source.source().inputStream()) {
                override fun close() = result.source.close()
            }
            return WebResourceResponse(type, null, 200, "OK", mapOf("Cache-Control" to "no-store"), stream)
        } catch (e: Exception) {
            result.source.close()
            throw e
        }
    }

    /**
     * The keyboard covers the bottom bar and the mini player, as in the Kotlin app (edge-to-edge, no
     * resize). With adjustNothing (manifest) Capacitor's SystemBars no longer pads the WebView by the
     * keyboard; instead the page gets how much of it the keyboard covers, in CSS px, as --ime, and
     * only the content makes room for it.
     */
    private var imeCss = -1
    private fun followKeyboard() {
        val web = bridge.webView
        fun publish(insets: androidx.core.view.WindowInsetsCompat?) {
            val ime = insets?.getInsets(androidx.core.view.WindowInsetsCompat.Type.ime())?.bottom ?: 0
            val place = IntArray(2).also { web.getLocationOnScreen(it) }
            val keyboardTop = window.decorView.height - ime
            val covered = if (ime > 0) (place[1] + web.height - keyboardTop).coerceAtLeast(0) else 0
            val css = Math.round(covered / resources.displayMetrics.density)
            if (css == imeCss) return
            imeCss = css
            web.evaluateJavascript("(()=>{const r=document.documentElement;r.style.setProperty('--ime','${css}px');" +
                "r.classList.toggle('ime-open',$css>0)})()", null)
        }
        androidx.core.view.ViewCompat.setWindowInsetsAnimationCallback(web,
            object : androidx.core.view.WindowInsetsAnimationCompat.Callback(DISPATCH_MODE_CONTINUE_ON_SUBTREE) {
                override fun onProgress(insets: androidx.core.view.WindowInsetsCompat,
                                        running: MutableList<androidx.core.view.WindowInsetsAnimationCompat>) =
                    insets.also { publish(androidx.core.view.ViewCompat.getRootWindowInsets(window.decorView)) }
                override fun onEnd(animation: androidx.core.view.WindowInsetsAnimationCompat) =
                    publish(androidx.core.view.ViewCompat.getRootWindowInsets(window.decorView))
            })
        // Without an animation (a hardware keyboard, a rotation) the layout still changes.
        window.decorView.viewTreeObserver.addOnGlobalLayoutListener {
            publish(androidx.core.view.ViewCompat.getRootWindowInsets(window.decorView))
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        // A different local origin isolates Web Storage and WebView caches for every server/account.
        val host = "a-${account.take(30)}.armonia.local"
        config = CapConfig.Builder(this).setHostname(host).setAndroidScheme("https")
            .setLoggingEnabled(false).create()
        registerPlugin(MusicPlugin::class.java)
        registerPlugin(ImportPlugin::class.java)
        super.onCreate(savedInstanceState)
        followKeyboard()
        lifecycleScope.launch { repeatOnLifecycle(Lifecycle.State.STARTED) { warmer.keepWarm() } }
        val fonts = mapOf(
            "/android-font/inter_regular.ttf" to R.font.inter_regular,
            "/android-font/inter_medium.ttf" to R.font.inter_medium,
            "/android-font/inter_semibold.ttf" to R.font.inter_semibold,
            "/android-font/inter_bold.ttf" to R.font.inter_bold,
        )
        onBackPressedDispatcher.addCallback(this) {
            bridge.webView.evaluateJavascript("window.dispatchEvent(new Event('armonia-back', {cancelable:true}))") { bubble ->
                if (bubble != "false") {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                    isEnabled = true
                }
            }
        }
        bridge.setWebViewClient(object : BridgeWebViewClient(bridge) {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                val uri = request.url
                val path = uri.path.orEmpty()
                if (uri.host == host && uri.scheme == "https" && request.method == "GET") {
                    fonts[path]?.let { return WebResourceResponse("font/ttf", null, resources.openRawResource(it)) }
                }
                val local = uri.host == host && uri.scheme == "https"
                val libraryArt = local && path == "/api/library/getCoverArt"
                val releaseArt = local && path.matches(Regex("/api/home/releases/[a-f0-9-]{36}/cover"))
                val publicArt = !local && uri.scheme in setOf("http", "https") &&
                    request.requestHeaders.entries.any { it.key.equals("Accept", true) && it.value.startsWith("image/") }
                if (request.method != "GET" || request.isForMainFrame || !(libraryArt || releaseArt || publicArt)) {
                    return super.shouldInterceptRequest(view, request)
                }
                return runCatching {
                    val session = auth()
                    val url = when {
                        libraryArt -> {
                            val id = requireNotNull(uri.getQueryParameter("id"))
                            require(!id.startsWith("http://", true) && !id.startsWith("https://", true))
                            val size = uri.getQueryParameter("size")?.toIntOrNull() ?: 300
                            if (size == CoverSizes.PLAYER) CoverSizes.player({ session.coverArtUrl(id, it) }, imageLoader)
                            else session.coverArtUrl(id, size)
                        }
                        releaseArt -> "${session.serverUrl.trimEnd('/')}$path?account=${session.namespace}"
                        else -> uri.toString()
                    }
                    coverResponse(url)
                }.getOrElse { WebResourceResponse("text/plain", "utf-8", 404, "Not Found", emptyMap(), null) }
            }
        })
        lifecycleScope.launch {
            prefs.authState.collect {
                if (!isFinishing && (it.sessionId.isBlank() || it.namespace != account)) {
                    AppEntry.restart(this@LibraryActivity)
                    finish()
                }
            }
        }
    }
}
