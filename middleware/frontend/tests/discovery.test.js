import test from 'node:test';
import assert from 'node:assert/strict';
import {profileMessage,seedReason,personalArtists} from '../src/lib/discovery.js';
test('old and trending pools cannot claim personalized provenance',()=>{
 const mixed={artists:[{name:'Trending',sourceArtist:'Popular'}]};
 assert.deepEqual(personalArtists(mixed),[]);assert.deepEqual(personalArtists({...mixed,version:1}),[]);
});
test('personal results require identified seed evidence',()=>{
 const data={version:1,state:'ready',artists:[{name:'Related',provenance:'similar_to_identified_seed',seeds:[{name:'Seed',mbid:'verified'}]}]};
 assert.equal(personalArtists(data).length,1);assert.match(profileMessage(data),/No se añaden tendencias/);
});
test('empty profiles and outages differ, ambiguity is explicit',()=>{
 assert.match(profileMessage({state:'insufficient_profile'}),/Todavía no hay/);assert.match(profileMessage({state:'unavailable'}),/reintentar/);
 assert.match(seedReason({reason:'multiple_artists'}),/varios artistas/);
});
