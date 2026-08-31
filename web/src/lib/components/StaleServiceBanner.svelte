<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchHealth, REQUIRED_API_REVISION, type Health } from '$lib/api';

  /**
   * A service left running across an update answers 404 to every route added
   * since it started, and 405 to every method. Read one request at a time that
   * looks like a bad request; read together it is one fact, and this says it
   * once, in the one place nobody can miss.
   */
  const POLL_MS = 15_000;

  let health = $state<Health | null>(null);
  let checked = $state(false);
  let dismissed = $state(false);

  const stale = $derived(
    checked && health !== null && (health.api_revision ?? 0) < REQUIRED_API_REVISION
  );
  const missing = $derived.by(() => {
    const has = new Set(health?.features ?? []);
    return [
      ['folder-runs', 'procesar carpetas locales'],
      ['inventory', 'el inventario'],
      ['inventory-xlsx', 'el inventario en Excel'],
      ['inventory-backend', 'el inventario en la base de datos'],
      ['documents', 'el historial de procesados'],
      ['job-delete', 'limpiar la pantalla'],
      ['output-edit', 'editar y eliminar resoluciones'],
      ['browse', 'el selector de carpetas']
    ].filter(([key]) => !has.has(key));
  });

  onMount(() => {
    const probe = async () => {
      health = await fetchHealth();
      checked = true;
    };
    probe();
    const poll = setInterval(probe, POLL_MS);
    return () => clearInterval(poll);
  });
</script>

{#if stale && !dismissed}
  <div class="banner" role="alert">
    <span class="icon" aria-hidden="true">⚠</span>
    <div class="body">
      <b>El servicio está corriendo una versión anterior.</b>
      <p>
        No es un problema de lo que escribió: el proceso quedó levantado desde antes de la
        actualización y no reconoce
        {#if missing.length}
          {missing.map(([, label]) => label).join(', ')}.
        {:else}
          las funciones nuevas.
        {/if}
        Párelo con <b class="key">Ctrl+C</b> en la terminal donde corre, y vuelva a levantarlo
        desde la carpeta <b class="key">backend</b> del proyecto:
      </p>
      <code>.venv\Scripts\python -m uvicorn resolutions.api.main:app --port 8000 --reload</code>
      <p class="tip">
        Con <b>--reload</b> no vuelve a pasar: el servicio recarga solo cuando cambia el código.
      </p>
    </div>
    <button onclick={() => (dismissed = true)} aria-label="Ocultar">✕</button>
  </div>
{/if}

<style>
  .banner {
    display: flex;
    align-items: flex-start;
    gap: 0.75rem;
    border-bottom: 1px solid color-mix(in oklab, var(--warning) 40%, var(--hairline));
    background: color-mix(in oklab, var(--warning) 10%, var(--surface-1));
    padding: 0.8rem 1.5rem;
  }

  .icon {
    flex-shrink: 0;
    font-size: 1rem;
    line-height: 1.3;
    color: var(--warning);
  }

  .body {
    min-width: 0;
    flex: 1;
  }
  b {
    font-size: 0.88rem;
    font-weight: 650;
  }
  p {
    margin: 0.2rem 0 0;
    max-width: 78ch;
    font-size: 0.82rem;
    line-height: 1.5;
    color: var(--ink-2);
  }

  code {
    display: block;
    margin-top: 0.5rem;
    overflow-x: auto;
    border: 1px solid var(--hairline);
    border-radius: 7px;
    background: var(--plane);
    padding: 0.5rem 0.7rem;
    font-family: var(--font-mono);
    font-size: 0.72rem;
    line-height: 1.6;
    color: var(--ink);
    white-space: nowrap;
  }

  .tip {
    font-size: 0.76rem;
    color: var(--muted);
  }
  .tip b {
    font-family: var(--font-mono);
    font-size: 0.74rem;
    font-weight: 600;
  }

  .key {
    font-family: var(--font-mono);
    font-size: 0.78rem;
    font-weight: 600;
    color: var(--ink);
  }

  button {
    flex-shrink: 0;
    border: 0;
    background: none;
    padding: 0;
    font-size: 0.85rem;
    color: var(--muted);
    cursor: pointer;
  }
  button:hover {
    color: var(--ink);
  }
</style>
