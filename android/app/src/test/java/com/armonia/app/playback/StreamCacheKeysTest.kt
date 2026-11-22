package com.armonia.app.playback

import com.armonia.app.security.AccountScope
import org.junit.Assert.*
import org.junit.Test

class StreamCacheKeysTest {
    @Test fun `same track is isolated by server and account`() {
        val url = "https://music.test/api/stream/one"
        assertNotEquals(StreamCacheKeys.keyFor(url, "alice"), StreamCacheKeys.keyFor(url, "bob"))
        assertNotEquals(StreamCacheKeys.keyFor(url, "alice"), StreamCacheKeys.keyFor(url.replace("music", "other"), "alice"))
        assertEquals(StreamCacheKeys.keyFor(url + "?session=old", "alice"), StreamCacheKeys.keyFor(url, "alice"))
    }
    @Test fun `playback keeps the light copy apart from offline downloads`() {
        val url = "https://music.test/api/stream/one"
        assertNotEquals(StreamCacheKeys.keyFor(url, "alice"), StreamCacheKeys.playbackKeyFor(url, "alice"))
        assertNotEquals(StreamCacheKeys.playbackKeyFor(url, "alice"), StreamCacheKeys.playbackKeyFor(url, "bob"))
        assertEquals(StreamCacheKeys.playbackKeyFor(url + "?session=old", "alice"), StreamCacheKeys.playbackKeyFor(url, "alice"))
    }
    @Test fun `origin check rejects hostile URLs`() {
        assertTrue(AccountScope.sameOrigin("https://music.test/api/stream/1", "https://music.test"))
        for (url in listOf("https://music.test.evil/", "http://music.test/", "https://music.test:8443/", "https://user@music.test/", "file:///private"))
            assertFalse(url, AccountScope.sameOrigin(url, "https://music.test"))
    }
    @Test fun `only own UID or system trusted controllers connect`() {
        assertTrue(AccountScope.controllerAllowed(10, 10, false))
        assertTrue(AccountScope.controllerAllowed(20, 10, true))
        assertFalse(AccountScope.controllerAllowed(20, 10, false))
    }
    @Test fun `namespace is stable but changes with identity`() {
        assertEquals(AccountScope.namespace("https://s/", "alice"), AccountScope.namespace("https://s", "alice"))
        assertNotEquals(AccountScope.namespace("https://s", "alice"), AccountScope.namespace("https://s", "bob"))
    }
}
