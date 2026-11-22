package com.armonia.app.playback

/** A single browse query belongs to one authenticated session, never to the host process. */
class ScopedSearchCache<T> {
    private var key: String? = null
    private var query: String? = null
    private var results: List<T> = emptyList()
    fun put(sessionKey: String?, search: String, value: List<T>) {
        key = sessionKey
        query = search
        results = if (sessionKey == null) emptyList() else value.toList()
    }
    fun get(sessionKey: String?, search: String): List<T>? =
        if (sessionKey != null && sessionKey == key && search == query) results else null
}

/** Bound IPC payloads and reject integer-overflow/invalid pagination. */
fun <T> browsePage(items: List<T>, page: Int, pageSize: Int): List<T> {
    val offset = page.toLong() * pageSize
    if (page < 0 || pageSize <= 0 || offset > Int.MAX_VALUE) return emptyList()
    return items.drop(offset.toInt()).take(pageSize)
}
