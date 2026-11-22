import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {beginLogin,completeLogin,readLibrary,toTrack,hasPendingLogin,PLAYLIST_LIMIT} from '../src/lib/spotifyLogin.js';

const CLIENT='0123456789abcdef0123456789abcdef';
const location={origin:'https://armonia.example'};
const memory=()=>{const m=new Map();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k)};};
const json=(body,status=200,headers={})=>({ok:status>=200&&status<300,status,json:async()=>body,headers:{get:k=>headers[k]??null}});

test('sign-in uses PKCE, read-only scopes and the exact return address; nothing secret is sent',async()=>{
  const storage=memory();
  const url=new URL(await beginLogin(CLIENT,{location,storage,crypto:webcrypto}));
  assert.equal(url.origin+url.pathname,'https://accounts.spotify.com/authorize');
  assert.equal(url.searchParams.get('redirect_uri'),'https://armonia.example/');
  assert.equal(url.searchParams.get('code_challenge_method'),'S256');
  assert.equal(url.searchParams.get('scope'),'playlist-read-private playlist-read-collaborative user-library-read');
  assert.equal(url.searchParams.has('client_secret'),false);
  assert.ok(hasPendingLogin(storage));
  const pending=JSON.parse(storage.getItem('armonia.spotify-login'));
  const digest=Buffer.from(await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(pending.verifier))).toString('base64url');
  assert.equal(url.searchParams.get('code_challenge'),digest);
  await assert.rejects(beginLogin('secret-or-garbage',{location,storage,crypto:webcrypto}),/no es válido/);

  const requests=[];
  const fetch=async(address,options)=>{requests.push({address,body:new URLSearchParams(options.body)});return json({access_token:'fictional-access'});};
  const token=await completeLogin({search:`?code=fixture-code&state=${pending.state}`,location,storage,fetch});
  assert.equal(token,'fictional-access');
  assert.equal(requests[0].address,'https://accounts.spotify.com/api/token');
  assert.equal(requests[0].body.get('code_verifier'),pending.verifier);
  assert.equal(requests[0].body.get('client_id'),CLIENT);
  assert.equal(requests[0].body.has('client_secret'),false);
  assert.equal(hasPendingLogin(storage),false,'the verifier is single use');
});

test('a return that is not ours, was refused or has another state never yields access',async()=>{
  const never=async()=>{throw new Error('no request expected');};
  assert.equal(await completeLogin({search:'',location,storage:memory(),fetch:never}),null);
  assert.equal(await completeLogin({search:'?code=stray',location,storage:memory(),fetch:never}),null);
  const storage=memory();
  await beginLogin(CLIENT,{location,storage,crypto:webcrypto});
  await assert.rejects(completeLogin({search:'?code=x&state=forged',location,storage,fetch:never}),/no corresponde/);
  assert.equal(hasPendingLogin(storage),false);
  await beginLogin(CLIENT,{location,storage,crypto:webcrypto});
  const state=JSON.parse(storage.getItem('armonia.spotify-login')).state;
  await assert.rejects(completeLogin({search:`?error=access_denied&state=${state}`,location,storage,fetch:never}),/No has dado permiso/);
  await beginLogin(CLIENT,{location,storage,crypto:webcrypto});
  const again=JSON.parse(storage.getItem('armonia.spotify-login')).state;
  await assert.rejects(completeLogin({search:`?code=x&state=${again}`,location,storage,fetch:async()=>json({},400)}),/rechazó/);
});

const song=(n,extra={})=>({type:'track',name:`Song ${n}`,uri:`spotify:track:${n}`,duration_ms:200000,artists:[{name:'Uno'},{name:'Dos'}],album:{name:'Disco'},external_ids:{isrc:`ES${n}`},...extra});

function spotify({owned=120,limited=false}={}) {
  const calls=[];
  let throttled=limited;
  const fetch=async(address,options)=>{
    assert.equal(options.headers.Authorization,'Bearer fictional-access');
    const url=new URL(address);calls.push(url.pathname+url.search);
    assert.equal(url.origin,'https://api.spotify.com');
    const offset=Number(url.searchParams.get('offset')||0);
    const page=(items,total,path)=>json({items,total,next:offset+50<total?`https://api.spotify.com${path}?limit=50&offset=${offset+50}`:null});
    if(url.pathname==='/v1/me')return json({id:'me',display_name:'Fixture'});
    if(url.pathname==='/v1/me/tracks'){
      if(throttled){throttled=false;return json({},429,{'Retry-After':'1'});}
      return page([{track:song('L1')},{track:null}],2,'/v1/me/tracks');
    }
    if(url.pathname==='/v1/me/albums')return page([{album:{name:'Guardado',artists:[{name:'Uno'}],tracks:{items:[{name:'Pista',uri:'spotify:track:a1',duration_ms:1000,artists:[{name:'Uno'}]}],next:null}}}],1,'/v1/me/albums');
    if(url.pathname==='/v1/me/playlists')return page([
      {id:'mine',name:'Mía',owner:{id:'me'},collaborative:false,items:{total:owned}},
      {id:'theirs',name:'De otra persona',owner:{id:'other',display_name:'Otra'},collaborative:false,items:{total:30}},
      {id:'shared',name:'Colaborativa',owner:{id:'other'},collaborative:true,tracks:{total:1}},
      {id:'refused',name:'Negada',owner:{id:'me'},collaborative:false,items:{total:3}},
    ],4,'/v1/me/playlists');
    if(url.pathname==='/v1/playlists/mine/items')return page(Array.from({length:Math.min(50,owned-offset)},(_,i)=>({item:song(offset+i)})),owned,'/v1/playlists/mine/items');
    if(url.pathname==='/v1/playlists/shared/items')return page([{track:song('C1')},{item:{type:'episode',name:'Podcast'}}],2,'/v1/playlists/shared/items');
    if(url.pathname==='/v1/playlists/refused/items')return json({},403);
    throw new Error('unexpected '+url.pathname);
  };
  return {fetch,calls};
}

test('reads saved songs, saved albums and every page of owned or collaborative playlists',async()=>{
  const {fetch,calls}=spotify({limited:true});
  const waits=[];
  const library=await readLibrary('fictional-access',{fetch,wait:async ms=>waits.push(ms)});
  assert.deepEqual(waits,[1000],'a rate limit is waited out and retried');
  assert.equal(library.user,'Fixture');
  assert.deepEqual(library.playlists.map(p=>[p.name,p.tracks.length]),[['Canciones que te gustan',2],['Álbumes guardados',1],['Mía',120],['Colaborativa',2]]);
  const mine=library.playlists[2].tracks;
  // Each performer is kept apart from the display text; this album states no owner.
  assert.deepEqual(mine[0],{title:'Song 0',artist:'Uno, Dos',artists:['Uno','Dos'],albumArtist:'',album:'Disco',trackNumber:null,discNumber:null,releaseDate:null,duration:200,isrc:'ES0',sourceId:'spotify:track:0'});
  assert.deepEqual(mine.map(t=>t.title),Array.from({length:120},(_,i)=>`Song ${i}`),'order kept across three pages');
  assert.equal(calls.filter(c=>c.startsWith('/v1/playlists/mine/items')).length,3);
  assert.equal(library.playlists[0].tracks[1].title,'','an unavailable song keeps its position');
  assert.equal(library.playlists[3].tracks[1].title,'','a podcast episode is not imported as a song');
  // A saved album's songs carry the album's own artist, so they are filed under one album.
  assert.deepEqual(library.playlists[1].tracks[0],{title:'Pista',artist:'Uno',artists:['Uno'],albumArtist:'Uno',album:'Guardado',trackNumber:null,discNumber:null,releaseDate:null,duration:1,isrc:null,sourceId:'spotify:track:a1'});
  assert.deepEqual(library.unreadable,[{name:'De otra persona',owner:'Otra',total:30},{name:'Negada',owner:'',total:null}]);
  assert.equal(calls.some(c=>c.includes('/playlists/theirs')),false,'contents of another person\'s list are not requested');
});

test('a list beyond the import limit is split instead of truncated; refusals are explained',async()=>{
  const {fetch}=spotify({owned:PLAYLIST_LIMIT+20});
  const library=await readLibrary('fictional-access',{fetch,wait:async()=>{}});
  assert.deepEqual(library.playlists.filter(p=>p.name.startsWith('Mía')).map(p=>[p.name,p.tracks.length]),[['Mía (1)',PLAYLIST_LIMIT],['Mía (2)',20]]);
  await assert.rejects(readLibrary('fictional-access',{fetch:async()=>json({},403),wait:async()=>{}}),/Premium/);
  await assert.rejects(readLibrary('fictional-access',{fetch:async()=>json({},401),wait:async()=>{}}),/caducado/);
  const leaving=async address=>address.endsWith('/v1/me')?json({id:'me'}):json({items:[],next:'https://elsewhere.example/steal'});
  await assert.rejects(readLibrary('fictional-access',{fetch:leaving,wait:async()=>{}}));
  assert.equal(toTrack(null).title,'');
});

test('a track keeps its position in the album and the album date when Spotify states them', async () => {
  const {toTrack} = await import('../src/lib/spotifyLogin.js');
  const item = {type:'track',name:'Bajamar',artists:[{name:'Lúa Norte'}],duration_ms:200000,track_number:4,disc_number:1,
    album:{name:'Mareas',artists:[{name:'Lúa Norte'}],release_date:'2019-03-08'}};
  const track = toTrack(item);
  assert.equal(track.trackNumber,4); assert.equal(track.discNumber,1); assert.equal(track.releaseDate,'2019-03-08');
  const odd = toTrack({...item,track_number:0,disc_number:'1',album:{...item.album,release_date:'hace poco'}});
  assert.equal(odd.trackNumber,null); assert.equal(odd.discNumber,null); assert.equal(odd.releaseDate,null);
});
