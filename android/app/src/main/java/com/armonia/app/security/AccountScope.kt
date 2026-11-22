package com.armonia.app.security

import java.net.URI
import java.security.MessageDigest

object AccountScope {
    fun sameOrigin(url: String, server: String): Boolean = runCatching {
        val a = URI(url); val b = URI(server)
        fun port(u: URI) = if (u.port != -1) u.port else if (u.scheme == "https") 443 else 80
        a.scheme in listOf("http", "https") && a.scheme == b.scheme &&
            !a.host.isNullOrBlank() && a.host.equals(b.host, true) && port(a) == port(b) && a.userInfo == null
    }.getOrDefault(false)

    fun namespace(server: String, username: String): String =
        MessageDigest.getInstance("SHA-256").digest("${server.trimEnd('/')}\n$username".toByteArray())
            .joinToString("") { "%02x".format(it) }

    fun controllerAllowed(uid: Int, ownUid: Int, trusted: Boolean): Boolean = uid == ownUid || trusted
}
