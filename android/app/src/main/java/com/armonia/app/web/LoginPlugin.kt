package com.armonia.app.web

import androidx.lifecycle.lifecycleScope
import com.armonia.app.security.BrowserLogin
import com.armonia.app.security.PasswordLogin
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/** What the sign-in page needs from the phone: the last server and user, and the two ways in. */
@CapacitorPlugin(name = "ArmoniaLogin")
class LoginPlugin : Plugin() {
    private val screen get() = activity as LoginActivity

    @PluginMethod fun defaults(call: PluginCall) {
        screen.lifecycleScope.launch {
            call.resolve(JSObject().put("server", screen.prefs.serverUrl.first().orEmpty())
                .put("username", screen.prefs.lastUsername.first().orEmpty()))
        }
    }

    @PluginMethod fun authentik(call: PluginCall) {
        screen.lifecycleScope.launch {
            call.resolve(JSObject().put("enabled", BrowserLogin.available(call.getString("server").orEmpty())))
        }
    }

    @PluginMethod fun signIn(call: PluginCall) {
        screen.lifecycleScope.launch {
            val error = PasswordLogin.signIn(screen.api, screen.prefs, call.getString("server").orEmpty(),
                call.getString("username").orEmpty(), call.getString("password").orEmpty())
            if (error != null) call.reject(error)
            else { call.resolve(); screen.openLibrary() }
        }
    }

    @PluginMethod fun browserSignIn(call: PluginCall) {
        screen.lifecycleScope.launch {
            try {
                BrowserLogin.start(screen, call.getString("server").orEmpty(), screen.prefs)
                call.resolve()
            } catch (_: Exception) { call.reject("No se ha podido abrir el navegador") }
        }
    }
}
