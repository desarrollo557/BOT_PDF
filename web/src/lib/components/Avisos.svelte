<script lang="ts">
  import { avisos } from '$lib/avisos.svelte';
  import Icono from '$lib/components/Icono.svelte';
</script>

<!-- Abajo a la izquierda: la consola ocupa el borde derecho. -->
<ol class="avisos" aria-live="polite">
  {#each avisos.lista as aviso (aviso.id)}
    <li class="panel panel-sm" data-tono={aviso.tono} role={aviso.tono === 'error' ? 'alert' : 'status'}>
      <div class="texto">
        <b>{aviso.titulo}</b>
        {#if aviso.detalle}<span>{aviso.detalle}</span>{/if}
      </div>
      <button
        type="button"
        class="btn btn-icon cerrar"
        aria-label="Cerrar aviso"
        onclick={() => avisos.quitar(aviso.id)}
      >
        <Icono nombre="cerrar" />
      </button>
    </li>
  {/each}
</ol>

<style>
  .avisos {
    position: fixed;
    bottom: 1rem;
    left: 1rem;
    z-index: 80;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    width: min(24rem, calc(100vw - 2rem));
    margin: 0;
    padding: 0;
    list-style: none;
    pointer-events: none;
  }

  /* La tarjeta es el `.panel` común; aquí sólo la raya del tono, que dice de
     qué clase es el aviso antes de leerlo, y la entrada. */
  li {
    display: flex;
    align-items: flex-start;
    gap: var(--space-2);
    border-left: 4px solid var(--accent);
    pointer-events: auto;
    animation: entrada var(--duration) var(--ease-out);
  }
  li[data-tono='error'] {
    border-left-color: var(--critical);
  }
  li[data-tono='aviso'] {
    border-left-color: var(--warning);
  }
  li[data-tono='ok'] {
    border-left-color: var(--good);
  }

  .texto {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 0.15rem;
    min-width: 0;
    font-size: var(--text-sm);
    line-height: 1.4;
  }
  .texto b {
    font-weight: 600;
  }
  .texto span {
    color: var(--ink-2);
    overflow-wrap: anywhere;
  }

  /* El botón de cerrar es el `.btn-icon` común; sólo se encoge para no
     estirar la tarjeta del aviso. */
  .cerrar {
    flex-shrink: 0;
    width: 1.6rem;
    height: 1.6rem;
    margin: -0.2rem -0.1rem 0 0;
  }
</style>
