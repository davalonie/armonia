// On the phone, the notice of MainScreen for MusicPlayer.queued: only when the song went into the queue
// (with an empty queue it just plays and nothing is said), naming it, with an undo for that insertion
// alone; a newer one takes the place of the one showing (collectLatest).
import {showToast} from './stores/toastStore.js';
import {undoPlayNext} from './stores/playerStore.js';

export const queuedMessage = (title, kind) => kind === 'next' ? `«${title}» sonara a continuacion`
  : kind === 'end' ? `«${title}» añadida al final de la cola` : `«${title}» añadida a la cola`;

export function queuedNotice(entry, song, kind = 'add') {
  return Promise.resolve(entry).then(queued => {
    if (queued?.token) showToast(queuedMessage(song.title, kind), 'info', () => undoPlayNext(queued), {replace: 'queue'});
  });
}
