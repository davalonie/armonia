package com.armonia.app.ui.components

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TextSearchTest {
    @Test fun accentsAndCaseDoNotMatter() {
        assertTrue(matchesSearch("lua", "Lúa Norte"))
        assertTrue(matchesSearch("CADIZ", "Cádiz", "Vera Solano"))
        assertTrue(matchesSearch("ultimas farolas", "Últimas farolas"))
        assertEquals("ñandu", "Ñandú".foldedForSearch())
        assertFalse("ñ is a letter of its own, not an accented n", matchesSearch("ano", "Año"))
    }

    @Test fun everyWordMustAppearInSomeField() {
        assertTrue(matchesSearch("norte bajamar", "Bajamar", "Lúa Norte", "Mareas"))
        assertFalse(matchesSearch("norte pleamar", "Bajamar", "Lúa Norte", "Mareas"))
        assertTrue(matchesSearch("   ", "anything"))
        assertTrue(matchesSearch("", null))
    }

    @Test fun aNameWithCommasIsSearchedWhole() {
        assertTrue(matchesSearch("uno, dos", "Trío Uno, Dos & Tres"))
        assertTrue(matchesSearch("dos & tres", "Trío Uno, Dos & Tres"))
    }
}
