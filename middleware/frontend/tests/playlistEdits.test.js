import test from 'node:test';
import assert from 'node:assert/strict';
import {uniqueAdditions} from '../src/lib/playlistEdits.js';
test('append deduplicates existing and selected without changing order',()=>{
  assert.deepEqual(uniqueAdditions(['a'],['c','a','b','c']),{added:['c','b'],duplicates:2});
});
test('mixed references keep distinct providers and metadata',()=>{
  const local={source:'navidrome',source_id:'x',title:'Local'};
  const external={source:'youtube',source_id:'x',title:'External'};
  assert.deepEqual(uniqueAdditions([local],[local,external],t=>`${t.source}:${t.source_id}`),{added:[external],duplicates:1});
});
