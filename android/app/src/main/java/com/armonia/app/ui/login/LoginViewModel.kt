package com.armonia.app.ui.login

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.armonia.app.data.api.LoginRequest
import kotlinx.coroutines.flow.first
import com.armonia.app.data.api.ArmoniaApi
import com.armonia.app.data.repository.PreferencesRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import android.content.Context
import com.armonia.app.security.BrowserLogin
import javax.inject.Inject

@HiltViewModel
class LoginViewModel @Inject constructor(
    private val api: ArmoniaApi,
    private val prefs: PreferencesRepository
) : ViewModel() {

    var serverUrl by mutableStateOf("")
    var username by mutableStateOf("")
    var password by mutableStateOf("")
    var isLoading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    init {
        viewModelScope.launch {
            prefs.serverUrl.first()?.let { if (it.isNotEmpty()) serverUrl = it }
            prefs.lastUsername.first()?.let { if (it.isNotEmpty()) username = it }
        }
    }

    fun startBrowserLogin(context: Context) {
        viewModelScope.launch {
            try { BrowserLogin.start(context, serverUrl, prefs) }
            catch (_: Exception) { error = "No se ha podido abrir el navegador" }
        }
    }

    fun login(onSuccess: () -> Unit) {
        val url = serverUrl.trim()
        if (url.isEmpty()) {
            error = "Falta la URL del servidor"
            return
        }
        
        if (BrowserLogin.origin(url) == null) {
            error = "Introduce el origen del servidor con HTTPS (HTTP disponible en debug)"
            return
        }

        isLoading = true
        error = null

        viewModelScope.launch {
            try {
                prefs.saveServerUrl(url)
                val response = api.login(LoginRequest(username, password))
                if (response.isSuccessful) {
                    response.body()?.sessionId?.let {
                        val account = requireNotNull(response.body())
                        prefs.saveLogin(url, account.username ?: username, requireNotNull(account.userId), it)
                        password = ""
                        onSuccess()
                    } ?: run {
                        error = "No se pudo iniciar sesion: el servidor no ha devuelto una sesion"
                    }
                } else {
                    error = loginErrorMessage(response.code())
                }
            } catch (e: Exception) {
                error = "No se puede conectar con $url (${e.message ?: e.javaClass.simpleName})"
            } finally {
                isLoading = false
            }
        }
    }
}
