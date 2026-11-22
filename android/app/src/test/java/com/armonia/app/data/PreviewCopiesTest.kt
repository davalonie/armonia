package com.armonia.app.data

import com.armonia.app.data.repository.PreviewCopies
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PreviewCopiesTest {
    @Test fun survivesEncodingForTheSameAccountOnly() {
        val copies = PreviewCopies.decode(null, "cuenta-a").with("preview|abc", "local1")
        assertEquals("local1", PreviewCopies.decode(copies.encode(), "cuenta-a")["preview|abc"])
        assertNull(PreviewCopies.decode(copies.encode(), "cuenta-b")["preview|abc"])
        assertNull(PreviewCopies.decode(copies.encode(), "")["preview|abc"])
    }

    @Test fun forgetsTheOldestBeyondTheLimitAndOnRequest() {
        var copies = PreviewCopies.decode(null, "a")
        repeat(PreviewCopies.LIMIT + 1) { copies = copies.with("preview|$it", "id$it") }
        assertEquals(PreviewCopies.LIMIT, copies.size)
        assertNull(copies["preview|0"])
        assertEquals("id1", copies["preview|1"])
        assertNull(copies.without("preview|1")["preview|1"])
    }

    @Test fun ignoresDamagedOrForeignLines() {
        val raw = "a\npreview|ok\tid1\nexternal|x\tid2\npreview|bad\tpreview|y\nbasura"
        val copies = PreviewCopies.decode(raw, "a")
        assertEquals(1, copies.size)
        assertEquals("id1", copies["preview|ok"])
    }
}
