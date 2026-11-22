import test from 'node:test';
import assert from 'node:assert/strict';
import {needsImportChoice,canSearchImportAlternatives,showImportItem,importItemTitle,importPhaseLabel,canDecideImportItem,reviewImportItems,importItemFailure} from '../src/lib/importProgress.js';

const item = state => ({state,track:{title:'Fixture'}});

test('saved and queued audio is not presented as a manual version choice', () => {
  for (const state of ['pending','searching','downloading','indexing','ready','skipped']) {
    assert.equal(needsImportChoice(item(state)),false,state);
    assert.equal(showImportItem(item(state),'running'),false,state);
  }
  assert.equal(showImportItem(item('indexing'),'done'),false);
  for (const state of ['review','not_found','search_failed']) {
    assert.equal(needsImportChoice(item(state)),true,state);
    assert.equal(showImportItem(item(state),'running'),true,state);
    assert.match(importItemTitle(item(state)),/Revisar coincidencia/);
  }
});

test('interrupted operations and failed downloads remain actionable without choosing again', () => {
  for (const state of ['pending','searching','downloading']) {
    assert.equal(showImportItem(item(state),'error'),true);
    assert.match(importItemTitle(item(state)),/interrumpido/);
  }
  assert.equal(showImportItem(item('download_failed'),'done'),true);
  assert.equal(needsImportChoice(item('download_failed')),false);
  assert.match(importItemTitle(item('download_failed')),/reintento/);
  assert.equal(showImportItem(item('source_unavailable'),'done'),true);
});

test('concurrent phases describe the import rather than the last worker', () => {
  const stages={search:'Buscando candidatos',indexing:'Indexando en biblioteca',indexing_pending:'Esperando la biblioteca'};
  assert.equal(importPhaseLabel({status:'running',phase:'search',queued:266,inProgress:2},stages),'Importando canciones');
  assert.equal(importPhaseLabel({status:'running',phase:'indexing',queued:0,inProgress:0},stages),'Indexando en biblioteca');
  assert.equal(importPhaseLabel({status:'done',phase:'indexing_pending'},stages),'Esperando la biblioteca');
});

test('legacy skipped songs remain recoverable when the server has no manual inbox', () => {
  assert.equal(needsImportChoice(item('skipped')),false);
  assert.equal(showImportItem(item('skipped'),'running'),false);
  for (const status of ['done','error']) assert.equal(showImportItem(item('skipped'),status),true);
  assert.equal(importItemTitle(item('skipped')),'Omitida: “Fixture”');
});

test('skipping into the separate inbox removes the card without changing original positions', () => {
  const omitted={...item('skipped'),manualPending:true};
  for(const status of ['running','done','error']) {
    assert.equal(showImportItem(omitted,status,true),false);
    const job={status,manualInboxAvailable:true,items:[omitted,item('review'),omitted,item('not_found')]};
    assert.deepEqual(reviewImportItems(job).map(row=>row.index),[1,3]);
    assert.equal(job.items.length,4);
  }
  assert.equal(showImportItem(item('skipped'),'done',false),true);
  assert.equal(showImportItem(item('skipped'),'done',true),true);
  assert.equal(showImportItem({...item('skipped'),manualPending:false},'done',true),true);
});

test('optional search remains available to recover errors and missing source metadata', () => {
  for (const state of ['download_failed','source_unavailable','skipped','pending','searching','downloading']) {
    assert.equal(needsImportChoice(item(state)),false,state);
    assert.equal(canSearchImportAlternatives(item(state)),true,state);
  }
  for (const state of ['review','not_found','search_failed']) assert.equal(canSearchImportAlternatives(item(state)),true,state);
  for (const state of ['indexing','ready']) assert.equal(canSearchImportAlternatives(item(state)),false,state);
});

test('running imports allow independent decisions only when the server supports them', () => {
  for (const state of ['review','not_found','search_failed','download_failed','source_unavailable','skipped']) {
    assert.equal(canDecideImportItem({status:'running',acceptingDecisions:true},item(state)),true,state);
    assert.equal(canDecideImportItem({status:'running'},item(state)),false,'old server '+state);
    assert.equal(canDecideImportItem({status:'running',acceptingDecisions:false},item(state)),false,'reserved '+state);
  }
  for (const state of ['pending','searching','downloading','indexing','ready']) {
    assert.equal(canDecideImportItem({status:'running',acceptingDecisions:true},item(state)),false,state);
  }
  assert.equal(canDecideImportItem({status:'done'},item('review')),true);
  assert.equal(canDecideImportItem({status:'error',acceptingDecisions:false},item('review')),false);
});

test('confirmed queued choices disappear without blocking other review cards', () => {
  const job={status:'running',acceptingDecisions:true,items:[
    {...item('pending'),decision:'confirmed'},item('review'),{...item('downloading'),decision:'confirmed'},item('review'),
  ]};
  assert.deepEqual(reviewImportItems(job).map(row=>row.index),[1,3]);
  assert(reviewImportItems(job).every(row=>canDecideImportItem(job,row.item)));
});

test('failed selections move to the end without changing playlist positions or input data', () => {
  const job={status:'running',items:[
    {...item('download_failed'),reviewOrder:30},item('review'),
    {...item('search_failed'),reviewOrder:20},item('review'),item('ready'),
  ]};
  const before=JSON.stringify(job);
  assert.deepEqual(reviewImportItems(job).map(row=>row.index),[1,3,2,0]);
  assert.deepEqual(reviewImportItems(job,{1:{order:100,message:'offline'}}).map(row=>row.index),[3,2,0,1]);
  assert.equal(JSON.stringify(job),before);
  assert.match(importItemFailure(job.items[0]),/reintentar/);
});

test('failed indexing returns at the bottom for retry without downloading another version', () => {
  const indexed={...item('indexing'),reason:'index_pending',reviewOrder:31};
  const job={status:'done',items:[indexed,item('review')]};
  assert.deepEqual(reviewImportItems(job).map(row=>row.index),[1,0]);
  assert.equal(canSearchImportAlternatives(indexed),false);
  assert.equal(canDecideImportItem(job,indexed),true);
  assert.equal(showImportItem(indexed,'running'),false);
  assert.match(importItemFailure(indexed),/sin descargarlo de nuevo/);
  assert.match(importItemTitle(indexed),/Esperando la biblioteca/);
});

test('interrupted confirmed positions show a safe retry reason at the end', () => {
  for (const state of ['pending','searching','downloading']) {
    const interrupted={...item(state),decision:'confirmed',reviewOrder:20,reason:'service_unavailable'};
    const job={status:'error',items:[interrupted,item('review')]};
    assert.deepEqual(reviewImportItems(job).map(row=>row.index),[1,0]);
    assert.equal(importItemFailure(interrupted),'Se interrumpió el procesamiento. Puedes reintentar.');
    assert.equal(canDecideImportItem(job,interrupted),true);
  }
});

test('import counts follow the app: processed is everything not waiting or working', async () => {
  const {importCounts} = await import('../src/lib/importProgress.js');
  const states = ['ready', 'ready', 'indexing', 'review', 'not_found', 'download_failed', 'skipped', 'source_unavailable', 'pending', 'searching', 'downloading'];
  const c = importCounts({items: states.map(state => ({state}))});
  assert.deepEqual(c, {processed: 8, ready: 2, indexing: 1, queued: 1, inProgress: 2, needsReview: 1, errors: 2, skipped: 1, unavailable: 1});
  const summary = importCounts({current: 5, downloaded: 2, existing: 1, needsReview: 1, errors: 1, queued: 3});
  assert.equal(summary.processed, 5); assert.equal(summary.ready, 3); assert.equal(summary.queued, 3);
  assert.equal(importCounts(null).processed, 0);
});
