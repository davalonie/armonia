package com.armonia.app.data.cache

import android.content.Context
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.armonia.app.data.api.Playlist
import com.armonia.app.data.api.Song
import com.armonia.app.data.api.PlaylistDetail
import com.armonia.app.data.repository.PreferencesRepository
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.security.MessageDigest
import javax.inject.Inject
import javax.inject.Singleton

/**
 * The last playlists the server gave, kept on the phone: the list opens at once with what was
 * known, and is refreshed behind it. Also what makes a playlist reachable without a connection.
 *
 * One folder per account (server + user), named by a hash: nothing of one account is ever read
 * for another. A file that cannot be read counts as absent; the server remains the source.
 */
class PlaylistCacheStore(private val root: File, private val gson: Gson = Gson()) {
    private fun hash(text: String): String =
        MessageDigest.getInstance("SHA-256").digest(text.toByteArray()).joinToString("") { "%02x".format(it) }.take(32)

    private fun folder(account: String) = File(root, hash(account))
    private fun listFile(account: String) = File(folder(account), "list.json")
    private fun playlistFile(account: String, id: String) = File(folder(account), "p-${hash(id)}.json")

    private fun write(file: File, value: Any) {
        file.parentFile?.mkdirs()
        val temp = File(file.parentFile, "${file.name}.tmp")
        temp.writeText(gson.toJson(value))
        if (!temp.renameTo(file)) { file.delete(); temp.renameTo(file) }
    }

    fun readList(account: String): List<Playlist>? = runCatching {
        val file = listFile(account)
        if (!file.isFile) return null
        gson.fromJson<List<Playlist>>(file.readText(), object : TypeToken<List<Playlist>>() {}.type)
    }.getOrNull()

    /** Saves the list and forgets the saved contents of playlists that are no longer in it. */
    fun writeList(account: String, playlists: List<Playlist>) {
        if (account.isBlank()) return
        runCatching {
            write(listFile(account), playlists)
            val keep = playlists.map { playlistFile(account, it.id).name }.toSet() + setOf("list.json", "songs.json")
            folder(account).listFiles()?.filter { it.name !in keep }?.forEach { it.delete() }
        }
    }

    fun readPlaylist(account: String, id: String): PlaylistDetail? = runCatching {
        val file = playlistFile(account, id)
        if (!file.isFile) return null
        gson.fromJson(file.readText(), PlaylistDetail::class.java)?.takeIf { it.id == id }
    }.getOrNull()

    fun writePlaylist(account: String, playlist: PlaylistDetail) {
        if (account.isBlank()) return
        runCatching { write(playlistFile(account, playlist.id), playlist) }
    }

    fun saveSongs(account: String, songs: List<Song>) {
        if (account.isNotBlank()) write(File(folder(account), "songs.json"), songs)
    }

    fun songs(account: String): List<Song> = runCatching {
        gson.fromJson<List<Song>>(File(folder(account), "songs.json").readText(), object : TypeToken<List<Song>>() {}.type)
    }.getOrNull().orEmpty()

    fun clear() { runCatching { root.deleteRecursively() } }
}

@Singleton
class PlaylistCache @Inject constructor(
    @ApplicationContext context: Context,
    private val prefs: PreferencesRepository,
) {
    private val store = PlaylistCacheStore(File(context.filesDir, "playlist-cache"))

    suspend fun list(): List<Playlist>? = withContext(Dispatchers.IO) { store.readList(prefs.accountNamespace) }
    suspend fun playlist(id: String): PlaylistDetail? = withContext(Dispatchers.IO) { store.readPlaylist(prefs.accountNamespace, id) }
    suspend fun saveList(account: String, playlists: List<Playlist>) = withContext(Dispatchers.IO) { store.writeList(account, playlists) }
    suspend fun savePlaylist(account: String, playlist: PlaylistDetail) = withContext(Dispatchers.IO) { store.writePlaylist(account, playlist) }
    suspend fun saveSongs(account: String, songs: List<Song>) = withContext(Dispatchers.IO) { runCatching { store.saveSongs(account, songs) }; Unit }
    suspend fun songs(account: String) = withContext(Dispatchers.IO) { store.songs(account) }
    suspend fun clear() = withContext(Dispatchers.IO) { store.clear() }
}
