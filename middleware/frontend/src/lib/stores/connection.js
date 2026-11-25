import { writable } from 'svelte/store';

// Whether the phone has a network at all, as the native NetworkMonitor sees it (always true outside
// the app). Whether the server answers is learnt from the requests themselves.
export const phoneOnline = writable(true);
