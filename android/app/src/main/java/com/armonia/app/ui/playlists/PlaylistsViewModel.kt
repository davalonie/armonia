package com.armonia.app.ui.playlists

import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.armonia.app.data.api.ImportRequest
import com.armonia.app.data.api.ImportStatusResponse
import com.armonia.app.data.api.ArmoniaApi
import com.armonia.app.data.api.Playlist
import com.armonia.app.data.repository.LibraryRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import javax.inject.Inject

@HiltViewModel
class PlaylistsViewModel @Inject constructor(
    private val repository: LibraryRepository,
    private val music: com.armonia.app.homelab.MusicApi,
    private val prefs: com.armonia.app.data.repository.PreferencesRepository,
    private val api: ArmoniaApi,
) : ViewModel() {

    var mixed by mutableStateOf<List<com.armonia.app.homelab.MixedSummary>>(emptyList()); private set
    val username get() = prefs.cachedUsername
    var playlists by mutableStateOf<List<Playlist>>(emptyList())
    var filter by mutableStateOf("")
    var isLoading by mutableStateOf(true)
    var error by mutableStateOf<String?>(null)
    /** Showing the copy saved on the phone because the server could not be reached. */
    var stale by mutableStateOf(false)
        private set

    // ── Playlist import ──────────────────────────────────────────────────────
    var importProgress by mutableStateOf<ImportStatusResponse?>(null)
        private set
    var importStarting by mutableStateOf(false)
        private set
    var importStartError by mutableStateOf<String?>(null)

    val filtered by derivedStateOf {
        if (filter.isBlank()) playlists
        else playlists.filter { com.armonia.app.ui.components.matchesSearch(filter, it.name) }
    }

    init { load() }

    /**
     * Shows at once what the phone remembers and asks the server behind it, so a change made on
     * another device appears without waiting for it. The progress wheel is only for an empty
     * screen or a refresh the user pulled.
     */
    fun load(pulled: Boolean = false) {
        error = null
        viewModelScope.launch {
            if (playlists.isEmpty()) repository.cachedPlaylists()?.let { playlists = it }
            isLoading = pulled || playlists.isEmpty()
            repository.getPlaylists()
                .onSuccess { playlists = it.playlists?.playlist ?: emptyList(); stale = false }
                .onFailure { if (playlists.isEmpty()) error = it.message else stale = true }
            isLoading = false
            runCatching { music.playlists().body()?.playlists }.getOrNull()?.let { mixed = it }
        }
    }

    /** Mixed lists are edited and deleted on their own screen: Biblioteca asks for them again when it comes back. */
    fun refreshMixed() {
        viewModelScope.launch { runCatching { music.playlists().body()?.playlists }.getOrNull()?.let { mixed = it } }
    }

    fun coverUrl(id: String) = repository.getCoverArtUrl(id, 128)

    fun uploadCover(kind: String, id: String, owner: String, open: () -> java.io.InputStream?) {
        viewModelScope.launch {
            try {
                check(owner == prefs.cachedUserId)
                val bytes = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                    val limit = 8 * 1024 * 1024
                    requireNotNull(open()).use { input ->
                        val out = java.io.ByteArrayOutputStream()
                        val buffer = ByteArray(16 * 1024)
                        while (true) {
                            val n = input.read(buffer)
                            if (n < 0) break
                            require(out.size() + n <= limit) { "La imagen debe ocupar como maximo 8 MiB" }
                            out.write(buffer, 0, n)
                        }
                        out.toByteArray()
                    }
                }
                val response = music.uploadCover(kind, id, owner, bytes.toRequestBody("application/octet-stream".toMediaType()))
                check(response.isSuccessful) { "El servidor rechazo la portada (${response.code()})" }
                if (owner == prefs.cachedUserId) load()
            } catch (e: Exception) {
                if (owner == prefs.cachedUserId) error = e.message ?: "No se pudo guardar la portada"
            }
        }
    }
    val ownerId get() = prefs.cachedUserId

    fun create(name: String) {
        val trimmed = name.trim()
        if (trimmed.isBlank()) return
        viewModelScope.launch {
            repository.createPlaylist(trimmed)
                .onSuccess { load() }
                .onFailure { error = "No se pudo crear la playlist: ${it.message}" }
        }
    }

    fun rename(id: String, newName: String) {
        val trimmed = newName.trim()
        if (trimmed.isBlank()) return
        viewModelScope.launch {
            repository.renamePlaylist(id, trimmed)
                .onSuccess { load() }
                .onFailure { error = "No se pudo cambiar el nombre: ${it.message}" }
        }
    }

    fun delete(id: String) {
        // Optimistic remove
        playlists = playlists.filter { it.id != id }
        viewModelScope.launch {
            repository.deletePlaylist(id)
                .onFailure { error = "No se pudo eliminar la playlist: ${it.message}"; load() }
        }
    }

    fun startImport(url: String) {
        val u = url.trim()
        if (u.isBlank() || importStarting) return
        importStarting = true
        importStartError = null
        viewModelScope.launch {
            try {
                val resp = api.importSpotify(ImportRequest(u))
                if (resp.isSuccessful && resp.body() != null) {
                    val b = resp.body()!!
                    importProgress = ImportStatusResponse(
                        importId = b.importId, name = b.name, status = "running",
                        total = b.total, current = 0, downloaded = 0, existing = 0,
                        failed = 0, playlistId = null, error = null, failures = emptyList(),
                    )
                    pollImport(b.importId)
                } else {
                    importStartError = parseDetail(resp.errorBody()?.string()) ?: "La importacion ha fallado (${resp.code()})"
                }
            } catch (e: Exception) {
                importStartError = e.message ?: "La importacion ha fallado"
            } finally {
                importStarting = false
            }
        }
    }

    private fun pollImport(id: String) {
        viewModelScope.launch {
            while (true) {
                delay(1500)
                val resp = try { api.importStatus(id) } catch (e: Exception) { break }
                if (!resp.isSuccessful || resp.body() == null) break
                val b = resp.body()!!
                importProgress = b
                if (b.status != "running") {
                    if (b.status == "done") load()
                    break
                }
            }
        }
    }

    fun dismissImport() { importProgress = null }

    private fun parseDetail(body: String?): String? =
        try { body?.let { JSONObject(it).optString("detail").ifBlank { null } } } catch (e: Exception) { null }
}
