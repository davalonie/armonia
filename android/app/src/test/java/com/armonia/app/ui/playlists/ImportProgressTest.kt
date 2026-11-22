package com.armonia.app.ui.playlists

import org.junit.Assert.*
import org.junit.Test

class ImportProgressTest {
    @Test fun savedDownloadsAreProcessedInsteadOfFailed() {
        val states = List(137) { "indexing" } + List(94) { "ready" } + List(19) { "review" } +
            List(222) { "pending" } + List(2) { "downloading" }
        val p = ImportProgress.fromStates(states)
        assertEquals(474, states.size)
        assertEquals(250, p.processed)
        assertEquals(137, p.indexing)
        assertEquals(19, p.needsReview)
        assertEquals(0, p.errors)
        assertEquals(474, p.processed + p.queued + p.inProgress)
    }

    @Test fun terminalStatesAndFailuresAreCountedSeparately() {
        val p = ImportProgress.fromStates(listOf(
            "ready", "indexing", "review", "not_found", "search_failed", "download_failed",
            "skipped", "source_unavailable", "pending", "searching", "downloading",
        ))
        assertEquals(8, p.processed)
        assertEquals(3, p.errors)
        assertEquals(1, p.needsReview)
        assertEquals(1, p.queued)
        assertEquals(2, p.inProgress)
        assertEquals(1, p.skipped)
        assertEquals(1, p.unavailable)
    }

    @Test fun queuedAndSavedItemsDoNotAskForAnotherVersion() {
        for (state in listOf("pending", "searching", "downloading", "indexing", "ready", "skipped")) {
            assertFalse(state, importNeedsChoice(state))
            assertFalse(state, showImportItem(state, running = true))
        }
        assertFalse(showImportItem("indexing", running = false))
        for (state in listOf("review", "not_found", "search_failed")) {
            assertTrue(state, importNeedsChoice(state))
            assertTrue(state, showImportItem(state, running = true))
        }
    }

    @Test fun failedDownloadRetainsItsSelectionAndInterruptedWorkCanResume() {
        assertTrue(showImportItem("download_failed", running = false))
        assertFalse(importNeedsChoice("download_failed"))
        assertTrue(canSearchImportAlternatives("download_failed"))
        assertTrue(canSearchImportAlternatives("source_unavailable"))
        assertFalse(importNeedsChoice("source_unavailable"))
        assertTrue(importItemHeading("download_failed", "Fixture").contains("reintento"))
        assertTrue(showImportItem("skipped", running = false))
        assertTrue(importItemHeading("skipped", "Fixture").contains("Omitida"))
        for (state in listOf("pending", "searching", "downloading")) {
            assertTrue(showImportItem(state, running = false))
            assertTrue(importItemHeading(state, "Fixture").contains("interrumpido"))
        }
    }
}
