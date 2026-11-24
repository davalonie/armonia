package com.armonia.app.ui.login

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
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
        isLoading = true
        error = null
        viewModelScope.launch {
            try {
                error = com.armonia.app.security.PasswordLogin.signIn(api, prefs, serverUrl, username, password)
                if (error == null) {
                    password = ""
                    onSuccess()
                }
            } finally {
                isLoading = false
            }
        }
    }
}
