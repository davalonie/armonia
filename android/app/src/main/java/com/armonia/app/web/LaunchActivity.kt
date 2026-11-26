package com.armonia.app.web

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.lifecycle.lifecycleScope
import com.armonia.app.data.repository.PreferencesRepository
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import javax.inject.Inject

/** The launcher entry: the library of the signed-in account, or the sign-in page. It shows nothing itself. */
@AndroidEntryPoint
class LaunchActivity : ComponentActivity() {
    @Inject lateinit var prefs: PreferencesRepository

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        lifecycleScope.launch {
            val auth = prefs.authState.first()
            startActivity(
                if (auth.sessionId.isBlank()) Intent(this@LaunchActivity, LoginActivity::class.java)
                else Intent(this@LaunchActivity, LibraryActivity::class.java).putExtra("account", auth.namespace)
            )
            finish()
        }
    }
}
