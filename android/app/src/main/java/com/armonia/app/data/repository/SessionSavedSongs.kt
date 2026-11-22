package com.armonia.app.data.repository

import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** The mini and expanded players can observe the same transition concurrently. */
internal class SessionSavedSongs {
    private val lock = Mutex()
    private val entries = LinkedHashMap<String, Boolean>()
    private var owner: AuthSnapshot? = null
    private var version = -1L

    suspend fun get(account: AuthSnapshot, revision: Long, id: String, fetch: suspend () -> Boolean): Boolean =
        lock.withLock {
            if (account != owner || revision != version) {
                entries.clear()
                owner = account
                version = revision
            }
            entries[id] ?: fetch().also {
                if (entries.size >= 1024) entries.remove(entries.keys.first())
                entries[id] = it
            }
        }
}
