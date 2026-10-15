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

  function ir(ancla: string) {
    document.getElementById(ancla)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
</script>

<section class="cola" aria-label="Procesos en curso">
  <header>
    <h2>Procesos en curso</h2>
    <span class="pill pill-good cuenta tabular">{procesos.length}</span>
  </header>

  <ol>
    {#each procesos as proceso, i (proceso.ancla)}
      <li>
        <button type="button" onclick={() => ir(proceso.ancla)} title="Ver su avance">
          <span class="orden tabular">{i + 1}</span>
          <span class="texto">
            <span class="linea">
              <small>{TIPOS[proceso.tipo]}</small>
              <span
                class="pill estado"
                class:pill-good={proceso.estado === 'procesando' || proceso.estado === 'vigilando'}
                class:pill-warn={proceso.estado === 'en pausa'}>{ESTADOS[proceso.estado]}</span
              >
            </span>
            <b title={proceso.nombre}>{proceso.nombre}</b>
            <span class="detalle tabular">{proceso.detalle}</span>
            {#if proceso.avance !== null}
              <span class="pista"><span style:width={`${proceso.avance}%`}></span></span>
            {/if}
          </span>
        </button>
      </li>
    {/each}
  </ol>

  <button type="button" class="btn btn-primary btn-block" onclick={onagregar} disabled={subiendo}>
    <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M3 8h10" /></svg>
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
    gap: 0.8rem;
    border: 1px solid var(--hairline);
    border-radius: var(--radius-lg);
    background: var(--surface-2);
    padding: 1rem;
  }

  header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
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
    gap: 0.4rem;
    max-height: 22rem;
    overflow-y: auto;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li button {
    display: flex;
    width: 100%;
    gap: 0.6rem;
    border: 1px solid var(--rule);
    border-radius: var(--radius);
    background: var(--surface-1);
    padding: 0.55rem 0.65rem;
    text-align: left;
    color: inherit;
    cursor: pointer;
  }
  li button:hover {
    border-color: var(--axis);
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
    gap: 0.15rem;
    min-width: 0;
  }
  .linea {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
  }
  .linea small {
    font-size: var(--text-2xs);
    font-weight: 600;
    letter-spacing: var(--tracking-caps);
    text-transform: uppercase;
    color: var(--muted);
  }
  /* El estado es la `.pill` común: verde lo que corre, ámbar lo pausado y el
     acento lo que espera turno. */
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
    height: 4px;
    margin-top: 0.2rem;
    border-radius: var(--radius-pill);
    background: var(--grid);
  }
  .pista span {
    display: block;
    height: 100%;
    border-radius: var(--radius-pill);
    background: var(--accent);
    transition: width 0.3s;
  }

  .nota {
    margin: 0;
    font-size: var(--text-xs);
    line-height: 1.45;
    color: var(--muted);
  }
</style>
