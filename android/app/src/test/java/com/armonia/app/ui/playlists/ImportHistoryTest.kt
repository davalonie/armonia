package com.armonia.app.ui.playlists

import com.google.gson.Gson
import com.google.gson.JsonObject
import com.armonia.app.homelab.*
import org.junit.Assert.*
import org.junit.Test

class ImportHistoryTest {
    private fun item(state: String, deferred: Boolean? = null) = ImportItem(
        Recording("Fixture", "Artist"), state, emptyList(), null, null, manualPending = deferred,
    )
    private fun job(items: List<ImportItem>, pending: Boolean? = true) = ImportJob(
        "selected", "Identical name", "done", 12, items.size, items.size, 0, 0, 0, items,
        JsonObject().apply { addProperty("source_complete", true) }, 0, hasPendingWork = pending, legacySkipped = 0,
    )

    @Test fun onlyExplicitCompletionLeavesTheDefaultSelectorAndNoRowsAreDeleted() {
        val history = listOf(
            ImportSummary("completed", "Same name", 474, false),
            ImportSummary("legacy", "Same name", 99),
            ImportSummary("working", "Same name", 474, true),
        )
        val sections = importHistorySections(history)
        assertEquals(listOf("legacy", "working"), sections.pending.map { it.importId })
        assertEquals(listOf("completed"), sections.completed.map { it.importId })
        assertEquals(history.size, sections.pending.size + sections.completed.size)
        // Initial selection uses this list; it does not auto-open the first historical record.
        assertEquals("legacy", sections.pending.first().importId)
        assertTrue(importHistorySections(listOf(history.first())).pending.isEmpty())
    }

    @Test fun aPollMovesOnlyItsOwnSummaryWithoutChangingIdentitiesOrOtherRecords() {
        val history = listOf(ImportSummary("selected", "Identical name", 1, true),
            ImportSummary("other", "Identical name", 12, true))
        val completed = job(listOf(item("ready")), pending = false)
        val updated = updateImportSummary(history, completed)
        assertEquals(listOf("selected", "other"), updated.map { it.importId })
        assertSame(history[1], updated[1])
        assertEquals(listOf("other"), importHistorySections(updated).pending.map { it.importId })
        assertEquals(listOf("selected"), importHistorySections(updated).completed.map { it.importId })
        assertEquals(true, history[0].hasPendingWork) // The original list remains unmodified.
        val resumed = updateImportSummary(updated, completed.copy(hasPendingWork = true))
        assertEquals(listOf("selected", "other"), importHistorySections(resumed).pending.map { it.importId })
    }

    @Test fun oneIndexingTrackOutOf474ProcessedTracksStillHasWork() {
        val selected = job(List(473) { item("ready") } + item("indexing"))
        assertEquals(474, ImportProgress.fromStates(selected.items.map { it.state }).processed)
        val updated = updateImportSummary(emptyList(), selected)
        assertEquals(listOf("selected"), importHistorySections(updated).pending.map { it.importId })
        assertTrue(importHistorySections(updated).completed.isEmpty())
        assertEquals("Comprobar biblioteca", importResumeLabel(selected))
    }

    @Test fun onlyIndexingUsesTheLibraryActionWithoutHidingOtherRecoveryWork() {
        val indexing = job(listOf(item("ready"), item("indexing")))
        for (state in listOf("review", "not_found", "search_failed", "download_failed", "pending",
            "searching", "downloading", "source_unavailable", "skipped", "future_state")) {
            assertEquals(state, "Continuar", importResumeLabel(indexing.copy(items = indexing.items + item(state),total = indexing.total + 1)))
        }
        for (status in listOf("running", "error", "paused")) {
            assertEquals(status, "Continuar", importResumeLabel(indexing.copy(status = status)))
        }
        assertEquals("Continuar", importResumeLabel(indexing.copy(legacySkipped = 1)))
        assertEquals("Continuar", importResumeLabel(indexing.copy(error = "playlist recovery required")))
        assertEquals("Continuar", importResumeLabel(indexing.copy(error = " ")))
        assertEquals("Continuar", importResumeLabel(indexing.copy(total = indexing.total + 1)))
        assertEquals("Continuar", importResumeLabel(indexing.copy(sourceInfo = null)))
        assertEquals("Continuar", importResumeLabel(indexing.copy(sourceInfo = JsonObject().apply {
            addProperty("source_complete", false)
        })))
        assertEquals("Comprobar biblioteca", importResumeLabel(indexing.copy(items = indexing.items + item("skipped", true),total = indexing.total + 1)))
        assertEquals("Continuar", importResumeLabel(job(listOf(item("ready")), pending = false)))
    }

    @Test fun completedHistoryIsReadOnlyAndCannotResumeOrMakeChoices() {
        val completed=job(listOf(item("ready")),pending=false)
        assertFalse(canResumeImport(completed))
        assertTrue(canResumeImport(completed.copy(hasPendingWork=true)))
        assertTrue(canResumeImport(completed.copy(hasPendingWork=null)))
        assertFalse(canResumeImport(completed.copy(status="running",hasPendingWork=true)))
        for(state in listOf("ready","review","skipped","indexing","download_failed","source_unavailable")) {
            assertFalse(state,canDecideImportItem(completed,item(state)))
        }
        val parsed=Gson().fromJson("""{"importId":"broken","name":"Fixture","status":"done","total":1,"items":[],"error":"recovery required","hasPendingWork":true}""",ImportJob::class.java)
        assertEquals("recovery required",parsed.error)
        assertTrue(canResumeImport(parsed))
    }

    @Test fun olderResponsesCannotSilentlyHideImportsAndNewFieldsAreRead() {
        val gson = Gson()
        val old = gson.fromJson("""{"importId":"old","name":"Fixture","total":474}""", ImportSummary::class.java)
        assertNull(old.hasPendingWork)
        assertNull(old.legacySkipped)
        assertEquals(1, importHistorySections(listOf(old)).pending.size)
        val current = gson.fromJson("""{"importId":"new","name":"Fixture","total":474,"hasPendingWork":true,"legacySkipped":1}""", ImportSummary::class.java)
        assertEquals(1, current.legacySkipped)
        assertEquals(1, importHistorySections(listOf(current)).pending.size)
        val completed = current.copy(hasPendingWork = false, legacySkipped = 0)
        assertEquals(1, importHistorySections(listOf(completed)).completed.size)
    }

    @Test fun detailResponsesCannotLeaveAnOutdatedSummaryArchived() {
        val old = listOf(ImportSummary("selected", "Identical name", 1, false))
        val unknown = job(listOf(item("indexing")), pending = null)
        assertEquals(1, importHistorySections(updateImportSummary(old, unknown)).pending.size)
        val newSelection = unknown.copy(importId = "new")
        val updated = updateImportSummary(old, newSelection)
        assertEquals(listOf("new", "selected"), updated.map { it.importId })
        assertEquals(1, importHistorySections(updated).pending.size)
        assertEquals(1, importHistorySections(updated).completed.size)
    }
}
