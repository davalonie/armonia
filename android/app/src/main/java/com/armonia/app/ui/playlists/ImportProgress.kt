package com.armonia.app.ui.playlists

/** Derived from item states so older servers' inaccurate current/failed totals are not reused. */
data class ImportProgress(
    val processed: Int,
    val ready: Int,
    val indexing: Int,
    val queued: Int,
    val inProgress: Int,
    val needsReview: Int,
    val errors: Int,
    val skipped: Int,
    val unavailable: Int,
) {
    companion object {
        fun fromStates(states: List<String>): ImportProgress {
            val counts = states.groupingBy { it }.eachCount()
            fun count(state: String) = counts[state] ?: 0
            val errors = count("not_found") + count("search_failed") + count("download_failed")
            val processed = count("ready") + count("indexing") + count("review") + errors +
                count("skipped") + count("source_unavailable")
            return ImportProgress(
                processed, count("ready"), count("indexing"), count("pending"),
                count("searching") + count("downloading"), count("review"), errors,
                count("skipped"), count("source_unavailable"),
            )
        }
    }
}

fun importNeedsChoice(state: String): Boolean = state in setOf("review", "not_found", "search_failed")

fun canSearchImportAlternatives(state: String): Boolean =
    importNeedsChoice(state) || state in setOf("download_failed", "source_unavailable")

fun showImportItem(state: String, running: Boolean): Boolean =
    importNeedsChoice(state) || state in setOf("download_failed", "source_unavailable") ||
        (!running && state in setOf("pending", "searching", "downloading", "skipped"))

fun importItemHeading(state: String, title: String): String = when {
    importNeedsChoice(state) -> "Revisar coincidencia de “$title”"
    state == "download_failed" -> "Descarga pendiente de reintento: “$title”"
    state == "source_unavailable" -> "Elemento no recuperado de la fuente"
    state == "skipped" -> "Omitida: “$title”"
    state == "indexing" -> "Esperando la biblioteca: “$title”"
    else -> "Procesamiento interrumpido: “$title”"
}
