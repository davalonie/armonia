package com.armonia.app.security

import com.armonia.app.data.repository.AuthSnapshot
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.*
import org.junit.Test

class SessionCallFactoryTest {
    @Test fun `queued request retains origin and session after account switch or logout`() {
        val alice = AuthSnapshot("https://alice.test", "Alice", "a", "a-session")
        val bob = AuthSnapshot("https://bob.test", "Bob", "b", "b-session")
        var current = alice
        val received = mutableListOf<AuthSnapshot>()
        val client = OkHttpClient.Builder().addInterceptor { chain ->
            received.add(requireNotNull(chain.request().tag(AuthSnapshot::class.java)))
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
                .code(200).message("simulated").body("{}".toResponseBody()).build()
        }.build()
        val factory = SessionCallFactory(client) { current }
        val request = Request.Builder().url("https://placeholder/api/library/star?id=track").build()
        val first = factory.newCall(request)
        current = bob
        val second = factory.newCall(request)
        current = AuthSnapshot()
        first.execute().close()
        second.execute().close()
        factory.newCall(request).execute().close()
        assertEquals(listOf(alice, bob, AuthSnapshot()), received)
    }

    @Test fun `background operation explicit account cannot be replaced by current account`() {
        val old = AuthSnapshot("https://old.test", "Old", "old", "old-session")
        val current = AuthSnapshot("https://new.test", "New", "new", "new-session")
        val factory = SessionCallFactory(OkHttpClient()) { current }
        val request = Request.Builder().url("https://placeholder/api/track/id")
            .tag(AuthSnapshot::class.java, old).build()
        val call = factory.newCall(request)
        assertEquals(old, call.request().tag(AuthSnapshot::class.java))
        call.cancel()
    }
}
