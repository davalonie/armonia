package com.armonia.app.data.repository

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import javax.inject.Inject
import javax.inject.Singleton
import com.armonia.app.security.AccountScope
import com.armonia.app.security.SessionVault

private val Context.dataStore by preferencesDataStore(name = "settings")

data class AuthSnapshot(val serverUrl:String="",val username:String="",val userId:String="",val sessionId:String="") {
    val namespace:String get()=AccountScope.namespace(serverUrl,userId)

    fun coverArtUrl(id: String, size: Int): String =
        if (id.startsWith("https://") || id.startsWith("http://")) id
        else "${serverUrl.trimEnd('/')}/api/library/getCoverArt?id=${android.net.Uri.encode(id)}&size=$size&account=$namespace"
}

@Singleton
class PreferencesRepository @Inject constructor(
    @ApplicationContext private val context: Context
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private object Keys {
        val SERVER_URL = stringPreferencesKey("server_url")
        val OIDC_TRANSACTION = stringPreferencesKey("oidc_transaction")
        val USER_ID = stringPreferencesKey("native_user_id")
        val SESSION_ID = stringPreferencesKey("session_id")
        val LAST_TRACK_JSON = stringPreferencesKey("last_track_json")
        val SEARCH_SOURCE = stringPreferencesKey("search_source")
        val LAST_USERNAME = stringPreferencesKey("last_username")
        val CACHE_MAX_MB = longPreferencesKey("cache_max_mb")
        val SEARCH_HISTORY = stringPreferencesKey("search_history")
        val DATA_SAVER = stringPreferencesKey("data_saver")
        val KEEP_ON_WIFI = booleanPreferencesKey("keep_on_wifi")
        val PREVIEW_COPIES = stringPreferencesKey("preview_copies")
    }

    val serverUrl: Flow<String?> = context.dataStore.data.map { it[Keys.SERVER_URL] }
    val sessionId: Flow<String?> = context.dataStore.data.map { if (it[Keys.USER_ID].isNullOrBlank()) null else SessionVault.decrypt(it[Keys.SESSION_ID]) }
    val lastTrackJson: Flow<String?> = context.dataStore.data.map { it[Keys.LAST_TRACK_JSON] }
    val searchSource: Flow<String> = context.dataStore.data.map { it[Keys.SEARCH_SOURCE] ?: "youtube_music" }
    val userId: Flow<String?> = context.dataStore.data.map { it[Keys.USER_ID] }
    val lastUsername: Flow<String?> = context.dataStore.data.map { it[Keys.LAST_USERNAME] }
    /** Recent YouTube / YouTube Music searches, newest first. */
    val searchHistory: Flow<List<String>> = context.dataStore.data.map { decodeSearchHistory(it[Keys.SEARCH_HISTORY]) }

    /** Size limit of the on-device stream cache, in MB. */
    val cacheMaxMb: Flow<Long> = context.dataStore.data.map { it[Keys.CACHE_MAX_MB] ?: DEFAULT_CACHE_MAX_MB }

    /** "Ahorro de datos": no, on mobile data (default) or always; a bad connection saves anyway (DataSaving). */
    val dataSaver: Flow<com.armonia.app.playback.DataSaver> =
        context.dataStore.data.map { com.armonia.app.playback.DataSaver.of(it[Keys.DATA_SAVER]) }

    /** On Wi-Fi, keep the weekly list, favourites and most played on the phone (CachePrefill); on by default. */
    val keepOnWifi: Flow<Boolean> = context.dataStore.data.map { it[Keys.KEEP_ON_WIFI] ?: true }

    val authState: Flow<AuthSnapshot> = context.dataStore.data.map {
        val id=it[Keys.USER_ID]?:""
        AuthSnapshot(it[Keys.SERVER_URL]?:"",it[Keys.LAST_USERNAME]?:"",id,
            if(id.isBlank()) "" else SessionVault.decrypt(it[Keys.SESSION_ID])?:"")
    }
    @Volatile var cachedAuth=AuthSnapshot();private set
    val cachedServerUrl:String get()=cachedAuth.serverUrl
    val cachedSessionId:String get()=cachedAuth.sessionId
    val cachedUsername:String get()=cachedAuth.username
    val cachedUserId:String get()=cachedAuth.userId
    val accountNamespace:String get()=cachedAuth.namespace
    init { scope.launch { authState.collect { cachedAuth=it } } }

    suspend fun storeBrowserTransaction(transaction: String) {
        context.dataStore.edit { it[Keys.OIDC_TRANSACTION] = SessionVault.encrypt(transaction) }
    }

    suspend fun browserTransaction(): String? = context.dataStore.data.first()[Keys.OIDC_TRANSACTION]

    suspend fun saveLogin(server: String, username: String, userId: String, sessionId: String, transaction: String? = null) {
        require(userId.isNotBlank() && sessionId.isNotBlank())
        val encrypted = SessionVault.encrypt(sessionId)
        context.dataStore.edit {
            if (transaction != null) {
                check(it[Keys.OIDC_TRANSACTION] == transaction && it[Keys.SESSION_ID].isNullOrBlank())
            }
            it.remove(Keys.OIDC_TRANSACTION)
            if (it[Keys.SERVER_URL]?.trimEnd('/') != server.trimEnd('/') || it[Keys.USER_ID] != userId) {
                it.remove(Keys.LAST_TRACK_JSON)
                it.remove(Keys.SEARCH_HISTORY)
                it.remove(Keys.PREVIEW_COPIES)
            }
            it[Keys.SERVER_URL] = server
            it[Keys.LAST_USERNAME] = username
            it[Keys.USER_ID] = userId
            it[Keys.SESSION_ID] = encrypted
        }
        cachedAuth = AuthSnapshot(server, username, userId, sessionId)
    }

    suspend fun saveServerUrl(url: String) {
        if (cachedServerUrl != url) clearSession()
        context.dataStore.edit { it[Keys.SERVER_URL] = url }
        cachedAuth = cachedAuth.copy(serverUrl=url)
    }

    suspend fun saveIdentity(id: String) {
        require(id.isNotBlank())
        if(cachedUserId != id) clearSession()
        context.dataStore.edit { it[Keys.USER_ID] = id }
        cachedAuth = cachedAuth.copy(userId=id)
    }

    suspend fun saveSessionId(id: String) {
        context.dataStore.edit { it[Keys.SESSION_ID] = SessionVault.encrypt(id) }
        cachedAuth = cachedAuth.copy(sessionId=id)
    }

    /** Compare within DataStore's transaction: an old HTTP failure cannot erase a new login. */
    suspend fun clearSessionIfCurrent(failedSession: String) {
        if (failedSession.isBlank()) return
        context.dataStore.edit {
            if (SessionVault.decrypt(it[Keys.SESSION_ID]) == failedSession) {
                it.remove(Keys.SESSION_ID)
                it.remove(Keys.LAST_TRACK_JSON)
                it.remove(Keys.SEARCH_HISTORY)
                it.remove(Keys.PREVIEW_COPIES)
            }
        }
        // authState updates the in-memory snapshot from the committed state.
    }

    suspend fun clearSession() {
        cachedAuth = cachedAuth.copy(sessionId="")
        context.dataStore.edit {
            it.remove(Keys.SESSION_ID)
            it.remove(Keys.OIDC_TRANSACTION)
            it.remove(Keys.LAST_TRACK_JSON)
            it.remove(Keys.SEARCH_HISTORY)
            it.remove(Keys.PREVIEW_COPIES)
        }
    }

    /** Library copies of downloaded previews (PreviewCopies); like the search history, gone when the session ends. */
    suspend fun previewCopies(): String? = context.dataStore.data.first()[Keys.PREVIEW_COPIES]

    suspend fun savePreviewCopies(raw: String) {
        context.dataStore.edit { it[Keys.PREVIEW_COPIES] = raw }
    }

    suspend fun saveLastTrack(json: String) {
        context.dataStore.edit { it[Keys.LAST_TRACK_JSON] = json }
    }

    suspend fun saveSearchSource(source: String) {
        context.dataStore.edit { it[Keys.SEARCH_SOURCE] = source }
    }

    suspend fun saveLastUsername(username: String) {
        if (cachedUsername != username) clearSession()
        context.dataStore.edit { it[Keys.LAST_USERNAME] = username }
        cachedAuth = cachedAuth.copy(username=username)
    }

    suspend fun clearLastTrack() {
        context.dataStore.edit { it.remove(Keys.LAST_TRACK_JSON) }
    }

    suspend fun recordSearch(query: String) {
        context.dataStore.edit { it[Keys.SEARCH_HISTORY] = encodeSearchHistory(addToSearchHistory(decodeSearchHistory(it[Keys.SEARCH_HISTORY]), query)) }
    }

    suspend fun removeSearch(query: String) {
        context.dataStore.edit { prefs ->
            prefs[Keys.SEARCH_HISTORY] = encodeSearchHistory(decodeSearchHistory(prefs[Keys.SEARCH_HISTORY]).filterNot { it == query })
        }
    }

    suspend fun clearSearchHistory() {
        context.dataStore.edit { it.remove(Keys.SEARCH_HISTORY) }
    }

    suspend fun saveCacheMaxMb(mb: Long) {
        context.dataStore.edit { it[Keys.CACHE_MAX_MB] = mb }
    }

    suspend fun saveDataSaver(choice: com.armonia.app.playback.DataSaver) {
        context.dataStore.edit { it[Keys.DATA_SAVER] = choice.pref }
    }

    suspend fun saveKeepOnWifi(enabled: Boolean) {
        context.dataStore.edit { it[Keys.KEEP_ON_WIFI] = enabled }
    }

    companion object {
        // 4 GB: about 1100 songs of this library kept without their covers, so what is played often (and what
        // is kept on Wi-Fi, CachePrefill) plays without data. It was 1 GB (about 260 songs) until 0.5.3.
        const val DEFAULT_CACHE_MAX_MB = 4096L
    }
}
