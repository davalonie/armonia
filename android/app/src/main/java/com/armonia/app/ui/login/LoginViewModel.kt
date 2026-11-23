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
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
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

    fun login(onSuccess: () -> Unit) {
        val url = serverUrl.trim()
        if (url.isEmpty()) {
            error = "Falta la URL del servidor"
            return
        }
        
        val parsed = url.toHttpUrlOrNull()
        if (parsed == null || parsed.username.isNotEmpty() || parsed.password.isNotEmpty() ||
            parsed.encodedPath != "/" || parsed.query != null || parsed.fragment != null) {
            error = "URL del servidor no valida"
            return
        }
        if(!com.armonia.app.BuildConfig.DEBUG && !parsed.isHttps) {
            error="Usa HTTPS para proteger las credenciales, tambien en LAN/Tailscale"
            return
        }

        isLoading = true
        error = null

        viewModelScope.launch {
            try {
                prefs.saveServerUrl(url)
                // Note: In a real app, we might need to recreate the Retrofit instance 
                // if the base URL changes, or use a dynamic base URL interceptor.
                
                val response = api.login(LoginRequest(username, password))
                if (response.isSuccessful) {
                    response.body()?.sessionId?.let {
                        prefs.saveLastUsername(response.body()?.username ?: username)
                        val identity = response.body()?.userId
                            ?: throw IllegalStateException("No se ha podido resolver la identidad de Navidrome")
                        prefs.saveIdentity(identity)
                        prefs.saveSessionId(it)
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
