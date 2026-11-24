package com.armonia.app.homelab

import java.io.ByteArrayOutputStream
import java.io.InputStream
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody

suspend fun playlistCoverBody(open: () -> InputStream?) = withContext(Dispatchers.IO) {
    requireNotNull(open()).use { input ->
        val bytes = ByteArrayOutputStream()
        val buffer = ByteArray(16 * 1024)
        while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            require(bytes.size() + count <= 8 * 1024 * 1024) { "La imagen debe ocupar como máximo 8 MiB" }
            bytes.write(buffer, 0, count)
        }
        bytes.toByteArray().toRequestBody("application/octet-stream".toMediaType())
    }
}
