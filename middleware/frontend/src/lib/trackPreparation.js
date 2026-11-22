// One speculative target at a time. A refusal/failure is not a cache hit, and
// retries stop when playback changes context instead of chasing old queue entries.
export function createTrackPreparation(request, {
  now = () => Date.now(), schedule = setTimeout, unschedule = clearTimeout,
  ownerNow, ttlMs = 60000, retryDelays = [1000, 3000],
} = {}) {
  let active = null;
  const ready = new Map();
  function cancel() {
    const old = active;
    active = null;
    if (old) { unschedule(old.timer); old.controller?.abort(); }
  }
  function valid(job) {
    return active === job && (!ownerNow || ownerNow() === job.owner);
  }
  async function run(job) {
    if (!valid(job)) return;
    const controller = job.controller = new AbortController();
    // An unresponsive request must not retain the speculative slot indefinitely.
    const timeout = job.timer = schedule(() => controller.abort(), 15000);
    let retry = true;
    try {
      const result = await request(job.id, controller.signal);
      if (!valid(job)) return;
      if (result?.state === 'ready' || result?.state === 'preparing') {
        ready.set(job.key, now() + ttlMs);
        retry = false;
      }
    } catch (error) {
      if ([400, 401, 403, 404].includes(error.status)) retry = false;
    } finally {
      unschedule(timeout);
      if (valid(job)) {
        if (retry && job.attempt < retryDelays.length) {
          job.timer = schedule(() => run(job), retryDelays[job.attempt++]);
        } else active = null;
      } else if (active === job) {
        cancel();
      }
    }
  }
  return {
    prepare(owner, id) {
      if (!owner || !id) { cancel(); return; }
      const key = `${owner}:${id}`;
      if (active?.key === key) return;
      cancel();
      for (const [cached, until] of ready) if (until <= now()) ready.delete(cached);
      if (ready.has(key)) return;
      // Bound memory even when rapidly browsing many playlists.
      while (ready.size >= 32) ready.delete(ready.keys().next().value);
      const job = active = {owner, id, key, attempt: 0, timer: null, controller: null};
      void run(job);
    },
    cancel,
    reset() { cancel(); ready.clear(); },
  };
}
