package com.armonia.app.ui.login

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class LoginErrorsTest {
    @Test
    fun `maps the statuses the backend actually returns`() {
        assertEquals("Usuario o contraseña incorrectos", loginErrorMessage(401))
        assertTrue(loginErrorMessage(429).contains("Demasiados intentos"))
        assertTrue(loginErrorMessage(502).contains("servidor de musica"))
    }

    @Test
    fun `unknown codes keep the number visible`() {
        assertEquals("No se pudo iniciar sesion (HTTP 500)", loginErrorMessage(500))
    }
}
