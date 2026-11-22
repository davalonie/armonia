package com.armonia.app.ui.playlists

import com.armonia.app.homelab.ImportJob
import com.armonia.app.homelab.ImportSummary

data class ImportHistorySections(val pending: List<ImportSummary>, val completed: List<ImportSummary>)

/** Only an explicit server result archives an import. A missing field is not completion. */
fun importHistorySections(history: List<ImportSummary>): ImportHistorySections {
    val (pending, completed) = history.partition { it.hasPendingWork != false }
    return ImportHistorySections(pending, completed)
}

/** Preserve ids and ordering, including the selected detail, when a poll completes a job. */
fun updateImportSummary(history: List<ImportSummary>, job: ImportJob): List<ImportSummary> {
    val summary = ImportSummary(job.importId, job.name, job.total, job.hasPendingWork, job.legacySkipped)
    return if (history.any { it.importId == job.importId })
        history.map { if (it.importId == job.importId) summary else it }
    else listOf(summary) + history
}

fun canResumeImport(job: ImportJob): Boolean = job.hasPendingWork != false && job.status != "running"

fun importResumeLabel(job: ImportJob): String {
    val completeSource = job.sourceInfo?.get("source_complete")?.takeUnless { it.isJsonNull }?.asBoolean == true
    val onlyIndexing = canResumeImport(job) && job.status == "done" && job.error.isNullOrEmpty() &&
        completeSource && job.items.size == job.total && (job.legacySkipped ?: 0) == 0 &&
        job.items.any { it.state == "indexing" } && job.items.all {
            it.state in setOf("ready", "indexing") || (it.state == "skipped" && it.manualPending == true)
        }
    return if (onlyIndexing) "Comprobar biblioteca" else "Continuar"
}
