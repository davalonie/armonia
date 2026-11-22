import { writable } from 'svelte/store';
export const playlistPickerState = writable({open:false,tracks:[],onDone:null});
export function showPlaylistPicker(tracks,onDone=null){playlistPickerState.set({open:true,tracks,onDone});}
export function closePlaylistPicker(){playlistPickerState.set({open:false,tracks:[],onDone:null});}
