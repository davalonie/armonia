package com.armonia.app.security

import com.armonia.app.data.api.ArmoniaApi
import com.armonia.app.data.api.LoginRequest
import com.armonia.app.data.repository.PreferencesRepository

/** Sign-in with the music account's password. Each interface only collects the three fields. */
object PasswordLogin {
    /** Null once signed in; otherwise the message to show, as the Kotlin screen always said it. */
    suspend fun signIn(api: ArmoniaApi, prefs: PreferencesRepository, server: String, username: String, password: String): String? {
        val url = server.trim()
        if (url.isEmpty()) return "Falta la URL del servidor"
        if (BrowserLogin.origin(url) == null) return "Introduce el origen del servidor con HTTPS (HTTP disponible en debug)"
        return try {
            prefs.saveServerUrl(url)
            val response = api.login(LoginRequest(username, password))
            if (!response.isSuccessful) return loginErrorMessage(response.code())
            val account = response.body()
            val session = account?.sessionId ?: return "No se pudo iniciar sesion: el servidor no ha devuelto una sesion"
            prefs.saveLogin(url, account.username ?: username, requireNotNull(account.userId), session)
            null
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            "No se puede conectar con $url (${e.message ?: e.javaClass.simpleName})"
        }
    }
}
