import { APP_NAME } from './lib/brand.js';
document.title=APP_NAME;
import './main.css';
import './phone-library.css';
import '@phosphor-icons/web/regular';
import '@phosphor-icons/web/fill';
import '@phosphor-icons/web/bold';
import { mount } from 'svelte';
import App from './App.svelte';
import { installRipple } from './lib/ripple.js';

// The app's press feedback on touch screens (the phone app and the web on a phone).
installRipple();

if (import.meta.env.MODE === 'capacitor') {
  document.documentElement.classList.add('capacitor');
  for (const [name,weight] of [['regular','400'],['medium','500'],['semibold','600'],['bold','700']]) {
    document.fonts.add(new FontFace('Armonia Inter', 'url(/android-font/inter_' + name + '.ttf)', {weight}));
  }
}

const app = mount(App, { target: document.getElementById('app') });

export default app;
