package com.armonia.app.ui.login

/** Turns a login HTTP status into something a person can act on. */
fun loginErrorMessage(code: Int): String = when (code) {
    401 -> "Usuario o contraseña incorrectos"
    429 -> "Demasiados intentos fallidos: espera unos minutos y vuelve a probar"
    502, 503, 504 -> "Armonía no llega al servidor de música: comprueba que Navidrome está en marcha"
    404 -> "Esa URL no es un servidor de Armonía"
    else -> "No se pudo iniciar sesión (HTTP $code)"
}
