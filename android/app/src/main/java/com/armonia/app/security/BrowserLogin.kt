package com.armonia.app.security

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Base64
import com.armonia.app.BuildConfig
import com.armonia.app.data.repository.PreferencesRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.security.MessageDigest
import java.security.SecureRandom

object BrowserLogin {
    private val http = OkHttpClient.Builder().followRedirects(false).followSslRedirects(false).build()
    private val flags = Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING

    fun origin(raw: String): String? {
        val url = raw.trim().toHttpUrlOrNull() ?: return null
        if ((!url.isHttps && !BuildConfig.DEBUG) || url.username.isNotEmpty() || url.password.isNotEmpty()
            || url.encodedPath != "/" || url.query != null || url.fragment != null) return null
        return url.toString().trimEnd('/')
    }

    suspend fun available(server: String): Boolean = withContext(Dispatchers.IO) {
        val base = origin(server) ?: return@withContext false
        runCatching {
            http.newCall(Request.Builder().url("$base/api/oidc/config").build()).execute().use {
                it.isSuccessful && JSONObject(it.body.string()).optBoolean("enabled")
            }
        }.getOrDefault(false)
    }

    suspend fun start(context: Context, raw: String, prefs: PreferencesRepository) {
        val server = requireNotNull(origin(raw))
        val verifier = Base64.encodeToString(ByteArray(32).also(SecureRandom()::nextBytes), flags)
        val challenge = Base64.encodeToString(MessageDigest.getInstance("SHA-256").digest(verifier.toByteArray()), flags)
        val pending = JSONObject().put("server", server).put("verifier", verifier)
            .put("expires", System.currentTimeMillis() + 600_000)
        prefs.storeBrowserTransaction(pending.toString())
        val client = BuildConfig.OIDC_CLIENT + if (BuildConfig.DEBUG) "-debug" else ""
        val uri = Uri.parse("$server/api/oidc/mobile").buildUpon().appendQueryParameter("client", client)
            .appendQueryParameter("challenge", challenge).build()
        context.startActivity(Intent(Intent.ACTION_VIEW, uri).addCategory(Intent.CATEGORY_BROWSABLE))
    }

    suspend fun finish(uri: Uri, prefs: PreferencesRepository) = withContext(Dispatchers.IO) {
        require(uri.scheme == BuildConfig.APPLICATION_ID && uri.authority == "oidc" && uri.path == "/callback")
        val code = requireNotNull(uri.getQueryParameter("code"))
        val transaction = requireNotNull(prefs.browserTransaction())
        val pending = JSONObject(requireNotNull(SessionVault.decrypt(transaction)))
        require(pending.getLong("expires") >= System.currentTimeMillis())
        val server = pending.getString("server")
        val body = JSONObject().put("code", code).put("verifier", pending.getString("verifier")).toString()
        val request = Request.Builder().url("$server/api/oidc/exchange")
            .post(body.toRequestBody("application/json".toMediaType())).build()
        http.newCall(request).execute().use {
            check(it.isSuccessful)
            val session = JSONObject(it.body.string())
            prefs.saveLogin(server, session.getString("username"), session.getString("userId"), session.getString("sessionId"), transaction)
        }
    }
}
