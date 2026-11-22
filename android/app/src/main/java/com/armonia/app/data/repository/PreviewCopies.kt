package com.armonia.app.data.repository

/**
 * The library copy of each song from outside the library that «Descargar y guardar» downloaded, kept on the phone so
 * the player's ✓ and the playlist sheet still find it after the app restarts. Each list belongs to one account: read
 * with another account's [namespace] it is empty. Beyond [LIMIT] songs, the oldest are forgotten.
 */
internal class PreviewCopies private constructor(val namespace: String, private val entries: LinkedHashMap<String, String>) {
    operator fun get(preview: String): String? = entries[preview]

    fun with(preview: String, local: String): PreviewCopies {
        val next = LinkedHashMap(entries)
        next.remove(preview)
        next[preview] = local
        while (next.size > LIMIT) next.remove(next.keys.first())
        return PreviewCopies(namespace, next)
    }

    fun without(preview: String): PreviewCopies = PreviewCopies(namespace, LinkedHashMap(entries).apply { remove(preview) })

    val size: Int get() = entries.size

    fun encode(): String = (listOf(namespace) + entries.map { "${it.key}\t${it.value}" }).joinToString("\n")

    companion object {
        const val LIMIT = 500

        fun decode(raw: String?, namespace: String): PreviewCopies {
            val entries = LinkedHashMap<String, String>()
            val lines = raw?.split("\n").orEmpty()
            if (namespace.isNotEmpty() && lines.firstOrNull() == namespace) for (line in lines.drop(1)) {
                val parts = line.split("\t")
                if (parts.size == 2 && parts[0].startsWith("preview|") && parts[1].isNotBlank() && '|' !in parts[1]) {
                    entries[parts[0]] = parts[1]
                }
            }
            return PreviewCopies(namespace, entries)
        }
    }
}
