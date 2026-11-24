import {nativeTrack} from '../nativeTracks.js';
import { mobile } from '../native.js';
import { showToast } from './toastStore.js';

export function command(action, args = {}) {
  return mobile.command({action, ...args}).catch(() => showToast('No se pudo actualizar el reproductor.', 'error'));
}

export function observeNativePlayer(stores) {
  let revision = -1;
  let downloadsRevision = -1;
  let serverDownloadRevision = -1;
  let pending = false;
  let nativeQueue = [];
  let lastError;
  async function refresh() {
    if (pending || document.hidden) return;
    pending = true;
    try {
      const s = await mobile.snapshot({revision,downloadsRevision,serverDownloadRevision});
      if (s.queue) {
        const automatic = new Set(s.autoSongs);
        nativeQueue = s.queue.map(track => nativeTrack(track,s,automatic));
        stores.queue.set(nativeQueue);
        stores.nativeQueueOrder.set({order:s.playOrder, handPicked:s.handPicked, automatic:s.autoSongs});
        revision = s.revision;
      }
      if(s.songDownloads){stores.songDownloads.set(s.songDownloads);downloadsRevision=s.downloadsRevision;}
      if(s.serverDownloads){stores.serverDownloads.set(s.serverDownloads);serverDownloadRevision=s.serverDownloadRevision;}
      stores.offlineProblem.set(s.offlineProblem || null);
      stores.listenProblem.set(s.listenProblem || null);
      stores.sleepTimer.set(s.sleep);
      const preview = s.auditionId && nativeQueue.find(t => t.id === s.auditionId);
      stores.previewState.set(preview ? {track:preview, status:s.buffering?'loading':s.playing?'playing':'paused', note:'Fragmento central · 10 segundos'} : null);
      // As the Kotlin screens did: say it once, then clear it so the next song starts clean
      // and a later failure with the same text is reported again.
      if (s.error && s.error !== lastError) {
        showToast(s.error,'error');
        mobile.command({action:'dismissError'}).catch(()=>{});
      }
      lastError = s.error;
      stores.currentIndex.set(s.index);
      stores.playing.set(s.playing);
      stores.playbackProgress.set({currentTime:s.position/1000, duration:s.duration/1000});
      stores.shuffleOn.set(s.shuffle);
      stores.repeatMode.set(s.repeat);
      stores.continueSimilar.set(s.similar);
      stores.playbackState.set(s.error ? 'error' : s.buffering ? 'loading' : '');
    } catch { /* The activity handles session expiry and account changes. */ }
    finally { pending = false; }
  }
  const notice = mobile.addListener('notice', e => {
    showToast(e.message);
    if (e.libraryChanged) window.dispatchEvent(new Event('armonia-library-changed'));
  });
  void refresh();
  document.addEventListener('visibilitychange', refresh);
  const timer = setInterval(refresh, 650);
  window.addEventListener('pagehide', () => {
    void notice.then(handle=>handle.remove());
    clearInterval(timer);
    document.removeEventListener('visibilitychange', refresh);
  }, {once:true});
}
