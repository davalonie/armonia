package com.armonia.app.homelab

import com.armonia.app.data.repository.AuthSnapshot
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Interceptor
import okhttp3.RequestBody
import okio.BufferedSink
import retrofit2.Response
import java.io.IOException
import java.io.InputStream
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.TimeUnit

data class ManualInboxItem(
    val id: String, val track: Recording, val originName: String, val originImportId: String,
    val originIndex: Int, val status: String, val songId: String?, val revision: Int, val error: String?,
)
data class ManualInboxResult(val items: List<ManualInboxItem>)
data class ManualInboxRevision(val revision: Int)

const val MANUAL_MP3_MAX_BYTES = 64L * 1024 * 1024

class ManualInboxFailure(val userMessage: String) : IOException(userMessage)

fun manualInboxHttpMessage(code: Int): String = when (code) {
    401 -> "La sesión ha caducado. Vuelve a iniciar sesión."
    403 -> "No tienes permiso para guardar en esta biblioteca."
    404 -> "Este pendiente ya no está disponible. Actualiza la bandeja."
    409 -> "Este pendiente ha cambiado o se está procesando. Actualiza antes de continuar."
    413 -> "El archivo supera el límite de 64 MiB."
    415, 422 -> "El archivo debe ser un MP3 válido."
    429 -> "Hay otra subida en curso. Espera un momento y reintenta."
    507 -> "La biblioteca no tiene espacio suficiente."
    else -> "No se pudo completar la operación. Actualiza la bandeja antes de reintentar."
}

fun <T> Response<T>.checkedInbox(): T {
    if (!isSuccessful) {
        errorBody()?.close()
        throw ManualInboxFailure(manualInboxHttpMessage(code()))
    }
    return body() ?: throw ManualInboxFailure("El servidor devolvió una respuesta vacía. Actualiza la bandeja.")
}

fun manualUploadAccountMatches(expected: AuthSnapshot, current: AuthSnapshot): Boolean =
    expected.userId.isNotBlank() && expected.sessionId.isNotBlank() && expected == current

/** Decoding occurs after the request body is received (server deadline: 120 seconds).
 * Keep the normal API timeouts; only this upload waits longer for its response.
 */
class ManualInboxUploadTimeout : Interceptor {
    override fun intercept(chain: Interceptor.Chain): okhttp3.Response {
        val request = chain.request()
        val upload = request.method == "POST" && Regex("/api/manual-inbox/[^/]+/upload").matches(request.url.encodedPath)
        return (if (upload) chain.withReadTimeout(150, TimeUnit.SECONDS) else chain).proceed(request)
    }
}

/** SAF streams can omit or misreport their size. Enforce the limit on bytes read too.
 * No whole-file allocation, filename, local pathname or external URL is sent to the server.
 */
class BoundedMp3Body(
    private val open: () -> InputStream,
    private val stillAuthorized: () -> Boolean,
    private val declaredSize: Long? = null,
    private val maximum: Long = MANUAL_MP3_MAX_BYTES,
) : RequestBody(), AutoCloseable {
    private val stream = AtomicReference<InputStream?>(null)
    private val used = AtomicBoolean(false)
    private val closed = AtomicBoolean(false)

    init {
        if (declaredSize != null && (declaredSize <= 0 || declaredSize > maximum))
            throw ManualInboxFailure(if (declaredSize == 0L) "El archivo está vacío." else "El archivo supera el límite de 64 MiB.")
    }

    override fun contentType() = "audio/mpeg".toMediaType()
    // Chunked transport allows truthful validation even if a document provider's size is wrong.
    override fun contentLength() = -1L
    override fun isOneShot() = true

    private fun checkAccess() {
        if (closed.get() || Thread.currentThread().isInterrupted) throw IOException("Upload cancelled")
        if (!stillAuthorized()) throw ManualInboxFailure("La cuenta o la sesión ha cambiado. No se enviará el archivo.")
    }

    override fun writeTo(sink: BufferedSink) {
        if (!used.compareAndSet(false, true)) throw IOException("Upload body already consumed")
        checkAccess()
        open().use { input ->
            stream.set(input)
            try {
                val buffer = ByteArray(8192)
                var count = 0L
                while (true) {
                    checkAccess()
                    val size = input.read(buffer)
                    if (size < 0) break
                    if (size == 0) continue
                    count += size
                    if (count > maximum) throw ManualInboxFailure("El archivo supera el límite de 64 MiB.")
                    checkAccess()
                    sink.write(buffer, 0, size)
                }
                if (count == 0L) throw ManualInboxFailure("El archivo está vacío.")
            } finally {
                stream.set(null)
            }
        }
    }

    override fun close() {
        closed.set(true)
        runCatching { stream.getAndSet(null)?.close() }
    }
}
