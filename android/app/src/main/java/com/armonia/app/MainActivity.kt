package com.armonia.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.SystemBarStyle
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.launch
import com.armonia.app.data.repository.PreferencesRepository
import com.armonia.app.ui.login.LoginScreen
import com.armonia.app.ui.main.MainScreen
import com.armonia.app.ui.theme.ArmoniaTheme
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    @Inject
    lateinit var prefs: PreferencesRepository

    @Inject
    lateinit var warmer: com.armonia.app.playback.ConnectionWarmer

    override fun onCreate(savedInstanceState: Bundle?) {
        // Armonía is always dark: ask for light icons on both system bars instead of following the
        // phone's theme, which left the clock and battery dark-on-dark on a phone in light mode.
        val bars = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT)
        enableEdgeToEdge(statusBarStyle = bars, navigationBarStyle = bars)
        super.onCreate(savedInstanceState)
        // While Armonía is on screen, keep the connection to the server ready for the next tap.
        lifecycleScope.launch { repeatOnLifecycle(Lifecycle.State.STARTED) { warmer.keepWarm() } }
        setContent {
            ArmoniaTheme {
                val sessionId by prefs.sessionId.collectAsState(initial = null)
                
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    if (sessionId == null) {
                        LoginScreen(onLoginSuccess = {
                            // Navigation to main content will happen via sessionId state change
                        })
                    } else {
                        MainScreen()
                    }
                }
            }
        }
    }
}
