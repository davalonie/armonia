package com.armonia.app.homelab

import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

data class PendingListen(val owner: String, val event: PlayEvent)

/** Serialise disk transactions, never network waits. All delivery data stays immutable. */
class DurableListenQueue(
    private val read: (String) -> List<PendingListen>,
    private val write: (String, List<PendingListen>) -> Unit,
) {
    private val storage = Mutex()
    private val delivery = Mutex()

    suspend fun enqueue(account: String, owner: String, event: PlayEvent) = storage.withLock {
        require(account.isNotBlank() && owner.isNotBlank())
        val events = read(account)
        val pending = PendingListen(owner, event)
        events.find { it.event.id == event.id }?.let {
            check(it == pending) { "Listening event ID reused with different data" }
            return@withLock
        }
        check(events.size < 5000) { "La cola de escuchas está llena" }
        write(account, events + pending)
    }

    suspend fun flush(account: String, owner: String, current: () -> Boolean,
                      send: suspend (PendingListen) -> Int) {
        if (!delivery.tryLock()) return
        try {
            val batch = storage.withLock { read(account).take(25) }
            for (pending in batch) {
                if (!current() || pending.owner != owner) break
                val code = send(pending)
                // A session change/401 must never turn its 409 into a rejected
                // recording for the old account. Keep it until that owner returns.
                if (!current()) break
                if (code !in 200..299 && code !in listOf(409, 422)) break
                storage.withLock {
                    if (code in listOf(409, 422)) {
                        val rejected = read("$account-rejected")
                        if (rejected.none { it.event.id == pending.event.id })
                            write("$account-rejected", (rejected + pending).takeLast(5000))
                    }
                    // New events may have arrived during the HTTP request.
                    write(account, read(account).filterNot { it.event.id == pending.event.id })
                }
            }
        } finally {
            delivery.unlock()
        }
    }
}
