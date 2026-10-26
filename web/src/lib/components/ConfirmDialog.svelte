<script lang="ts">
  import { confirmacion } from '$lib/confirmar.svelte';

  const pregunta = $derived(confirmacion.actual);

  let aceptar = $state<HTMLButtonElement | null>(null);
  let volver = $state<HTMLButtonElement | null>(null);

  // El foco arranca en «volver» cuando la acción destruye algo: un Enter dado
  // por costumbre no debe borrar nada.
  $effect(() => {
    if (!pregunta) return;
    (pregunta.peligro ? volver : aceptar)?.focus();
  });

  function teclas(evento: KeyboardEvent) {
    if (!pregunta) return;
    if (evento.key === 'Escape') {
      evento.preventDefault();
      confirmacion.responder(false);
    }
  }
</script>

<svelte:window onkeydown={teclas} />

{#if pregunta}
  <div class="velo" role="presentation" onclick={() => confirmacion.responder(false)}></div>
  <div
    class="hoja"
    role="alertdialog"
    aria-modal="true"
    aria-labelledby="confirmar-titulo"
    aria-describedby={pregunta.mensaje ? 'confirmar-mensaje' : undefined}
    data-peligro={pregunta.peligro ? '' : undefined}
  >
    <h2 id="confirmar-titulo">{pregunta.titulo}</h2>
    {#if pregunta.mensaje}
      <p id="confirmar-mensaje">{pregunta.mensaje}</p>
    {/if}
    <div class="botones">
      <!-- Los botones de siempre: volver es el secundario y aceptar el primario,
           o el de peligro cuando lo que se acepta destruye algo. -->
      <button bind:this={volver} type="button" class="btn" onclick={() => confirmacion.responder(false)}>
        {pregunta.volver ?? 'Volver'}
      </button>
      <button
        bind:this={aceptar}
        type="button"
        class={pregunta.peligro ? 'btn btn-danger' : 'btn btn-primary'}
        onclick={() => confirmacion.responder(true)}
      >
        {pregunta.aceptar ?? 'Aceptar'}
      </button>
    </div>
  </div>
{/if}

<style>
  .velo {
    position: fixed;
    inset: 0;
    z-index: 90;
    background: var(--scrim);
  }

  .hoja {
    position: fixed;
    top: 50%;
    left: 50%;
    z-index: 91;
    width: min(26rem, calc(100vw - 2rem));
    transform: translate(-50%, -50%);
    border: 1px solid var(--hairline);
    border-radius: var(--radius-xl);
    background: var(--surface-2);
    box-shadow: var(--shadow-lg);
    padding: 1.2rem 1.3rem 1rem;
  }
  .hoja[data-peligro] {
    border-top: 3px solid var(--critical);
  }

  h2 {
    margin: 0;
    font-size: var(--text-lg);
    font-weight: 650;
    letter-spacing: -0.01em;
  }

  p {
    margin: 0.5rem 0 0;
    font-size: var(--text-md);
    line-height: 1.5;
    color: var(--ink-2);
  }

  .botones {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    margin-top: 1.1rem;
  }

</style>
