package com.armonia.app.homelab

import com.google.gson.Gson
import com.armonia.app.data.repository.AuthSnapshot
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import org.junit.Assert.*
import org.junit.Test
import retrofit2.Response
import java.io.ByteArrayInputStream
import java.io.IOException

class ManualInboxTest {
    private val alice = AuthSnapshot("https://fixture.invalid", "Alice", "alice", "alice-session")
    private class TrackedInput(bytes: ByteArray) : ByteArrayInputStream(bytes) {
        var closed = false
        override fun close() { closed = true; super.close() }
    }
    private fun expectIo(block: () -> Unit): IOException = try {
        block(); throw AssertionError("Expected rejected upload")
    } catch (e: IOException) { e }

    @Test fun streamsWithoutReusingTheBodyOrRetainingAnOpenFile() {
        val input = TrackedInput(ByteArray(20) { it.toByte() })
        val body = BoundedMp3Body({ input }, { true }, 20, 32)
        val sink = Buffer()
        body.writeTo(sink)
        assertEquals(20L, sink.size)
        assertTrue(input.closed)
        assertTrue(body.isOneShot())
        assertEquals(-1L, body.contentLength())
        assertEquals("audio/mpeg", body.contentType().toString())
        expectIo { body.writeTo(Buffer()) }
    }

    @Test fun rejectsKnownOversizeBeforeOpeningAndDoesNotTrustAFalseSmallSize() {
        var opened = false
        expectIo { BoundedMp3Body({ opened = true; ByteArrayInputStream(byteArrayOf(1)) }, { true }, 33, 32) }
        assertFalse(opened)
        val input = TrackedInput(ByteArray(33))
        val sink = Buffer()
        val body = BoundedMp3Body({ input }, { true }, declaredSize = 1, maximum = 32)
        assertTrue(expectIo { body.writeTo(sink) }.message!!.contains("límite"))
        assertEquals(0L, sink.size)
        assertTrue(input.closed)
    }

    @Test fun unknownSizeIsLimitedIncrementallyAndEmptyFilesAreRejected() {
        val input = TrackedInput(ByteArray(18_000))
        val sink = Buffer()
        expectIo { BoundedMp3Body({ input }, { true }, maximum = 16_384).writeTo(sink) }
        assertEquals(16_384L, sink.size)
        assertTrue(input.closed)
        expectIo { BoundedMp3Body({ ByteArrayInputStream(byteArrayOf()) }, { true }).writeTo(Buffer()) }
        expectIo { BoundedMp3Body({ ByteArrayInputStream(byteArrayOf()) }, { true }, declaredSize = 0) }
    }

    @Test fun accountSwitchRevocationOrServerChangeDoesNotSendTheFile() {
        assertTrue(manualUploadAccountMatches(alice, alice.copy()))
        for (current in listOf(alice.copy(userId = "bob"), alice.copy(sessionId = ""),
            alice.copy(sessionId = "renewed"), alice.copy(serverUrl = "https://other.invalid"))) {
            var opened = false
            val sink = Buffer()
            expectIo { BoundedMp3Body({ opened = true; ByteArrayInputStream(byteArrayOf(1)) },
                { manualUploadAccountMatches(alice, current) }).writeTo(sink) }
            assertFalse(opened)
            assertEquals(0L, sink.size)
        }
        assertFalse(manualUploadAccountMatches(AuthSnapshot(), AuthSnapshot()))
    }

    @Test fun accountSwitchDuringReadStopsBeforeSendingTheNextChunk() {
        var current = alice
        var closed = false
        val input = object : ByteArrayInputStream(ByteArray(20)) {
            override fun read(bytes: ByteArray, offset: Int, length: Int): Int {
                val read = super.read(bytes, offset, length)
                current = alice.copy(userId = "bob", sessionId = "bob-session")
                return read
            }
            override fun close() { closed = true; super.close() }
        }
        val sink = Buffer()
        expectIo { BoundedMp3Body({ input }, { manualUploadAccountMatches(alice, current) }).writeTo(sink) }
        assertEquals(0L, sink.size)
        assertTrue(closed)
    }

    @Test fun cancellationClosesAnActiveStreamAndBlocksFurtherWrites() {
        lateinit var body: BoundedMp3Body
        var closed = false
        val input = object : ByteArrayInputStream(ByteArray(20)) {
            override fun read(bytes: ByteArray, offset: Int, length: Int): Int {
                body.close()
                return super.read(bytes, offset, length)
            }
            override fun close() { closed = true; super.close() }
        }
        body = BoundedMp3Body({ input }, { true })
        val sink = Buffer()
        expectIo { body.writeTo(sink) }
        assertEquals(0L, sink.size)
        assertTrue(closed)
        val unopened = BoundedMp3Body({ throw AssertionError("Must not open") }, { true })
        unopened.close()
        expectIo { unopened.writeTo(Buffer()) }
    }

    @Test fun serverFailuresUseSafeMessagesAndRequireExplicitRevision() {
        for (code in listOf(401,403,404,409,413,415,422,429,500,507)) {
            val response = Response.error<ManualInboxItem>(code, "https://secret.invalid/?token=fixture".toResponseBody())
            val failure = expectIo { response.checkedInbox() }
            assertEquals(manualInboxHttpMessage(code), failure.message)
            assertFalse(failure.message!!.contains("token"))
        }
        val gson = Gson()
        assertEquals("{\"revision\":7}", gson.toJson(ManualInboxRevision(7)))
        val item = gson.fromJson("""{"id":"fixture","track":{"title":"Song","artist":"Artist"},"originName":"Original","originImportId":"import","originIndex":4,"status":"saved","songId":null,"revision":7,"error":"index_pending"}""", ManualInboxItem::class.java)
        assertEquals("saved", item.status)
        assertNull(item.songId)
        assertEquals(7, item.revision)
    }

    @Test fun onlyMp3UploadGetsExtraResponseTime() {
        val observed = mutableListOf<Int>()
        val client = OkHttpClient.Builder().addInterceptor(ManualInboxUploadTimeout())
            .addInterceptor { chain ->
                observed += chain.readTimeoutMillis()
                okhttp3.Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
                    .code(200).message("simulated").body("{}".toResponseBody()).build()
            }.build()
        for (path in listOf("/api/manual-inbox/test/upload", "/api/manual-inbox/test/refresh", "/api/stream/test")) {
            client.newCall(Request.Builder().url("https://fixture.invalid$path").post("".toRequestBody()).build()).execute().close()
        }
        assertEquals(listOf(150_000, client.readTimeoutMillis, client.readTimeoutMillis), observed)
    }
}
