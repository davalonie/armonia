import {call} from './api.js';

export const MAX_ZIP_BYTES = 8 * 1024 * 1024;

export function validateArchive(file) {
  if (!file || !/\.zip$/i.test(file.name || '')) throw new Error('Elige el archivo ZIP que descarga «Exportar todo» en Exportify.');
  if (!Number.isFinite(file.size) || file.size <= 0) throw new Error('El archivo está vacío.');
  if (file.size > MAX_ZIP_BYTES) throw new Error('El archivo supera el límite de 8 MiB.');
}

export function batchError(error) {
  const messages = {
    401: 'Tu sesión ha caducado. Inicia sesión de nuevo.',
    404: 'Esta importación ya no existe. Vuelve a empezar.',
    409: 'Esta importación ya se había iniciado. Actualiza para ver su estado.',
    413: 'El archivo es demasiado grande o contiene demasiadas playlists.',
    422: 'No se han encontrado playlists que se puedan importar en ese archivo.',
  };
  return messages[error?.status] || error?.message || 'No se pudo completar la operación. Vuelve a intentarlo.';
}

const NOTES = {
  unreadable: 'Vacía o ilegible', too_large: 'Demasiado grande', empty: 'Sin canciones',
  resource_limit: 'Solo las primeras 5000 canciones',
};
export const noteLabel = note => NOTES[note] || '';
export const importable = playlist => playlist.total > 0 && !['unreadable', 'too_large', 'empty'].includes(playlist.note);

/** What one row of a started batch shows, from the queue state and its own import. */
export function playlistProgress(playlist) {
  const job = playlist.import;
  if (playlist.state === 'skipped') return {label: 'No seleccionada', tone: 'muted'};
  if (playlist.state === 'waiting') return {label: 'En espera', tone: 'muted'};
  if (playlist.state === 'failed') return {label: 'No se pudo iniciar', tone: 'error'};
  if (!job) return {label: 'Historial eliminado', tone: 'muted'};
  if (job.status === 'running') return {label: `Importando ${job.current}/${job.total}`, tone: 'active'};
  if (job.status === 'done') return job.review
    ? {label: `Importada · ${job.review} por revisar`, tone: 'review'}
    : {label: 'Importada', tone: 'done'};
  return {label: job.review ? `Detenida · ${job.review} por revisar` : 'Detenida: continúala desde Importaciones', tone: 'review'};
}

const REASONS = {
  user: 'En pausa. La playlist en curso termina; las siguientes esperan.',
  busy: 'Hay otra importación tuya en marcha. Continúa cuando termine.',
  session: 'La sesión caducó durante la importación. Continúa para seguir con las que faltan.',
  interrupted: 'El servidor se reinició. Continúa para seguir con las que faltan.',
};
export const pauseReason = reason => REASONS[reason] || 'En pausa.';

export const loadBatch = opts => call('/api/import-batch', opts);
export const batchStatus = (id, opts) => call(`/api/import-batch/${encodeURIComponent(id)}`, opts);
export const loadConfig = opts => call('/api/import-batch/config', opts);
export const saveConfig = clientId => call('/api/import-batch/config', {method: 'PUT', body: JSON.stringify({clientId})});
export const startBatch = (id, selected, names) => call(`/api/import-batch/${encodeURIComponent(id)}/start`, {
  method: 'POST', body: JSON.stringify({selected, names}),
});
export const resumeBatch = id => call(`/api/import-batch/${encodeURIComponent(id)}/resume`, {method: 'POST'});
export const removeFromBatch = (id, index) => call(`/api/import-batch/${encodeURIComponent(id)}/remove`, {method: 'POST', body: JSON.stringify({index})});
export const pauseBatch = id => call(`/api/import-batch/${encodeURIComponent(id)}/pause`, {method: 'POST'});
export const forgetBatch = id => call(`/api/import-batch/${encodeURIComponent(id)}`, {method: 'DELETE'});
export const proposeFromSpotify = playlists => call('/api/import-batch/spotify', {method: 'POST', body: JSON.stringify({playlists})});
export function proposeFromArchive(file) {
  validateArchive(file);
  // The archive goes to fetch as it is: no base64 or second copy in memory.
  return call('/api/import-batch/zip', {method: 'POST', headers: {'Content-Type': 'application/zip'}, body: file});
}
