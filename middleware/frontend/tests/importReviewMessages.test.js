import test from 'node:test';
import assert from 'node:assert/strict';
import {importErrorMessage,importActionError} from '../src/lib/importReviewMessages.js';

test('missing destination explains saved progress and explicit recovery, not login', () => {
  const message=importErrorMessage('playlist_missing');
  assert.match(message,/ya no existe/);
  assert.match(message,/sin volver a descargar/);
  assert.doesNotMatch(message,/Inicia sesion/);
});

test('authentication, indexing and playlist outages have distinct recovery instructions', () => {
  assert.match(importErrorMessage('session_expired'),/Inicia sesion/);
  assert.match(importErrorMessage('index_service_unavailable'),/no vuelve a descargarlas/);
  assert.match(importErrorMessage('playlist_service_unavailable'),/actualizar la playlist/);
  assert.doesNotMatch(importErrorMessage('service_unavailable'),/Inicia sesion/);
});

test('file validation errors explain the failure without leaking arbitrary provider details', () => {
  const generic={status:400,message:'Revisa los datos e intentalo de nuevo.'};
  assert.match(importActionError({...generic,detail:'El archivo no contiene canciones'}),/no contiene canciones/);
  assert.match(importActionError({...generic,detail:'No se pudo leer el archivo'}),/CSV exportado/);
  assert.match(importActionError({...generic,detail:'Linea 3: se esperaba "Artista - Titulo" o un CSV con cabecera'}),/linea 3/);
  assert.equal(importActionError({...generic,detail:'https://upstream/?token=private'}),generic.message);
  assert.equal(importActionError({...generic,detail:{unexpected:'private'}}),generic.message);
  assert.match(importActionError({status:401,message:'Inicia sesion de nuevo.'}),/Inicia sesion/);
});
