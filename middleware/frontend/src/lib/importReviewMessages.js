export function importErrorMessage(error) {
  const messages = {
    playlist_missing: 'La playlist de destino ya no existe en Navidrome. Las canciones y tus elecciones siguen guardadas. Puedes crear otra playlist con este progreso, sin volver a descargar las canciones ya preparadas.',
    playlist_service_unavailable: 'No se pudo actualizar la playlist en Navidrome. El progreso está guardado; reintenta cuando el servicio esté disponible.',
    index_service_unavailable: 'Navidrome no pudo completar la consulta de biblioteca. Las descargas terminadas se conservan; reintentar no vuelve a descargarlas.',
    session_expired: 'Tu sesión ha caducado o fue revocada. Inicia sesión de nuevo para continuar la importación guardada.',
    permission_denied: 'No tienes permiso para completar esta operación. Comprueba el acceso a la biblioteca y que seas el propietario de la playlist.',
  };
  if (messages[error]) return messages[error];
  if (String(error).includes('playlist')) return 'La playlist cambió o su creación no pudo confirmarse. Comprueba las listas y vincula la existente antes de continuar.';
  return 'No se pudo completar la operación. El progreso está guardado. Reintenta; si vuelve a fallar, revisa el estado del servidor.';
}

export function importActionError(error) {
  // Only application-defined validation messages may reach the UI. Never echo
  // arbitrary upstream bodies/URLs, which could contain credentials.
  if (error?.status === 400 && typeof error.detail === 'string') {
    if (error.detail === 'El archivo no contiene canciones') return 'El archivo no contiene canciones. Comprueba que has seleccionado el CSV de la playlist.';
    if (error.detail === 'No se pudo leer el archivo') return 'No se pudo leer el archivo. Usa un CSV exportado o texto con una línea «Artista - Título» por canción.';
    const line = /^Línea (\d{1,6}): se esperaba "Artista - Título" o un CSV con cabecera$/.exec(error.detail);
    if (line) return `No se reconoce el formato en la línea ${line[1]}. Usa el CSV exportado con su cabecera o una línea «Artista - Título» por canción.`;
  }
  return error?.message || 'No se pudo completar la operación. Inténtalo de nuevo.';
}
