package com.armonia.app.ui.playlists

import com.armonia.app.homelab.ImportItem
import com.armonia.app.homelab.ImportJob

data class ImportDecisionFailure(val order: Long, val message: String)

fun canDecideImportItem(job: ImportJob, item: ImportItem): Boolean {
    if (job.hasPendingWork == false) return false
    if (!(job.acceptingDecisions ?: (job.status != "running"))) return false
    if (item.state == "ready") return false
    return job.status != "running" || item.state in setOf(
        "review", "not_found", "search_failed", "download_failed", "source_unavailable", "skipped",
    )
}

/** Reorders review cards only: the position sent to the API remains the original index. */
fun orderedImportReview(job: ImportJob, failures: Map<Int, ImportDecisionFailure> = emptyMap()): List<IndexedValue<ImportItem>> =
    job.items.withIndex().filter { (_, item) ->
        !(job.manualInboxAvailable == true && item.manualPending == true && item.state == "skipped") &&
            (showImportItem(item.state, job.status == "running") ||
                (item.state == "indexing" && (item.reviewOrder ?: 0) > 0 && job.status != "running"))
    }.sortedWith(compareBy<IndexedValue<ImportItem>> {
        val order = maxOf(it.value.reviewOrder ?: 0, failures[it.index]?.order ?: 0)
        if (order > 0) 1 else 0
    }.thenBy { maxOf(it.value.reviewOrder ?: 0, failures[it.index]?.order ?: 0) }.thenBy { it.index })

fun nextImportReviewIndex(before: List<Int>, after: List<Int>, chosen: Int): Int? {
    val following = before.drop(before.indexOf(chosen).takeIf { it >= 0 }?.plus(1) ?: 0)
    return following.firstOrNull { it in after } ?: after.firstOrNull()
}

fun acceptsImportSnapshot(epoch: Long, currentEpoch: Long, wantedId: String?, receivedId: String,
                          currentRevision: Int?, receivedRevision: Int): Boolean =
    epoch == currentEpoch && wantedId == receivedId &&
        (currentRevision == null || receivedRevision >= currentRevision)

/** Why a candidate was not accepted automatically, in the words the web already uses. */
fun importCandidateReason(reason: String): String = when (reason) {
    "different recording version" -> "Versión distinta (directo, remix, cover…)"
    "duration differs" -> "La duración difiere"
    "duration unverified" -> "Duración sin verificar"
    "title or artist is not exact enough" -> "Título o créditos de artistas diferentes"
    "version detail differs" -> "Los detalles de la versión difieren"
    "conflicting isrc" -> "ISRC diferente"
    "conflicting recording_mbid" -> "Identificador de grabación diferente"
    "metadata missing" -> "Faltan metadatos"
    else -> reason
}

fun importFailureReason(reason: String?): String = when (reason) {
    "index_pending" -> "El audio está guardado, pero la biblioteca aún no lo encuentra. Reintentar no vuelve a descargarlo."
    "permission" -> "No hay permiso para completar esta descarga."
    "provider_unavailable", "service_unavailable" -> "La fuente no ha podido completar la operación. Puedes reintentar o elegir otra opción."
    else -> "No se ha completado la operación. Puedes reintentar."
}
