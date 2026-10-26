<script lang="ts" module>
  export interface Proceso {
    /** El `id` del monitor en la página, para llevar la vista hasta él. */
    ancla: string;
    tipo: 'carpeta' | 'lote' | 'documento';
    nombre: string;
    estado: 'procesando' | 'en cola' | 'en pausa' | 'vigilando';
    /** De 0 a 100, si se sabe. */
    avance: number | null;
    detalle: string;
  }
</script>

<script lang="ts">
  import Icono from '$lib/components/Icono.svelte';

  interface Props {
    procesos: Proceso[];
    onagregar: () => void;
    /** Mientras se suben archivos no se ofrece otra carga: la que va no terminó. */
    subiendo?: boolean;
  }

  let { procesos, onagregar, subiendo = false }: Props = $props();

  const TIPOS = { carpeta: 'Carpeta', lote: 'Lote', documento: 'Documento' };
  /* El estado viaja en minúscula porque también se compone en frases; como
     etiqueta va con mayúscula inicial, igual que el resto de la aplicación. */
  const ESTADOS: Record<Proceso['estado'], string> = {
    procesando: 'Procesando',
    'en cola': 'En cola',
    'en pausa': 'En pausa',
    vigilando: 'Vigilando'
  };

  /** El estado es la `.pill` común: el acento lo que corre (algo en curso), el
   * aviso lo pausado y neutro lo que espera turno. */
  const TONO: Record<Proceso['estado'], string> = {
    procesando: '',
    vigilando: '',
    'en pausa': 'pill-warn',
    'en cola': 'pill-neutral'
  };

  function ir(ancla: string) {
    document.getElementById(ancla)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
</script>

<section class="cola panel" aria-label="Procesos en curso">
  <header>
    <h2>Procesos en curso</h2>
    <span class="pill cuenta tabular">{procesos.length}</span>
  </header>

  <ol>
    {#each procesos as proceso, i (proceso.ancla)}
      <li>
        <button type="button" onclick={() => ir(proceso.ancla)} title="Ver su avance">
          <span class="orden tabular">{i + 1}</span>
          <span class="texto">
            <span class="linea">
              <small class="caps">{TIPOS[proceso.tipo]}</small>
              <span class="pill estado {TONO[proceso.estado]}">{ESTADOS[proceso.estado]}</span>
            </span>
            <b title={proceso.nombre}>{proceso.nombre}</b>
            <span class="detalle tabular">{proceso.detalle}</span>
            {#if proceso.avance !== null}
              <span class="progress progress-sm pista">
                <span class="progress-fill" style:width={`${proceso.avance}%`}></span>
              </span>
            {/if}
          </span>
        </button>
      </li>
    {/each}
  </ol>

  <button type="button" class="btn btn-primary btn-block" onclick={onagregar} disabled={subiendo}>
    <Icono nombre="mas" />
    {subiendo ? 'Subiendo archivos…' : 'Agregar otro proceso a la cola'}
  </button>
  <p class="nota">
    Lo nuevo se suma a la cola: sus documentos esperan turno hasta que haya un trabajador libre, sin
    detener lo que ya corre.
  </p>
</section>

<style>
  .cola {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  h2 {
    margin: 0;
    font-size: var(--text-lg);
    font-weight: 650;
    letter-spacing: -0.015em;
  }
  .cuenta {
    font-family: var(--font-mono);
  }

  ol {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    max-height: 22rem;
    overflow-y: auto;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  /* Cada fila entera es el control que lleva al monitor de ese proceso: no es
     un `.btn`, es una fila de la lista que se puede pulsar. */
  li button {
    display: flex;
    width: 100%;
    gap: var(--space-2);
    border: 1px solid var(--rule);
    border-radius: var(--radius);
    background: var(--surface-1);
    padding: var(--space-2) var(--space-3);
    font: inherit;
    text-align: left;
    color: inherit;
    cursor: pointer;
    transition: border-color var(--duration-fast) var(--ease-out);
  }
  li button:hover {
    border-color: var(--control);
  }
  .orden {
    flex-shrink: 0;
    width: 1.3rem;
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .texto {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .linea {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }
  .estado {
    padding-block: 0;
  }
  b {
    overflow: hidden;
    font-size: var(--text-md);
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .detalle {
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .pista {
    margin-top: 2px;
  }

  .nota {
    margin: 0;
    font-size: var(--text-xs);
    line-height: 1.45;
    color: var(--muted);
  }
</style>
