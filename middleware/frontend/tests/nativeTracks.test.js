import {test} from 'node:test';
import assert from 'node:assert/strict';
import {nativeTrack} from '../src/lib/nativeTracks.js';

test('a restored YouTube item keeps its playback ID, artwork and source',()=>{
  const song={id:'preview|abc',title:'Una pista',artist:'Artista',coverArt:'https://example.org/portada.jpg'};
  const track=nativeTrack(song,{playlist:'lista',playlistKind:'mixed',from:'Inicio'},new Set([song.id]));
  assert.equal(track.id,song.id);
  assert.equal(track._previewUrl,'/api/preview/abc');
  assert.equal(track._previewThumb,song.coverArt);
  assert.equal(track._musicTrack.source_id,'abc');
  assert.equal(track._auto,true);
  assert.deepEqual(track._playlist,{kind:'mixed',id:'lista'});
});

test('library tracks and authorised external recordings keep distinct sources',()=>{
  const library=nativeTrack({id:'abc',title:'Local'},{},new Set());
  assert.equal(library._previewUrl,undefined);
  assert.equal(library._auto,false);
  const remote=nativeTrack({id:'external|abc',title:'Externa',musicTrack:{source:'authorized_http',source_id:'abc',title:'Externa',artist:'A'}},{},new Set());
  assert.equal(remote._previewUrl,'/api/external/abc');
  assert.equal(remote._playlist,null);
});

test('private release artwork from the player goes through the signed-in WebView origin',()=>{
  const path='/api/home/releases/12345678-1234-1234-1234-123456789abc/cover';
  const song={id:'preview|abc',title:'Una pista',artist:'Artista',coverArt:'http://servidor.local'+path+'?account=cuenta'};
  assert.equal(nativeTrack(song,{},new Set())._previewThumb,path);
});
