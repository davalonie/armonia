export function importErrorMessage(error) {
  const messages = {
    playlist_missing: 'La playlist de destino ya no existe en Navidrome. Las canciones y tus elecciones siguen guardadas. Puedes crear otra playlist con este progreso, sin volver a descargar las canciones ya preparadas.',
    playlist_service_unavailable: 'No se pudo actualizar la playlist en Navidrome. El progreso esta guardado; reintenta cuando el servicio este disponible.',
    index_service_unavailable: 'Navidrome no pudo completar la consulta de biblioteca. Las descargas terminadas se conservan; reintentar no vuelve a descargarlas.',
    session_expired: 'Tu sesion ha caducado o fue revocada. Inicia sesion de nuevo para continuar la importacion guardada.',
    permission_denied: 'No tienes permiso para completar esta operacion. Comprueba el acceso a la biblioteca y que seas el propietario de la playlist.',
  };
  if (messages[error]) return messages[error];
  if (String(error).includes('playlist')) return 'La playlist cambio o su creacion no pudo confirmarse. Comprueba las listas y vincula la existente antes de continuar.';
  return 'No se pudo completar la operacion. El progreso esta guardado. Reintenta; si vuelve a fallar, revisa el estado del servidor.';
}

export function importActionError(error) {
  // Only application-defined validation messages may reach the UI. Never echo
  // arbitrary upstream bodies/URLs, which could contain credentials.
  if (error?.status === 400 && typeof error.detail === 'string') {
    if (error.detail === 'El archivo no contiene canciones') return 'El archivo no contiene canciones. Comprueba que has seleccionado el CSV de la playlist.';
    if (error.detail === 'No se pudo leer el archivo') return 'No se pudo leer el archivo. Usa un CSV exportado o texto con una linea «Artista - Titulo» por cancion.';
    const line = /^L[ií]nea (\d{1,6}): se esperaba "Artista - T[ií]tulo" o un CSV con cabecera$/.exec(error.detail);
    if (line) return `No se reconoce el formato en la linea ${line[1]}. Usa el CSV exportado con su cabecera o una linea «Artista - Titulo» por cancion.`;
  }
  return error?.message || 'No se pudo completar la operacion. Intentalo de nuevo.';
}
