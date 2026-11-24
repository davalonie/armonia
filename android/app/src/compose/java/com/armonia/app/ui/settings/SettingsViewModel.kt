package com.armonia.app.ui.settings

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.armonia.app.data.api.ArmoniaApi
import com.armonia.app.data.api.StatsResponse
import com.armonia.app.data.repository.PreferencesRepository
import com.armonia.app.offline.OfflineManager
import com.armonia.app.playback.StreamCache
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val musicApi: com.armonia.app.homelab.MusicApi,
    private val api: ArmoniaApi,
    private val prefs: PreferencesRepository,
    private val streamCache: StreamCache,
    private val offline: OfflineManager,
    val musicPlayer: com.armonia.app.playback.MusicPlayer,
    connectionLog: com.armonia.app.auto.AutoConnectionLog,
    @dagger.hilt.android.qualifiers.ApplicationContext private val context: android.content.Context,
) : ViewModel() {

    var linked by mutableStateOf<Boolean?>(null)
        private set
    var linkError by mutableStateOf(false)
        private set
    var linking by mutableStateOf(false)
        private set
    fun refreshLink() = viewModelScope.launch {
        linkError = false
        linked = runCatching { musicApi.linkStatus().body()?.get("linked") }.getOrNull()
        linkError = linked == null
    }
    fun link(username: String, password: String) {
        if (linking) return
        linking = true
        viewModelScope.launch {
            val ok = runCatching {
                musicApi.link(prefs.cachedUserId, com.armonia.app.homelab.AccountLink(username, password)).isSuccessful
            }.getOrDefault(false)
            if (ok) linked = true
            linkError = !ok
            linking = false
        }
    }

    // ── Reproduccion ──────────────────────────────────────────────────────────
    val continueSimilar = musicPlayer.continueSimilar
    var playbackSettingError by mutableStateOf<String?>(null)
        private set
    var savingPlaybackSetting by mutableStateOf(false)
        private set

    fun setContinueSimilar(on: Boolean) {
        if (savingPlaybackSetting) return
        savingPlaybackSetting = true
        playbackSettingError = null
        viewModelScope.launch {
            if (!musicPlayer.setContinueSimilar(on)) playbackSettingError = "No se pudo guardar el ajuste. Se mantiene como estaba."
            savingPlaybackSetting = false
        }
    }

    // ── Android Auto ──────────────────────────────────────────────────────────
    val autoConnections = connectionLog.entries

    /** True when Android may stop Armonia in the background (battery optimisation on). */
    var batteryOptimized by mutableStateOf(false)
        private set
    /** True when the user has restricted Armonia's background activity entirely. */
    var backgroundRestricted by mutableStateOf(false)
        private set

    fun refreshBatteryState() {
        val pm = context.getSystemService(android.os.PowerManager::class.java)
        batteryOptimized = pm?.isIgnoringBatteryOptimizations(context.packageName) == false
        backgroundRestricted = android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.P &&
            context.getSystemService(android.app.ActivityManager::class.java)?.isBackgroundRestricted == true
    }

    fun appSettingsIntent(): android.content.Intent =
        android.content.Intent(
            android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
            android.net.Uri.fromParts("package", context.packageName, null),
        )

    var stats by mutableStateOf<StatsResponse?>(null)
    var statsLoading by mutableStateOf(true)
    var statsError by mutableStateOf<String?>(null)

    var rescanLoading by mutableStateOf(false)
    var rescanMessage by mutableStateOf<String?>(null)

    var searchSource by mutableStateOf("youtube_music")
        private set

    var cacheMaxMb by mutableStateOf(PreferencesRepository.DEFAULT_CACHE_MAX_MB)
        private set
    var cacheUsedBytes by mutableStateOf(0L)
        private set
    var dataSaver by mutableStateOf(com.armonia.app.playback.DataSaver.DEFAULT)
        private set
    var keepOnWifi by mutableStateOf(true)
        private set
    var dataUsage by mutableStateOf<com.armonia.app.playback.DataUsage.Month?>(null)
        private set
    var cacheClearing by mutableStateOf(false)
        private set
    var offlineUsedBytes by mutableStateOf(0L)
        private set
    var offlineCollections by mutableStateOf(0)
        private set

    init {
        refreshLink()
        loadStats()
        loadCacheUsage()
        viewModelScope.launch {
            prefs.searchSource.collect { searchSource = it }
        }
        viewModelScope.launch {
            prefs.cacheMaxMb.collect { cacheMaxMb = it }
        }
        viewModelScope.launch {
            prefs.dataSaver.collect { dataSaver = it }
        }
        viewModelScope.launch {
            prefs.keepOnWifi.collect { keepOnWifi = it }
        }
    }

    fun updateDataSaver(choice: com.armonia.app.playback.DataSaver) {
        viewModelScope.launch { prefs.saveDataSaver(choice) }
    }

    fun updateKeepOnWifi(enabled: Boolean) {
        viewModelScope.launch { prefs.saveKeepOnWifi(enabled) }
    }

    fun updateCacheMaxMb(mb: Long) {
        viewModelScope.launch { prefs.saveCacheMaxMb(mb) }
    }

    fun loadCacheUsage() {
        viewModelScope.launch {
            dataUsage = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                com.armonia.app.playback.DataUsage.thisMonth(context)
            }
            cacheUsedBytes = try { streamCache.usedBytes() } catch (_: Exception) { 0L }
            offlineUsedBytes = try { offline.sizeBytes() } catch (_: Exception) { 0L }
            offlineCollections = offline.catalog.value.collections.size
        }
    }

    fun removeAllOffline() {
        viewModelScope.launch {
            try { offline.removeAll() } catch (_: Exception) {}
            loadCacheUsage()
        }
    }

    fun clearCache() {
        cacheClearing = true
        viewModelScope.launch {
            try { streamCache.clear() } catch (_: Exception) {}
            cacheClearing = false
            loadCacheUsage()
        }
    }

    fun updateSearchSource(source: String) {
        viewModelScope.launch { prefs.saveSearchSource(source) }
    }

    fun loadStats() {
        statsLoading = true
        statsError = null
        viewModelScope.launch {
            try {
                val r = api.getStats()
                if (r.isSuccessful) stats = r.body()
                else statsError = "No se pudieron cargar las estadisticas"
            } catch (e: Exception) {
                statsError = e.message
            } finally {
                statsLoading = false
            }
        }
    }

    fun rescan() {
        rescanLoading = true
        rescanMessage = null
        viewModelScope.launch {
            try {
                val r = api.rescan()
                rescanMessage = if (r.isSuccessful) "Escaneo de la biblioteca iniciado" else "El escaneo ha fallado"
            } catch (e: Exception) {
                rescanMessage = "El escaneo ha fallado: ${e.message}"
            } finally {
                rescanLoading = false
            }
        }
    }

    fun logout(onDone: () -> Unit) {
        viewModelScope.launch {
            try { api.logout() } catch (_: Exception) {}
            prefs.clearSession()
            onDone()
        }
    }
}
