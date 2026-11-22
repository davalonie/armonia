package com.armonia.app.data.cache

import com.armonia.app.data.api.Playlist
import com.armonia.app.data.api.PlaylistDetail
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class PlaylistCacheStoreTest {
    @get:Rule val folder = TemporaryFolder()

    private fun playlist(id: String, name: String, songs: Int = 0) =
        Playlist(id, name, null, "ana", false, songs, 0, null, null, null)
    private fun detail(id: String, name: String) =
        PlaylistDetail(id, name, null, "ana", false, 0, 0, null, null, null, entry = emptyList())

    @Test fun whatWasSavedComesBackAfterTheAppRestarts() {
        PlaylistCacheStore(folder.root).apply {
            writeList("servidor|ana", listOf(playlist("1", "Para conducir de noche", 16), playlist("2", "Domingo")))
            writePlaylist("servidor|ana", detail("1", "Para conducir de noche"))
        }
        val again = PlaylistCacheStore(folder.root)
        assertEquals(listOf("Para conducir de noche", "Domingo"), again.readList("servidor|ana")!!.map { it.name })
        assertEquals(16, again.readList("servidor|ana")!![0].songCount)
        assertEquals("Para conducir de noche", again.readPlaylist("servidor|ana", "1")!!.name)
    }

    @Test fun nothingSavedIsNullNotAnEmptyList() {
        val store = PlaylistCacheStore(folder.root)
        assertNull(store.readList("servidor|ana"))
        assertNull(store.readPlaylist("servidor|ana", "1"))
    }

    @Test fun oneAccountNeverReadsAnother() {
        val store = PlaylistCacheStore(folder.root)
        store.writeList("servidor|ana", listOf(playlist("1", "De Ana")))
        store.writePlaylist("servidor|ana", detail("1", "De Ana"))
        assertNull(store.readList("servidor|berto"))
        assertNull(store.readPlaylist("servidor|berto", "1"))
        assertNull(store.readList("otro-servidor|ana"))
    }

    @Test fun aPlaylistDeletedElsewhereIsForgottenWhenTheListIsRefreshed() {
        val store = PlaylistCacheStore(folder.root)
        store.writeList("a", listOf(playlist("1", "Uno"), playlist("2", "Dos")))
        store.writePlaylist("a", detail("1", "Uno"))
        store.writePlaylist("a", detail("2", "Dos"))
        store.writeList("a", listOf(playlist("2", "Dos")))
        assertNull(store.readPlaylist("a", "1"))
        assertEquals("Dos", store.readPlaylist("a", "2")!!.name)
    }

    @Test fun aDamagedFileCountsAsAbsent() {
        val store = PlaylistCacheStore(folder.root)
        store.writeList("a", listOf(playlist("1", "Uno")))
        folder.root.walkTopDown().filter { it.isFile }.forEach { it.writeText("{ no es json") }
        assertNull(store.readList("a"))
        assertNull(store.readPlaylist("a", "1"))
    }

    @Test fun clearingRemovesEveryAccount() {
        val store = PlaylistCacheStore(File(folder.root, "cache"))
        store.writeList("a", listOf(playlist("1", "Uno")))
        store.clear()
        assertNull(store.readList("a"))
    }
}
