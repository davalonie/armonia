export function profileMessage(data) {
  if (data.state==='unavailable') return 'No se han podido consultar los metadatos. Tus escuchas siguen guardadas; puedes reintentar.';
  if (data.state==='no_similar_results') return 'Tus artistas estan identificados, pero el proveedor no ha devuelto similitudes. Puedes reintentar; no rellenamos con tendencias.';
  if (data.artists?.length) return 'Similitud con artistas identificados de tus escuchas del ultimo mes. No se añaden tendencias para rellenar la lista.';
  return 'Todavia no hay similitudes verificables para tu perfil. Escucha musica o revisa los artistas pendientes y vuelve a consultar.';
}
export function seedReason(seed) {
  return ({recording_metadata:'Identificado mediante metadatos de tus grabaciones',name_and_recording:'Nombre y cancion contrastados en MusicBrainz',conflicting_ids:'Hay identificadores contradictorios',multiple_artists:'Hay varios artistas con ese nombre',not_found:'Sin coincidencia de nombre en MusicBrainz',missing_recording_evidence:'Faltan canciones coincidentes para verificar su identidad',metadata_unavailable:'Proveedor de metadatos no disponible',missing_evidence:'Todavia no hay evidencia suficiente'})[seed.reason] || 'Identidad pendiente de comprobar';
}
export function personalArtists(data) {
  // Fail closed for old/mixed snapshots, including cached responses from older servers.
  return data.version===1 ? (data.artists||[]).filter(a=>a.provenance==='similar_to_identified_seed'&&a.seeds?.length) : [];
}
