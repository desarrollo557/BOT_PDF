<script lang="ts">
  import { steerBatch, steerJob } from '$lib/api';
  import type { JobState } from '$lib/types';

  interface Props {
    /** El documento, o el lote entero. Uno de los dos. */
    jobId?: string;
    batchId?: string;
    /**
     * En qué está ahora: decide si se ofrece pausar o reanudar.
     *
     * No se llama `state` porque ese nombre tapa la runa `$state` de Svelte y
     * las variables locales dejan de ser reactivas sin decirlo.
     */
    runState: JobState;
    /** Cuántos documentos abarca la orden, cuando es un lote. */
    documents?: number;
  }

  let { jobId, batchId, runState, documents = 1 }: Props = $props();

  let working = $state(false);
  let confirming = $state(false);
  let error = $state<string | null>(null);
  let note = $state<string | null>(null);

  /**
   * Lo que se ofrece depende de dónde está el trabajo. Pausar y reanudar nunca
   * salen a la vez: son la misma decisión vista desde los dos lados, y mostrar
   * las dos obligaría a leer cuál está activa.
   */
  const paused = $derived(runState === 'paused');
  const steerable = $derived(
    runState === 'queued' || runState === 'running' || runState === 'paused'
  );

  async function send(action: 'pause' | 'resume' | 'cancel') {
    working = true;
    error = null;
    note = null;
    try {
      if (batchId) await steerBatch(batchId, action);
      else if (jobId) await steerJob(jobId, action);
    } catch (problem) {
      const message = (problem as Error).message;
      // Que el trabajo ya hubiera terminado no es un fallo: el operador pidió
      // que dejara de correr y no está corriendo. Se cuenta, no se alarma.
      if (message.includes('ya terminó')) {
        note = 'El documento ya había terminado cuando llegó la orden.';
      } else {
        error = message;
      }
    } finally {
      working = false;
      confirming = false;
    }
  }
</script>

{#if steerable}
  <div class="controls">
    {#if confirming}
      <span class="ask">
        {#if batchId}
          ¿Cancelar los {documents} documentos del lote?
        {:else}
          ¿Cancelar este documento?
        {/if}
      </span>
      <button class="btn btn-sm btn-danger" disabled={working} onclick={() => send('cancel')}>
        Sí, cancelar
      </button>
      <button class="btn btn-sm" disabled={working} onclick={() => (confirming = false)}>
        Seguir
      </button>
    {:else}
      {#if paused}
        <button class="btn btn-sm btn-tonal" disabled={working} onclick={() => send('resume')}>
          Reanudar
        </button>
      {:else}
        <button class="btn btn-sm" disabled={working} onclick={() => send('pause')}>Pausar</button>
      {/if}
      <button class="btn btn-sm btn-ghost" disabled={working} onclick={() => (confirming = true)}>
        Cancelar
      </button>
    {/if}
  </div>

  {#if paused && !confirming}
    <p class="note">
      Detenido entre dos páginas. El documento sigue abierto, así que al reanudar continúa por
      donde iba y no vuelve a empezar.
    </p>
  {/if}

  {#if note}
    <p class="note">{note}</p>
  {/if}

  {#if error}
    <p class="inline-error">{error}</p>
  {/if}
{/if}

<style>
  .controls {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  /* Los botones son los globales en tamaño `btn-sm`. Reanudar va en tonal
     porque es la acción que el operador busca cuando ve esto, y se distingue
     sin gritar; cancelar pide confirmación, y sólo la confirmación va en rojo. */

  .ask {
    font-size: var(--text-sm);
    color: var(--ink-2);
  }

  .note {
    margin: 0.4rem 0 0;
    font-size: var(--text-xs);
    color: var(--muted);
  }
</style>
