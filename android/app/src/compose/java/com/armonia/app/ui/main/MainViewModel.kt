package com.armonia.app.ui.main

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.armonia.app.data.api.ArmoniaApi
import com.armonia.app.data.repository.PreferencesRepository
import com.armonia.app.playback.MusicPlayer
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class MainViewModel @Inject constructor(
    val musicPlayer: MusicPlayer,
    private val prefs: PreferencesRepository,
    private val api: ArmoniaApi,
    val downloadTracker: com.armonia.app.data.repository.DownloadTracker,
    val libraryRepository: com.armonia.app.data.repository.LibraryRepository,
    val playbackNotices: com.armonia.app.playback.PlaybackNotices,
) : ViewModel() {

    init {
        // Probe the stored session once on launch. A 401 here is picked up by the
        // auth interceptor, which clears the session so MainActivity swaps back to
        // the login screen instead of every tab quietly loading nothing.
        viewModelScope.launch {
            try { api.me() } catch (_: Exception) { /* offline: keep the session */ }
        }
    }

    suspend fun failedDownloads(): Int = try {
        api.listDownloads().body()?.downloads.orEmpty().count { it.status == "error" || it.status == "timeout" }
    } catch (_: java.io.IOException) { 0 }

    fun logout(onSuccess: () -> Unit) {
        viewModelScope.launch {
            libraryRepository.forgetCachedPlaylists()
            prefs.clearSession()
            onSuccess()
        }
    }
}
