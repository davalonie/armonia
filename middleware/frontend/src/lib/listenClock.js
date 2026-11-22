// Pure clock: playback position alone never counts seeks as listening.
export class ListenClock {
  constructor() { this.seconds=0; this.previous=null; this.submitted=false; }
  sample(position, now, playing, seeking=false) {
    const p=this.previous;
    if (p && p.playing && playing && !seeking && !p.seeking) {
      const elapsed=Math.max(0,(now-p.now)/1000), delta=position-p.position;
      if (delta > 0 && delta <= elapsed*2 + .5) this.seconds += Math.min(delta,elapsed);
    }
    this.previous={position,now,playing,seeking};
  }
  ready(duration) {
    if (this.submitted || (duration>0 && duration<30)) return false;
    if (this.seconds < (duration>0 ? Math.min(duration/2,240) : 240)) return false;
    this.submitted=true;
    return true;
  }
}
