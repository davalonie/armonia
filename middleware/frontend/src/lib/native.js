import { Capacitor, registerPlugin } from '@capacitor/core';

// Only the Android asset build can use the device bridge.
const android = import.meta.env?.MODE === 'capacitor';

// The sign-in page runs in its own activity, whose only plugin is the sign-in one: there is no account there yet.
export const mobileLogin = android && Capacitor.isPluginAvailable('ArmoniaLogin') ? registerPlugin('ArmoniaLogin') : null;

export const mobile = android && !mobileLogin ? registerPlugin('Armonia') : null;

export const mobileImport = android && !mobileLogin ? registerPlugin('ArmoniaImport') : null;
