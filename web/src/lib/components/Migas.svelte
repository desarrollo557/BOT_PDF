<script lang="ts">
  import { afterNavigate, goto } from '$app/navigation';
  import { page } from '$app/state';
  import Icono from '$lib/components/Icono.svelte';
  import { migasDe, padreDe, vista } from '$lib/navegacion.svelte';

  const migas = $derived(migasDe(page.url, vista.titulo));
  const padre = $derived(padreDe(page.url));

  /** De dónde se llegó, para volver con la flecha del navegador cuando es el padre. */
  let anterior = $state<string | null>(null);
  // Al abrir la aplicación no se viene de ninguna parte: SvelteKit da un
  // `from` con la URL en null, y leerla sin mirar rompía la carga.
  afterNavigate(({ from }) => {
    anterior = from?.url ? from.url.pathname + from.url.search : null;
  });

  /**
   * Sube un nivel. Si se llegó justo desde el padre, se vuelve por el
   * historial: así el archivo reaparece con la búsqueda, la pestaña y el
   * desplazamiento que tenía. Si no -- un enlace copiado, una recarga --, se
   * navega al padre.
   */
  function volver() {
    if (!padre) return;
    if (anterior === padre) history.back();
    else void goto(padre);
  }
</script>

{#if migas.length}
  <nav class="migas" aria-label="Dónde está">
    <button type="button" class="btn btn-sm volver" onclick={volver}>
      <Icono nombre="atras" />
      Volver
    </button>
    <ol>
      {#each migas as miga, i (i)}
        <li>
          {#if miga.href}
            <a href={miga.href}>{miga.etiqueta}</a>
          {:else}
            <span aria-current="page" title={miga.etiqueta}>{miga.etiqueta}</span>
          {/if}
        </li>
      {/each}
    </ol>
  </nav>
{/if}

<style>
  .migas {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-3);
    margin-bottom: var(--space-4);
    font-size: var(--text-sm);
  }

  /* «Volver» es un `.btn` pequeño; la flecha queda pegada al borde izquierdo
     porque apunta hacia allí. */
  .volver {
    gap: 0.3rem;
    padding-left: 0.45rem;
  }

  ol {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    min-width: 0;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li {
    display: flex;
    align-items: center;
    min-width: 0;
  }
  li + li::before {
    content: '›';
    margin: 0 0.45rem;
    color: var(--muted);
  }
  a {
    color: var(--accent);
    text-decoration: none;
  }
  a:hover {
    text-decoration: underline;
  }
  span {
    overflow: hidden;
    max-width: 32rem;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--ink-2);
  }
</style>
