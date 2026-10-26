<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchHealth, REQUIRED_API_REVISION, type Health } from '$lib/api';
  import Icono from '$lib/components/Icono.svelte';

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
      ['browse', 'el selector de carpetas'],
      ['inventory-task', 'inventariar sin dividir'],
      ['job-fuid', 'descargar el FUID de un documento'],
      ['perfiles', 'los perfiles de usuario'],
      ['usuario-siar', 'entrar como «siar»'],
      ['fuid-tabla', 'ver el FUID en pantalla'],
      ['agrupar-por-mes', 'un archivo por mes en la caja de correspondencia']
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
    <span class="icon"><Icono nombre="aviso" /></span>
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
    <button class="btn btn-icon cerrar" onclick={() => (dismissed = true)} aria-label="Cerrar">
      <Icono nombre="cerrar" />
    </button>
  </div>
{/if}

<style>
  .banner {
    display: flex;
    align-items: flex-start;
    gap: var(--space-3);
    border-bottom: 1px solid color-mix(in oklab, var(--warning) 40%, var(--hairline));
    /* El tinte de aviso común, sobre la superficie para que no transparente lo
       que pasa por debajo. */
    background: linear-gradient(var(--warning-soft), var(--warning-soft)), var(--surface-1);
    padding: 0.8rem 1.5rem;
  }

  /* El triángulo de aviso común, a la altura de la primera línea. */
  .icon {
    display: inline-flex;
    flex-shrink: 0;
    margin-top: 2px;
    color: var(--warning-ink);
    --icono: var(--text-lg);
  }

  .body {
    min-width: 0;
    flex: 1;
  }
  b {
    font-size: var(--text-md);
    font-weight: 650;
  }
  p {
    margin: 0.2rem 0 0;
    max-width: 78ch;
    font-size: var(--text-sm);
    line-height: 1.5;
    color: var(--ink-2);
  }

  code {
    display: block;
    margin-top: 0.5rem;
    overflow-x: auto;
    border: 1px solid var(--hairline);
    border-radius: var(--radius);
    background: var(--plane);
    padding: 0.5rem 0.7rem;
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    line-height: 1.6;
    color: var(--ink);
    white-space: nowrap;
  }

  .tip {
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .tip b {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    font-weight: 600;
  }

  .key {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    font-weight: 600;
    color: var(--ink);
  }

  .cerrar {
    flex-shrink: 0;
    margin-top: -0.3rem;
  }
</style>
