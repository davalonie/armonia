const choiceStates = new Set(['review', 'not_found', 'search_failed']);
const decisionStates = new Set(['review', 'not_found', 'search_failed', 'download_failed', 'source_unavailable', 'skipped']);

export function canDecideImportItem(job, item) {
  if (!job || !item) return false;
  // Older servers reject all mutations during a running job. A new server must
  // explicitly advertise safe per-position decisions before enabling them.
  if (job.acceptingDecisions === false) return false;
  if (job.status === 'running') return job.acceptingDecisions === true && decisionStates.has(item.state);
  return decisionStates.has(item.state) || ['pending', 'searching', 'downloading', 'indexing'].includes(item.state);
}

export function needsImportChoice(item) {
  return choiceStates.has(item.state);
}

export function canSearchImportAlternatives(item) {
  // An optional replacement also recovers unavailable sources and failed
  // downloads. It does not mean their recording identity is uncertain.
  return needsImportChoice(item) || [
    'download_failed', 'source_unavailable', 'skipped', 'pending', 'searching', 'downloading',
  ].includes(item.state);
}

export function showImportItem(item, status, manualInboxAvailable = false) {
  // Hide only positions actually saved to the inbox. Historical omissions on
  // an upgraded server never had a ticket and must retain their recovery card.
  if (item.state === 'skipped' && manualInboxAvailable === true && item.manualPending === true) return false;
  if (needsImportChoice(item) || ['download_failed', 'source_unavailable'].includes(item.state)) return true;
  if (item.state === 'indexing' && item.reviewOrder > 0 && item.reason === 'index_pending') return status !== 'running';
  // Queued/active items do not need a manual choice, and indexing is summarized
  // separately. Avoid hundreds of misleading review cards during a large import.
  // Legacy skipped choices remain reversible once mutations are allowed again.
  return status !== 'running' && ['pending', 'searching', 'downloading', 'skipped'].includes(item.state);
}

export function importItemTitle(item) {
  if (item.state === 'source_unavailable') return 'Elemento no recuperado de la fuente';
  if (item.state === 'skipped') return `Omitida: “${item.track.title}”`;
  if (item.state === 'download_failed') return `Descarga pendiente de reintento: “${item.track.title}”`;
  if (item.state === 'indexing') return `Esperando la biblioteca: “${item.track.title}”`;
  if (needsImportChoice(item)) return `Revisar coincidencia de “${item.track.title}”`;
  return `Procesamiento interrumpido: “${item.track.title}”`;
}

export function reviewImportItems(job, localFailures = {}) {
  // Never sort the persisted items themselves: indices identify playlist
  // positions, including duplicates, in every decision sent to the API.
  return (job?.items || []).map((item, index) => ({item, index}))
    .filter(({item}) => showImportItem(item, job.status, job.manualInboxAvailable))
    .sort((a, b) => {
      const order = entry => localFailures[entry.index]?.order || entry.item.reviewOrder || 0;
      const ao = order(a), bo = order(b);
      return Number(ao > 0) - Number(bo > 0) || ao - bo || a.index - b.index;
    });
}

export function importItemFailure(item) {
  if (item.state === 'indexing' && item.reason === 'index_pending') return 'El audio está guardado, pero la biblioteca aún no lo encuentra. Reintentar vuelve a consultar sin descargarlo de nuevo.';
  if (item.reviewOrder > 0 && item.reason === 'service_unavailable' && ['pending', 'searching', 'downloading'].includes(item.state)) return 'Se interrumpió el procesamiento. Puedes reintentar.';
  if (item.state === 'download_failed') return item.reason === 'permission'
    ? 'No se pudo descargar con los permisos actuales. Revisa la sesión o los permisos antes de reintentar.'
    : 'No se pudo descargar esta elección. Puedes reintentar o buscar otra fuente.';
  if (item.state === 'search_failed') return 'La búsqueda no pudo completarse. Puedes reintentarlo.';
  return '';
}

export function importPhaseLabel(job, stages) {
  // With concurrent workers the last written phase describes one operation,
  // not the whole job. Keep the exact phase only for batch/final operations.
  if (job.status === 'running' && ((job.queued || 0) + (job.inProgress || 0) > 0)) return 'Importando canciones';
  return stages[job.phase] || 'Preparando';
}

/**
 * The open import's counts, as the app's ImportProgress.fromStates: everything that is not pending, searching or
 * downloading counts as processed. Without the songs (a summary), the server's own counters are used.
 */
export function importCounts(job) {
  const n = value => Number.isInteger(value) && value >= 0 ? value : 0;
  if (Array.isArray(job?.items)) {
    const c = {};
    for (const item of job.items) c[item.state] = (c[item.state] || 0) + 1;
    const errors = n(c.not_found) + n(c.search_failed) + n(c.download_failed);
    return {processed: n(c.ready) + n(c.indexing) + n(c.review) + errors + n(c.skipped) + n(c.source_unavailable),
      ready: n(c.ready), indexing: n(c.indexing), queued: n(c.pending), inProgress: n(c.searching) + n(c.downloading),
      needsReview: n(c.review), errors, skipped: n(c.skipped), unavailable: n(c.source_unavailable)};
  }
  return {processed: n(job?.current), ready: n(job?.downloaded) + n(job?.existing), indexing: n(job?.indexing),
    queued: n(job?.queued), inProgress: n(job?.inProgress), needsReview: n(job?.needsReview), errors: n(job?.errors),
    skipped: n(job?.skipped), unavailable: n(job?.unavailable)};
}
