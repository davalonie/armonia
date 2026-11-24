package com.armonia.app.data.repository

/** The server already has this song: the download is offered again only on purpose («Descargar igualmente»). */
class DuplicateException : Exception("already in library")
