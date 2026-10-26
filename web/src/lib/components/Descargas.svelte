<script lang="ts" module>
  /**
   * Lo que se puede bajar de un documento, un lote o una carpeta, dicho igual
   * en todas las pantallas.
   *
   * Las descargas estaban repartidas en diez sitios, cada una con su botón y
   * su frase -- «exportar a Excel», «Inventario (Excel)», «Descargar inventario
   * general (N actas)» -- y no se sabía cuál era cuál. Aquí cada una dice qué
   * es, qué trae y en qué formato, y van agrupadas por lo que son: primero los
   * inventarios -- el de la habilidad, después el general del bot -- y luego
   * los archivos.
   */
  export interface Descarga {
    id: string;
    /** Qué es: «Índice electrónico», «Inventario de procesos». */
    titulo: string;
    /** Qué trae, en una línea: «Plantilla del cliente, una hoja por PDF». */
    detalle?: string;
    formato: 'Excel' | 'ZIP' | 'PDF' | 'JSON';
    /** Un enlace directo… */
    href?: string;
    /** …o una descarga que tiene que identificarse ante el servicio. */
    bajar?: () => Promise<void>;
    /** La descarga principal del grupo: va resaltada. */
    principal?: boolean;
  }

  export interface GrupoDeDescargas {
    titulo: string;
    items: Descarga[];
  }
</script>

<script lang="ts">
  import Icono from './Icono.svelte';

  let {
    grupos,
    titulo = 'Descargas'
  }: {
    grupos: GrupoDeDescargas[];
    titulo?: string;
  } = $props();

  const conItems = $derived(grupos.filter((grupo) => grupo.items.length));

  let ocupada = $state<string | null>(null);
  let fallo = $state<string | null>(null);

  async function correr(descarga: Descarga) {
    if (!descarga.bajar) return;
    ocupada = descarga.id;
    fallo = null;
    try {
      await descarga.bajar();
    } catch (problema) {
      fallo = (problema as Error).message;
    } finally {
      ocupada = null;
    }
  }
</script>

{#if conItems.length}
  <section class="descargas" aria-label={titulo}>
    <h3 class="caps">{titulo}</h3>
    {#each conItems as grupo (grupo.titulo)}
      <div class="grupo">
        {#if conItems.length > 1}<p class="grupo-titulo">{grupo.titulo}</p>{/if}
        <ul>
          {#each grupo.items as descarga (descarga.id)}
            <li>
              {#snippet contenido()}
                <span class="icono"><Icono nombre="descargar" /></span>
                <span class="texto">
                  <span class="titulo">
                    {ocupada === descarga.id ? 'Descargando…' : descarga.titulo}
                  </span>
                  {#if descarga.detalle}<span class="detalle">{descarga.detalle}</span>{/if}
                </span>
                <span class="pill pill-neutral pill-sm formato">{descarga.formato}</span>
              {/snippet}
              {#if descarga.href && !descarga.bajar}
                <a
                  class="item panel panel-sm panel-interactive"
                  class:principal={descarga.principal}
                  href={descarga.href}
                  download
                >
                  {@render contenido()}
                </a>
              {:else}
                <button
                  class="item panel panel-sm panel-interactive"
                  class:principal={descarga.principal}
                  onclick={() => correr(descarga)}
                  disabled={ocupada === descarga.id}
                >
                  {@render contenido()}
                </button>
              {/if}
            </li>
          {/each}
        </ul>
      </div>
    {/each}
    {#if fallo}<p class="inline-error">{fallo}</p>{/if}
  </section>
{/if}

<style>
  .descargas {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  h3 {
    margin: 0;
  }
  .grupo {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }
  .grupo-titulo {
    margin: 0.2rem 0 0;
    font-size: var(--text-xs);
    font-weight: 600;
    color: var(--ink-2);
  }
  ul {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  /* Cada descarga es una fila entera que se pulsa: la tarjeta-control común
     (`.panel-interactive`). Aquí sólo la fila y dos casos propios. */
  .item {
    display: flex;
    width: 100%;
    align-items: center;
    gap: var(--space-2);
    text-align: left;
  }
  /* Apagada mientras baja: no es una opción que no se pueda elegir (borde
     punteado), es una descarga en curso. */
  .item:disabled {
    border-style: solid;
    background: var(--surface-2);
    opacity: 0.6;
    cursor: progress;
  }
  .item.principal {
    border-color: color-mix(in srgb, var(--accent) 45%, transparent);
    background: color-mix(in srgb, var(--accent) 6%, var(--surface-2));
  }
  .icono {
    display: inline-flex;
    flex: none;
    color: var(--accent);
  }
  .texto {
    display: flex;
    min-width: 0;
    flex: 1;
    flex-direction: column;
    gap: 0.05rem;
  }
  .titulo {
    font-size: var(--text-sm);
    font-weight: 600;
  }
  .detalle {
    font-size: var(--text-xs);
    color: var(--muted);
  }
  /* El formato es una `.pill` neutra, en versalitas. */
  .formato {
    flex: none;
    letter-spacing: var(--tracking-caps);
    text-transform: uppercase;
  }
</style>
