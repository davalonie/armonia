package com.armonia.app.ui.components

import org.junit.Assert.assertEquals
import org.junit.Test

class FastScrollTest {
    @Test fun labels() {
        assertEquals(listOf("A", "Ñ", "#", "#", "#"), listOf("Álbum", "ñandú", "123", "@", "").map(::scrollInitial))
        assertEquals(emptyList<String>(), emptyList<String>().map(::scrollInitial))
        assertEquals("nov 2026", scrollMonth("2026-11-19T00:00:00Z"))
        assertEquals("—", scrollMonth(null))
    }
}
