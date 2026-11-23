import {call} from './api.js';

export const MAX_MANUAL_AUDIO_BYTES = 64 * 1024 * 1024;

export function validateManualAudio(file) {
  if (!file || !/\.mp3$/i.test(file.name || '')) throw new Error('Selecciona un archivo MP3.');
  if (!Number.isFinite(file.size) || file.size <= 0) throw new Error('El archivo esta vacio.');
  if (file.size > MAX_MANUAL_AUDIO_BYTES) throw new Error('El MP3 supera el limite de 64 MiB.');
}

export function manualInboxError(error) {
  const messages = {
    401: 'Tu sesion ha caducado. Inicia sesion de nuevo.',
    403: 'No tienes permiso para guardar archivos en esta biblioteca.',
    404: 'Este pendiente ya no esta disponible. Actualiza la bandeja.',
    409: 'El pendiente ha cambiado o hay otra operacion en curso. Actualiza antes de reintentar.',
    413: 'El archivo supera el limite permitido.',
    415: 'Selecciona un archivo MP3.',
    422: 'No se ha podido leer el archivo como audio MP3.',
    429: 'Hay otras operaciones en curso. Espera un momento y reintenta.',
    507: 'No queda suficiente espacio libre en la biblioteca.',
  };
  if (messages[error?.status]) return messages[error.status];
  if (error?.name === 'AbortError') return 'La operacion tardo demasiado o se interrumpio. Actualiza la bandeja para comprobar si el archivo se guardo.';
  // Never display an upstream error body, path, URL or credential here.
  return 'No se pudo completar la operacion. Actualiza la bandeja para comprobar el resultado antes de reintentar.';
}

export function pendingAudioLabel(item) {
  if (item.status !== 'saved') return 'Pendiente de aportar un MP3';
  return item.songId ? 'Guardada en tu biblioteca' : 'Audio guardado; esperando a la biblioteca';
}

export const loadManualInbox = opts => call('/api/manual-inbox', opts);
export const deleteManualPending = (item, opts = {}) => call(`/api/manual-inbox/${encodeURIComponent(item.id)}`, {
  ...opts, method: 'DELETE', body: JSON.stringify({revision: item.revision}),
});
export const refreshManualPending = (item, opts = {}) => call(`/api/manual-inbox/${encodeURIComponent(item.id)}/refresh`, {
  ...opts, method: 'POST', body: JSON.stringify({revision: item.revision}),
});
export function uploadManualAudio(item, file, opts = {}) {
  validateManualAudio(file);
  // File/Blob goes directly to fetch. No base64, JSON wrapping or extra copy of
  // the complete audio in memory; authentication remains in the existing call.
  return call(`/api/manual-inbox/${encodeURIComponent(item.id)}/upload`, {
    ...opts, method: 'POST', headers: {'Content-Type': 'audio/mpeg', 'X-Item-Revision': String(item.revision)}, body: file,
  });
}
