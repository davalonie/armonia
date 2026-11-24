<script>
  import { APP_NAME } from '../lib/brand.js';
  import { createEventDispatcher, onMount } from 'svelte';
  import { call, login, setSession } from '../lib/api.js';

  const dispatch = createEventDispatcher();

  let username = '';
  let password = '';
  let loading = false;
  let error = '';
  let passEl;
  let authentik = false;
  onMount(() => { call('/api/oidc/config').then(r => authentik = r.enabled).catch(() => {}); });

  async function signInWithAuthentik() {
    loading = true;
    try {
      const {url} = await call('/api/oidc/web', {method: 'POST'});
      location.assign(url);
    } catch (e) {
      error = e.message;
      loading = false;
    }
  }

  async function doLogin() {
    if (!username.trim() || !password) return;
    loading = true;
    error = '';
    try {
      const result = await login(username.trim(), password);
      setSession(result);
      dispatch('success');
    } catch (e) {
      error = e.status===401 ? 'Usuario o contraseña incorrectos.' : (e.message || 'No se pudo conectar. Intentalo de nuevo.');
      loading = false;
    }
  }
</script>

<div class="fixed inset-0 bg-armonia-bg flex items-center justify-center p-4 z-50">
  <div class="w-full max-w-sm">
    <div class="flex items-center gap-3 justify-center mb-10">
      <img src="/armonia.svg" alt="" class="w-10 h-10 rounded-xl" draggable="false">
      <h1 class="font-london text-3xl text-armonia-text">{APP_NAME}</h1>
    </div>
    <div class="bg-armonia-surface rounded-2xl p-8 border border-white/5 shadow-2xl">
      <h2 class="text-xl font-semibold mb-6 text-armonia-text">Iniciar sesion</h2>
      {#if error}
        <div class="mb-4 p-3 rounded-xl bg-red-500/10 text-red-400 text-sm">{error}</div>
      {/if}
      <form on:submit|preventDefault={doLogin}>
        <label class="block mb-4">
          <span class="block text-sm text-armonia-muted mb-1.5 font-medium">Usuario</span>
          <input
            type="text"
            bind:value={username}
            autocomplete="username"
            placeholder="Usuario"
            autofocus
            on:keydown={e => { if (e.key === 'Enter') passEl?.focus(); }}
            class="w-full bg-armonia-bg text-armonia-text placeholder-armonia-muted rounded-xl py-3 px-4 focus:outline-hidden focus:ring-2 focus:ring-armonia-accent/50 transition-all border border-white/10"
          >
        </label>
        <label class="block mb-6">
          <span class="block text-sm text-armonia-muted mb-1.5 font-medium">Contraseña</span>
          <input
            type="password"
            bind:value={password}
            bind:this={passEl}
            autocomplete="current-password"
            class="w-full bg-armonia-bg text-armonia-text placeholder-armonia-muted rounded-xl py-3 px-4 focus:outline-hidden focus:ring-2 focus:ring-armonia-accent/50 transition-all border border-white/10"
          >
        </label>
        <button
          type="submit"
          disabled={loading}
          class="w-full py-3 bg-armonia-accent hover:bg-armonia-accentHover text-armonia-bg font-semibold rounded-xl transition-colors disabled:opacity-70"
        >
          {#if loading}
            <i class="ph ph-circle-notch animate-spin-slow mr-2"></i>Entrando…
          {:else}
            Entrar
          {/if}
        </button>
      </form>
      {#if authentik}
        <button class="w-full mt-3 py-3 border border-white/20 rounded-xl" disabled={loading}
          on:click={signInWithAuthentik}>Entrar con Authentik</button>
      {/if}
    </div>
    <p class="text-center text-sm text-armonia-muted mt-6">Usa tu usuario y contraseña de Navidrome</p>
  </div>
</div>
