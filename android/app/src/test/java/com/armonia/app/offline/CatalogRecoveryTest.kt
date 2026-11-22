package com.armonia.app.offline

import com.google.gson.Gson
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

class CatalogRecoveryTest {
    @Test fun `corruption never becomes an empty writable catalog`() {
        for (json in listOf("broken", "null", "{}", "{\"collections\":null}", "[]")) {
            try {OfflineCatalog.parseStored(json, Gson());fail("accepted corrupt catalog: $json")}
            catch (_:RuntimeException) {}
        }
        assertEquals(OfflineCatalog(), OfflineCatalog.parseStored("{\"collections\":[]}", Gson()))
    }
    @Test fun `disk full cannot publish a deletion or remove existing state`() {
        val previous = OfflineCatalog(listOf(OfflineCollection("playlist:keep", "Keep", "", null, emptyList(), 1)))
        var visible = previous
        try {
            commitCatalog(OfflineCatalog(), {throw IOException("simulated disk full")}, {visible=it})
            fail("expected disk failure")
        } catch (_:IOException) {}
        assertEquals(previous, visible)
        var persisted:OfflineCatalog?=null
        commitCatalog(OfflineCatalog(), {persisted=it}, {assertEquals(it,persisted);visible=it})
        assertEquals(OfflineCatalog(),visible)
    }
}
