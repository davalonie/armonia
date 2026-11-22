package com.armonia.app.ui.components

import java.text.Normalizer

private val MARKS = Regex("\\p{Mn}+")

/** Lower case without accents, so «lua» finds «Lúa» and «cadiz» finds «Cádiz». Ñ stays ñ. */
fun String.foldedForSearch(): String =
    MARKS.replace(Normalizer.normalize(replace("ñ", "\u0001").replace("Ñ", "\u0001"), Normalizer.Form.NFD), "")
        .replace("\u0001", "ñ").lowercase()

/**
 * True when every word of [query] appears in some field, ignoring case and accents.
 * A field is searched whole: a name is never split on commas, "y" or "&".
 */
fun matchesSearch(query: String, vararg fields: String?): Boolean {
    val words = query.foldedForSearch().split(' ').filter { it.isNotBlank() }
    if (words.isEmpty()) return true
    val text = fields.filterNotNull().joinToString("\n") { it.foldedForSearch() }
    return words.all { it in text }
}
