package com.armonia.app.web

import android.content.Intent
import android.os.Bundle
import com.armonia.app.data.api.ArmoniaApi
import com.armonia.app.data.repository.PreferencesRepository
import com.getcapacitor.BridgeActivity
import com.getcapacitor.CapConfig
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

/**
 * The sign-in page of the web interface. It has its own local origin, apart from every account's,
 * and only the sign-in plugin: nothing of an account is reachable from here.
 */
@AndroidEntryPoint
class LoginActivity : BridgeActivity() {
    @Inject lateinit var prefs: PreferencesRepository
    @Inject lateinit var api: ArmoniaApi

    override fun onCreate(savedInstanceState: Bundle?) {
        config = CapConfig.Builder(this).setHostname("login.armonia.local").setAndroidScheme("https")
            .setLoggingEnabled(false).create()
        registerPlugin(LoginPlugin::class.java)
        super.onCreate(savedInstanceState)
    }

    /** Signed in with a password: on to that account's library. (Authentik returns through LoginReturnActivity.) */
    fun openLibrary() {
        startActivity(Intent(this, LibraryActivity::class.java).putExtra("account", prefs.cachedAuth.namespace))
        finish()
    }
}
