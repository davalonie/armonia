package com.armonia.app.web

import android.app.ActivityManager
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.lifecycle.lifecycleScope
import com.armonia.app.auto.controllerLabel
import com.armonia.app.playback.DataSaver
import com.armonia.app.playback.DataUsage
import com.armonia.app.data.repository.DownloadEvent
import kotlinx.coroutines.flow.merge
import kotlinx.coroutines.flow.first
import com.armonia.app.data.api.Song
import com.armonia.app.data.repository.AuthSnapshot
import com.armonia.app.homelab.MusicTrack
import com.armonia.app.homelab.asMusicTrack
import com.armonia.app.homelab.canKeepOffline
import com.armonia.app.offline.OfflineSongState
import com.armonia.app.offline.OfflineCollection
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject

@CapacitorPlugin(name = "Armonia")
class MusicPlugin : Plugin() {
    private val screen get() = activity as LibraryActivity
    private var lastQueue: List<Song>? = null
    private var previousDownloads: Map<String, OfflineSongState>? = null
    private var downloadsRevision = 0
    private var lastOrder: List<Int>? = null
    private var lastPicked: Set<Int>? = null
    private var lastAuto: Set<String>? = null
    private var lastPlaylist: Triple<String?, String?, String?>? = null
    private var previousServerDownloads: Map<String, com.armonia.app.data.repository.TrackedDownload>? = null
    private var serverDownloadRevision = 0
    private var revision = 0

    override fun load() {
        screen.lifecycleScope.launch {
            screen.downloadTracker.events.collect { event ->
                if (screen.prefs.accountNamespace == screen.account) {
                    val message = when(event) {
                        is DownloadEvent.Added -> "«${event.title}» ya está en tu biblioteca"
                        is DownloadEvent.Failed -> "No se pudo descargar «${event.title}»: ${event.reason}"
                    }
                    notifyListeners("notice", JSObject().put("message", message).put("libraryChanged", event is DownloadEvent.Added))
                }
            }
        }
        screen.lifecycleScope.launch {
            merge(screen.notices.messages, screen.library.messages).collect { message ->
                if (screen.prefs.accountNamespace == screen.account)
                    notifyListeners("notice", JSObject().put("message", message))
            }
        }
    }

    private fun perform(call: PluginCall, checkAfter: Boolean = true, action: suspend () -> JSObject) {
        screen.lifecycleScope.launch {
            try {
                screen.auth()
                val result = action()
                if (checkAfter) screen.auth()
                call.resolve(result)
            } catch (_: Exception) {
                call.reject("No se pudo completar la operación en esta cuenta.")
            }
        }
    }

    @PluginMethod fun identity(call: PluginCall) = perform(call) {
        val session = screen.auth()
        JSObject().put("username", session.username).put("userId", session.userId)
            .put("searchSource", screen.prefs.searchSource.first())
    }

    @PluginMethod fun request(call: PluginCall) = perform(call) {
        val session = screen.auth()
        val method = call.getString("method", "GET")!!
        val base = session.serverUrl.toHttpUrl()
        val url = requireNotNull(base.resolve(requireNotNull(call.getString("path"))))
        require(url.scheme == base.scheme && url.host == base.host && url.port == base.port && url.username.isEmpty())
        require(url.pathSegments.first() == "api" && url.pathSegments.getOrNull(1) !in setOf("login","oidc","logout"))
        require(method in setOf("GET", "POST", "PUT", "PATCH", "DELETE"))
        val body = call.getString("body")?.toRequestBody("application/json".toMediaType())
        val req = Request.Builder().url(url).tag(AuthSnapshot::class.java, session)
            .method(method, body ?: if (method in setOf("POST","PUT","PATCH")) "".toRequestBody() else null)
        if (call.getBoolean("albumGroups") == true) req.header("X-Armonia-Albums", "1")
        val result = withContext(Dispatchers.IO) {
            screen.http.newCall(req.build()).execute().use {
                JSObject().put("status", it.code).put("text", it.body.string())
            }
        }
        screen.auth()
        result
    }

    @PluginMethod fun logout(call: PluginCall) = perform(call, checkAfter = false) {
        val session = screen.auth()
        withContext(Dispatchers.IO) {
            val req = Request.Builder().url(session.serverUrl.trimEnd('/') + "/api/logout")
                .tag(AuthSnapshot::class.java, session).post("".toRequestBody()).build()
            runCatching { screen.http.newCall(req).execute().close() }
        }
        screen.player.closePlayer()
        screen.prefs.clearSessionIfCurrent(session.sessionId)
        JSObject()
    }

    private fun song(json: JSONObject): Song {
        val gson = screen.gson
        val ref = json.optJSONObject("_musicTrack")
        if (ref != null && ref.optString("source") != "navidrome") {
            val external = gson.fromJson(ref.toString(), MusicTrack::class.java).toSong()
            val thumbnail = json.optString("_previewThumb").ifBlank { return external }
            val path = Uri.parse(thumbnail).path
            val session = screen.auth()
            val cover = if (thumbnail.startsWith("/") && path?.matches(Regex("/api/home/releases/[a-f0-9-]{36}/cover")) == true)
                "${session.serverUrl.trimEnd('/')}$path?account=${session.namespace}" else thumbnail
            return external.copy(coverArt = cover)
        }
        return gson.fromJson(json.toString(), Song::class.java).also {
            require(!it.id.isNullOrBlank() && !it.title.isNullOrBlank())
        }
    }

    @PluginMethod fun command(call: PluginCall) = perform(call) {
        val player = screen.player
        val index = call.getInt("index", 0)!!
        fun track() = song(requireNotNull(call.getObject("track")))
        val result = JSObject()
        when (call.getString("action")) {
            "beginPlay" -> result.put("epoch", player.routeGuard.explicitPlay())
            "prepare" -> player.prepareSource(requireNotNull(call.getString("videoId")))
            "step" -> player.step(requireNotNull(call.getInt("direction")).also { require(it == 1 || it == -1) })
            "play" -> {
                val tracks = requireNotNull(call.getArray("tracks"))
                val list = (0 until tracks.length()).map { song(tracks.getJSONObject(it)) }
                val epoch = if (call.data.isNull("epoch")) player.routeGuard.explicitPlay() else call.data.getLong("epoch")
                player.playQueue(list, index, requestEpoch = epoch, playlistId = call.getString("playlistId"),
                    playlistKind = call.getString("kind", "local")!!, from = call.getString("from"))
            }
            "toggle" -> player.togglePlayPause()
            "next" -> player.next()
            "previous" -> player.prev()
            "seek" -> player.seekFraction(call.getDouble("fraction", 0.0)!!.toFloat())
            "shuffle" -> player.toggleShuffle()
            "repeat" -> player.toggleRepeat()
            "like" -> player.toggleLike()
            "add" -> result.put("token", player.addToQueue(track()))
            "end" -> result.put("token", player.addToEnd(track()))
            "playNext" -> result.put("token", player.playNext(track()))
            "undo" -> player.undoQueued(requireNotNull(call.getString("token")))
            "jump" -> player.jumpTo(index)
            "sleep" -> {
                when (val minutes = call.getInt("minutes")) {
                    null -> player.setSleepAtTrackEnd()
                    0 -> player.cancelSleepTimer()
                    15, 30, 45, 60 -> player.setSleepTimer(minutes)
                    else -> error("Duración no válida")
                }
                result.put("sleep", sleepState())
            }
            "remove" -> player.removeFromQueue(index)
            "move" -> player.moveInQueue(index, call.getInt("to", index)!!)
            "clear" -> player.clearUpcoming()
            "close" -> player.closePlayer()
            "audition" -> player.audition(track(), resumeAfter = call.getBoolean("resumeAfter") == true)
            "stopAudition" -> player.stopAudition(resume = call.getBoolean("resume", true) == true)
            "similar" -> check(player.setContinueSimilar(call.getBoolean("enabled") == true))
            else -> error("unknown command")
        }
        result
    }

    private fun sleepState(): JSObject {
        val timer = screen.player.sleepTimer.value
        return JSObject().put("endsAt", timer.endsAtMs).put("atEnd", timer.atTrackEnd)
    }

    @PluginMethod fun snapshot(call: PluginCall) = perform(call) {
        val player = screen.player
        val queue = player.queue.value
        val order = player.playOrder.value
        val picked = player.handPicked.value
        val automatic = player.autoSongs.value
        val context = Triple(player.playingPlaylistKind, player.playingPlaylistId.value, player.playingFrom.value)
        if (queue !== lastQueue || order !== lastOrder || picked !== lastPicked || automatic !== lastAuto || context != lastPlaylist) {
            revision++
            lastQueue = queue
            lastOrder = order
            lastPicked = picked
            lastAuto = automatic
            lastPlaylist = context
        }
        val result = JSObject()
        if (call.getInt("revision") != revision) {
            result.put("queue", JSONArray(screen.gson.toJson(queue)))
                .put("playOrder", JSONArray(order)).put("handPicked", JSONArray(picked)).put("autoSongs", JSONArray(automatic))
        }
        val states = screen.offline.songStatesFor(screen.account)
        if (states !== previousDownloads) {
            previousDownloads = states
            downloadsRevision++
        }
        result.put("downloadsRevision", downloadsRevision)
        if (call.getInt("downloadsRevision") != downloadsRevision) {
            result.put("songDownloads", JSONObject(screen.gson.toJson(states)))
        }
        result.put("sleep", sleepState())
            .put("auditionId", player.auditionId.value).put("buffering", player.buffering.value)

        val tracked = screen.downloadTracker.downloads.value
        if (tracked !== previousServerDownloads) {
            previousServerDownloads = tracked
            serverDownloadRevision++
        }
        if (call.getInt("serverDownloadRevision") != serverDownloadRevision)
            result.put("serverDownloads", JSONObject(tracked.mapValues { it.value.status }))
        result.put("serverDownloadRevision", serverDownloadRevision)
        result.put("offlineProblem", screen.offline.persistenceProblem.value)
        result.put("listenProblem", screen.listenOutbox.persistenceProblem.value)
        val progress = player.progress.value
        result.put("revision", revision).put("index", player.currentIndex.value)
            .put("position", progress.positionMs).put("duration", progress.durationMs)
            .put("playing", player.isPlaying.value).put("shuffle", player.shuffleOn.value)
            .put("repeat", player.repeatMode.value.name.lowercase()).put("similar", player.continueSimilar.value)
            .put("playlistKind", player.playingPlaylistKind).put("playlist", player.playingPlaylistId.value).put("from", player.playingFrom.value)
            .put("error", player.playbackError.value)
    }

    @PluginMethod fun deviceSettings(call: PluginCall) = perform(call) {
        val host = screen
        val account = host.auth().namespace
        val prefs = host.prefs
        val stats = withContext(Dispatchers.IO) { DataUsage.thisMonth(host) }
        val connections = JSONArray()
        host.autoConnections.entries.value.take(8).forEach {
            connections.put(JSONObject().put("at", it.timeMillis).put("name", controllerLabel(it.packageName)).put("event", it.event))
        }
        val result = JSObject().put("cacheMb", prefs.cacheMaxMb.first()).put("cacheBytes", host.streamCache.usedBytes())
            .put("wifi", prefs.keepOnWifi.first()).put("saver", prefs.dataSaver.first().pref)
            .put("offlineCount", host.offline.collectionsFor(account).size).put("offlineBytes", host.offline.sizeBytes())
            .put("connections", connections)
            .put("optimized", host.getSystemService(PowerManager::class.java)?.isIgnoringBatteryOptimizations(host.packageName) == false)
            .put("restricted", Build.VERSION.SDK_INT >= Build.VERSION_CODES.P &&
                host.getSystemService(ActivityManager::class.java)?.isBackgroundRestricted == true)
        if (stats != null) result.put("mobileBytes", stats.mobileBytes).put("wifiBytes", stats.wifiBytes)
        host.auth()
        result
    }

    @PluginMethod fun changeDeviceSetting(call: PluginCall) = perform(call) {
        val host = screen
        when (call.getString("setting")) {
            "cacheMb" -> {
                val limit = requireNotNull(call.getInt("value")).toLong()
                require(limit in setOf(1024L, 2048L, 4096L, 8192L))
                host.prefs.saveCacheMaxMb(limit)
            }
            "wifi" -> host.prefs.saveKeepOnWifi(requireNotNull(call.getBoolean("value")))
            "searchSource" -> {
                val source = requireNotNull(call.getString("value"))
                require(source in setOf("youtube_music", "youtube"))
                host.prefs.saveSearchSource(source)
            }
            "saver" -> host.prefs.saveDataSaver(DataSaver.entries.first { it.pref == call.getString("value") })
            "clearCache" -> host.streamCache.clear()
            "removeOffline" -> host.offline.removeAll()
            "appSettings" -> host.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                Uri.fromParts("package", host.packageName, null)))
            else -> error("Ajuste desconocido")
        }
        JSObject()
    }

    @PluginMethod fun downloads(call: PluginCall) = perform(call) {
        val offline = screen.offline
        val rows = JSONArray()
        offline.collectionsFor(screen.account).sortedByDescending { it.pinnedAt }.forEach { item ->
            val progress = offline.progress.value[item.key]
            rows.put(JSONObject().put("id", item.sourceId).put("key", item.key).put("title", item.title)
                .put("subtitle", item.subtitle).put("running", progress?.running == true)
                .put("coverArt", item.coverArt).put("done", progress?.done ?: 0).put("total", item.songs.size).put("failed", progress?.failed ?: 0))
        }
        JSObject().put("rows", rows)
    }

    @PluginMethod fun offlineTracks(call: PluginCall) = perform(call) {
        val key = call.getString("key")
        val account = screen.account
        val collections = screen.offline.collectionsFor(account)
        val songs = if (key == "all") {
            val pinned = collections.flatMap { it.songs }
            val available = screen.offline.cachedSongIds(pinned) + screen.streamCache.completeLibraryIds(account)
            val known = (screen.library.savedSongMetadata(account) + screen.player.queue.value + pinned).associateBy { it.id }
            com.armonia.app.ui.homelab.songsOnPhone(available, known)
        } else collections.first { it.key == key }.songs
        screen.auth()
        JSObject().put("songs", JSONArray(screen.gson.toJson(songs)))
    }

    @PluginMethod fun editPlaylist(call: PluginCall) {
        screen.runOnUiThread {
            try {
                val session = screen.auth()
                val id = requireNotNull(call.getString("id")).also { require(it.isNotBlank()) }
                val intent = Intent(screen, AddSongsActivity::class.java)
                    .putExtra("id", id).putExtra("account", session.namespace)
                startActivityForResult(call, intent, "editorClosed")
            } catch (_: Exception) { call.reject("No se pudo abrir la playlist.") }
        }
    }

    @com.getcapacitor.annotation.ActivityCallback
    private fun editorClosed(call: PluginCall?, result: androidx.activity.result.ActivityResult) {
        if (call == null) return
        perform(call) { JSObject() }
    }

    @PluginMethod fun playlists(call: PluginCall) = perform(call) {
        val library = screen.library
        val id = call.getString("id")
        val cached = call.getBoolean("cached") == true
        val result = JSObject()
        if (id == null) {
            val list = if (cached) library.cachedPlaylists() else library.getPlaylists().getOrThrow().playlists?.playlist.orEmpty()
            if (list != null) result.put("playlists", JSONArray(screen.gson.toJson(list)))
        } else {
            val list = if (cached) library.cachedPlaylist(id) else library.getPlaylist(id).getOrThrow().playlist
            if (list != null) result.put("playlist", JSONObject(screen.gson.toJson(list)))
        }
        result
    }

    @PluginMethod fun searchHistory(call: PluginCall) = perform(call) {
        val prefs = screen.prefs
        when (call.getString("action", "read")) {
            "record" -> prefs.recordSearch(requireNotNull(call.getString("query")))
            "remove" -> prefs.removeSearch(requireNotNull(call.getString("query")))
            "clear" -> prefs.clearSearchHistory()
            "read" -> Unit
            else -> error("Acción desconocida")
        }
        JSObject().put("history", JSONArray(prefs.searchHistory.first()))
    }

    @PluginMethod fun trackDownload(call: PluginCall) = perform(call) {
        screen.downloadTracker.track(requireNotNull(call.getString("videoId")), requireNotNull(call.getString("jobId")),
            requireNotNull(call.getString("title")), screen.auth())
        JSObject()
    }

    @PluginMethod fun librarySongs(call: PluginCall) = perform(call) {
        val songs = if (call.getBoolean("cached") == true) screen.library.savedSongMetadata(screen.account)
            else screen.library.getSongs(forceRefresh = call.getBoolean("refresh") == true).getOrThrow()
        JSObject().put("songs", JSONArray(screen.gson.toJson(songs)))
    }

    @PluginMethod fun songDownload(call: PluginCall) = perform(call) {
        val id = requireNotNull(call.getString("id"))
        val offline = screen.offline
        val state = offline.songStatesFor(screen.account)[id] ?: OfflineSongState.NONE
        when (call.getString("action")) {
            "save" -> if (state == OfflineSongState.NONE) {
                val track = song(requireNotNull(call.getObject("track")))
                require(track.id == id && !id.startsWith("preview|") && !id.startsWith("external|"))
                offline.pinSong(track)
            }
            "remove" -> if (state != OfflineSongState.IN_COLLECTION) offline.unpinSong(id)
            null -> Unit
            else -> error("Acción desconocida")
        }
        JSObject().put("state", (offline.songStatesFor(screen.account)[id] ?: OfflineSongState.NONE).name)
    }

    @PluginMethod fun unpin(call: PluginCall) = perform(call) {
        val key = requireNotNull(call.getString("key"))
        if (screen.offline.collectionsFor(screen.account).any { it.key == key }) screen.offline.unpin(key)
        JSObject()
    }

    @PluginMethod fun pin(call: PluginCall) = perform(call) {
        val tracks = requireNotNull(call.getArray("tracks"))
        val songs = (0 until tracks.length()).map { song(tracks.getJSONObject(it)) }
        require(songs.isNotEmpty())
        val id = requireNotNull(call.getString("id"))
        val (key, label) = when (call.getString("kind", "playlist")) {
            "album" -> OfflineCollection.albumKey(id) to "Album"
            "playlist" -> OfflineCollection.playlistKey(id) to "Playlist"
            "mixed" -> "mixed:$id" to "Playlist mixta"
            else -> error("Tipo de colección desconocido")
        }
        val session = screen.auth()
        if (!screen.musicApi.canKeepOffline(songs.map { it.asMusicTrack() }, session))
            return@perform JSObject().put("restricted", true)
        check(screen.auth() == session)
        val isNew = screen.offline.collectionsFor(screen.account).none { it.key == key }
        screen.offline.pin(OfflineCollection(key, requireNotNull(call.getString("title")),
            "$label · ${songs.size} canciones", songs.first().coverArt, songs, System.currentTimeMillis()))
        check(screen.offline.collectionsFor(screen.account).any { it.key == key })
        if (isNew) screen.showDownloadNotifications()
        JSObject()
    }
}
