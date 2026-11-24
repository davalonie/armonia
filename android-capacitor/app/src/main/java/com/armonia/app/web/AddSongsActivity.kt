package com.armonia.app.web

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import com.armonia.app.data.repository.PreferencesRepository
import com.armonia.app.ui.playlists.AddSongsScreen
import com.armonia.app.ui.playlists.PlaylistDetailViewModel
import com.armonia.app.ui.theme.ArmoniaTheme
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

@AndroidEntryPoint
class AddSongsActivity : ComponentActivity() {
    @Inject lateinit var prefs: PreferencesRepository
    private val editor: PlaylistDetailViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val account = intent.getStringExtra("account")
        setContent {
            val session by prefs.authState.collectAsState(initial = null)
            val auth = session
            if (auth != null) {
                if (account != auth.namespace || auth.sessionId.isBlank()) {
                    LaunchedEffect(Unit) { finish() }
                } else ArmoniaTheme {
                    LaunchedEffect(Unit) { editor.load() }
                    Box(Modifier.safeDrawingPadding()) {
                        AddSongsScreen(onBack = { finish() }, viewModel = editor)
                    }
                }
            }
        }
    }
}
