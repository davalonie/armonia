package com.armonia.app.playback

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ConnectionWarmerTest {
    private val server = "https://servidor.ficticio.example"

    @Test fun keepsTheServerHealthAddressWarm() {
        assertEquals("$server/health", warmTarget(server, "sesion-ficticia", online = true))
        assertEquals("$server/health", warmTarget(" $server/ ", "sesion-ficticia", online = true))
    }

    @Test fun nothingToKeepWithoutNetworkSessionOrServer() {
        assertNull(warmTarget(server, "sesion-ficticia", online = false))
        assertNull(warmTarget(server, "", online = true))
        assertNull(warmTarget("", "sesion-ficticia", online = true))
        assertNull(warmTarget("servidor-sin-esquema", "sesion-ficticia", online = true))
    }

    @Test fun oftenEnoughToNoticeABrokenPathBeforeTheTap() {
        // The measured silences were 3–8 s; a 10 s rhythm finds a broken path well within a minute.
        assertEquals(10_000L, ConnectionWarmer.INTERVAL_MS)
    }
}
