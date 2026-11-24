import { registerPlugin } from '@capacitor/core';

// Only the Android asset build can use the device bridge.
export const mobile = import.meta.env?.MODE === 'capacitor' ? registerPlugin('Armonia') : null;

export const mobileImport = import.meta.env?.MODE === 'capacitor' ? registerPlugin('ArmoniaImport') : null;
