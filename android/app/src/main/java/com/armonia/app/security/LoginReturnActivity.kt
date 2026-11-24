package com.armonia.app.security

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.lifecycle.lifecycleScope
import com.armonia.app.AppEntry
import com.armonia.app.data.repository.PreferencesRepository
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.launch
import javax.inject.Inject

@AndroidEntryPoint
class LoginReturnActivity : ComponentActivity() {
    @Inject lateinit var prefs: PreferencesRepository

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        lifecycleScope.launch {
            try {
                BrowserLogin.finish(requireNotNull(intent.data), prefs)
                AppEntry.restart(this@LoginReturnActivity)
            } catch (_: Exception) {
                Toast.makeText(this@LoginReturnActivity, "No se pudo completar el acceso con Authentik", Toast.LENGTH_LONG).show()
            } finally {
                finish()
            }
        }
    }
}
