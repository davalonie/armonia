import test from 'node:test';
import assert from 'node:assert/strict';
import {ListenClock} from '../src/lib/listenClock.js';
test('seek, buffering and pause cannot count as listening',()=>{
 const c=new ListenClock(); c.sample(0,0,true); c.sample(100,1000,true,true);
 c.sample(100,2000,true); c.sample(100,5000,true); c.sample(100,9000,false);
 assert.equal(c.seconds,0); assert.equal(c.ready(200),false);
});
test('counts actual progress once; a new play/repeat uses a new clock',()=>{
 const c=new ListenClock(); for(let i=0;i<=100;i++) c.sample(i,i*1000,true);
 assert.equal(c.ready(200),true); assert.equal(c.ready(200),false);
 assert.equal(new ListenClock().ready(200),false);
});
test('short tracks never count and speeding up does not invent elapsed time',()=>{
 const c=new ListenClock();for(let i=0;i<=60;i++) c.sample(i*2,i*1000,true);
 assert.equal(c.seconds,60);assert.equal(c.ready(20),false);assert.equal(c.ready(200),false);
});
