<script lang="ts">
  import { documentFuidUrl, fuidTabla } from '$lib/api';
  import type { FuidTabla } from '$lib/types';

  /**
   * El Formato Único de Inventario Documental, en pantalla.
   *
   * Existe porque el archivo pidió que el técnico y el de calidad pudieran
   * revisar la planilla sin llevársela: un Excel que sale de la máquina deja de
   * estar bajo control del archivo en cuanto se copia a un correo, y quien la
   * revisa no es quien la firma.
   *
   * La tabla sale del archivo que hay en el disco, no de una armada aquí con
   * los datos del informe. Es lo mismo que hace la descarga, y por el mismo
   * motivo: lo que se mira y lo que se firma tienen que ser el mismo documento.
   *
   * Quién puede descargarlo lo contesta el servicio en `descargable`, y esta
   * pantalla obedece. No lo deduce del perfil por su cuenta, para que la regla
   * viva en un solo sitio y no en dos que puedan discrepar.
   *
   * Sobre el aspecto: la cabecera va a dos niveles como en el papel, con los
   * grupos del formato —consecutivo, fechas extremas, unidad de conservación—
   * abarcando sus columnas. Aplanada obligaba a leer «FECHAS EXTREMAS Final»
   * y «CONSECUTIVO Final» para saber final de qué, y no se parecía al formato
   * que el operador tiene delante en papel.
   *
   * El color hace un solo trabajo, y es el que importa al revisar: distinguir
   * **lo que el papel dijo** de **lo que no aplica**. Un `N/A` es correcto -- lo
   * manda el instructivo del formato -- pero no es un dato, así que se apaga, y
   * lo que queda encendido es exactamente lo que hay que comprobar. Ningún color
   * de serie entra aquí: en esta casa un color de serie significa «esta porción
   * de los datos» y nada más.
   */
  let { jobId, nombre = '' }: { jobId: string; nombre?: string } = $props();

  let abierto = $state(false);
  let planilla = $state<FuidTabla | null>(null);
  let cargando = $state(false);
  let error = $state<string | null>(null);

  /** Lo que el formato manda escribir donde no hay dato. No es un dato. */
  const NO_APLICA = new Set(['N/A', 'NA', 'N.A.', '-', '—']);

  /**
   * En qué columna empieza cada grupo del formato.
   *
   * Se usa para pintar el filete que los separa: dentro de un grupo las
   * columnas se rozan, y entre dos grupos hay una línea que se ve. Sin eso, las
   * dieciséis columnas son una reja uniforme en la que la vista no encuentra
   * dónde acaba la unidad de conservación y dónde empiezan los folios.
   */
  const bordes = $derived.by(() => {
    const inicios = new Set<number>();
    let columna = 0;
    for (const grupo of planilla?.grupos ?? []) {
      inicios.add(columna);
      columna += grupo.ancho;
    }
    return inicios;
  });

  /**
   * En qué columna del cuerpo empieza el grupo que ocupa este puesto.
   *
   * La cabecera tiene once celdas y el cuerpo dieciséis, así que el índice de
   * una no sirve para preguntarle nada a la otra.
   */
  function columnaDe(puesto: number): number {
    let columna = 0;
    for (let i = 0; i < puesto; i += 1) columna += planilla?.grupos[i]?.ancho ?? 1;
    return columna;
  }

  /** Qué columnas llevan cifras, para alinearlas a la derecha y en tabulares. */
  const numericas = $derived.by(() => {
    const cuales = new Set<number>();
    (planilla?.columnas ?? []).forEach((nombre, indice) => {
      if (/orden|folios/i.test(nombre)) cuales.add(indice);
    });
    return cuales;
  });

  /**
   * Lo que mide la fila de grupos, medido y no supuesto.
   *
   * La segunda fila de la cabecera se pega debajo de la primera, y hacerlo con
   * una constante funciona hasta que un título largo envuelve -- «FECHAS
   * EXTREMAS (DD-MM-AAAA)» lo hace -- y entonces las dos filas se solapan justo
   * al desplazarse, que es cuando la cabecera fija tenía que servir de algo.
   */
  let altoDeLosGrupos = $state(0);

  async function abrir() {
    abierto = true;
    if (planilla || cargando) return;
    cargando = true;
    error = null;
    try {
      planilla = await fuidTabla(jobId);
    } catch (problema) {
      error = (problema as Error).message;
    } finally {
      cargando = false;
    }
  }

  function cerrar() {
    abierto = false;
  }

  /** Escape cierra el diálogo. Es la salida que se busca sin mirar. */
  function porTeclado(evento: KeyboardEvent) {
    if (evento.key === 'Escape') cerrar();
  }

  /** El texto de la cabecera del formato, sin su propia etiqueta repetida. */
  function sinRotulo(valor: string): string {
    return valor.replace(/^(OFICINA PRODUCTORA|OBJETO)\s*:\s*/i, '').trim();
  }
</script>

<svelte:window onkeydown={abierto ? porTeclado : undefined} />

<button class="ver" onclick={abrir}>
  <svg viewBox="0 0 16 16" aria-hidden="true">
    <rect x="2.5" y="2" width="11" height="12" rx="1.5" />
    <path d="M5 6h6M5 8.5h6M5 11h3.5" />
  </svg>
  ver el FUID
</button>

{#if abierto}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div class="scrim" role="presentation" onclick={cerrar}></div>

  <div
    class="sheet"
    role="dialog"
    aria-modal="true"
    aria-label="Formato Único de Inventario Documental"
  >
    <header>
      <div class="titulo">
        <span class="sello">FO-GD-008</span>
        <b>Formato Único de Inventario Documental</b>
        {#if nombre}<small>{nombre}</small>{/if}
      </div>
      <button class="cerrar" onclick={cerrar} aria-label="Cerrar">
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="M4 4l8 8M12 4l-8 8" />
        </svg>
      </button>
    </header>

    {#if cargando}
      <p class="quiet">Leyendo la planilla…</p>
    {:else if error}
      <p class="bad" role="alert">{error}</p>
    {:else if planilla}
      <dl class="cabecera">
        {#if planilla.oficina_productora}
          <div>
            <dt>Oficina productora</dt>
            <dd>{sinRotulo(planilla.oficina_productora)}</dd>
          </div>
        {/if}
        {#if planilla.objeto}
          <div class="ancho">
            <dt>Objeto</dt>
            <dd>{sinRotulo(planilla.objeto)}</dd>
          </div>
        {/if}
        <div class="cuenta">
          <dt>Registros</dt>
          <dd><span class="pastilla tabular">{planilla.total}</span></dd>
        </div>
      </dl>

      <!-- La tabla del formato tiene dieciséis columnas y no cabe en ninguna
           pantalla: se desplaza sola, dentro de su caja, en vez de empujar el
           ancho de la página. La primera columna y la cabecera se quedan
           fijas, que es lo que permite irse a las notas sin perder de vista
           de qué fila son. -->
      <div class="tabla">
        <table>
          <thead>
            <tr class="grupos" bind:clientHeight={altoDeLosGrupos}>
              {#each planilla.grupos as grupo, indice (indice)}
                {#if grupo.ancho === 1}
                  <th
                    rowspan="2"
                    class:primera={indice === 0}
                    class:cifra={numericas.has(columnaDe(indice))}
                    class:corte={indice !== 0}
                  >
                    {grupo.titulo}
                  </th>
                {:else}
                  <th colspan={grupo.ancho} class="agrupada corte">{grupo.titulo}</th>
                {/if}
              {/each}
            </tr>
            <tr class="sub" style="--alto-grupos: {altoDeLosGrupos}px">
              {#each planilla.subcolumnas as sub, indice (indice)}
                {#if sub}
                  <th class:corte={bordes.has(indice)} class:cifra={numericas.has(indice)}>
                    {sub}
                  </th>
                {/if}
              {/each}
            </tr>
          </thead>
          <tbody>
            {#each planilla.filas as fila, numero (numero)}
              <tr>
                {#each fila as celda, indice (indice)}
                  <td
                    class:primera={indice === 0}
                    class:corte={bordes.has(indice) && indice !== 0}
                    class:vacia={!celda || NO_APLICA.has(celda.toUpperCase())}
                    class:cifra={numericas.has(indice)}
                    class:asunto={indice === 2}
                  >
                    {celda || 'N/A'}
                  </td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      <footer>
        {#if planilla.descargable}
          <a class="bajar" href={documentFuidUrl(jobId)}>
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M8 2.5v7m0 0 3-3m-3 3-3-3" />
              <path d="M3 11.5v1A1.5 1.5 0 0 0 4.5 14h7a1.5 1.5 0 0 0 1.5-1.5v-1" />
            </svg>
            descargar el Excel
          </a>
        {:else}
          <!-- Dicho, y no sólo escondido: un botón que desaparece sin
               explicación se lee como una avería del programa. -->
          <p class="nota">
            Su perfil no descarga el Excel de esta planilla. Lo que ve aquí es el archivo tal
            como quedó escrito en el disco.
          </p>
        {/if}
      </footer>
    {/if}
  </div>
{/if}

<style>
  .ver {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    border: 1px solid var(--hairline);
    border-radius: 6px;
    background: transparent;
    padding: 0.35rem 0.7rem;
    font: inherit;
    font-family: var(--font-mono);
    font-size: 0.75rem;
    color: var(--ink-2);
    cursor: pointer;
    transition:
      border-color 0.15s,
      color 0.15s,
      background 0.15s;
  }
  .ver svg {
    width: 13px;
    height: 13px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.4;
    stroke-linecap: round;
  }
  .ver:hover {
    border-color: var(--accent);
    background: var(--accent-soft);
    color: var(--accent);
  }

  .scrim {
    position: fixed;
    inset: 0;
    z-index: 60;
    background: color-mix(in oklab, var(--ink) 42%, transparent);
    backdrop-filter: blur(2px);
  }
  .sheet {
    position: fixed;
    z-index: 61;
    top: 50%;
    left: 50%;
    display: flex;
    flex-direction: column;
    width: min(78rem, calc(100vw - 2rem));
    max-height: min(46rem, calc(100dvh - 3rem));
    translate: -50% -50%;
    overflow: hidden;
    border: 1px solid var(--hairline);
    border-radius: 14px;
    background: var(--surface-2);
    box-shadow: var(--shadow);
  }

  /* La banda del formato. En el papel el encabezado va sobre fondo y con el
     código del formato a la derecha; aquí se cita esa idea sin imitar el
     membrete, que es de la Universidad y no de este programa. */
  header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
    border-bottom: 1px solid var(--hairline);
    background: var(--plane);
    padding: 0.9rem 1.1rem;
  }
  .titulo {
    min-width: 0;
  }
  .sello {
    display: inline-block;
    margin-bottom: 0.3rem;
    border: 1px solid color-mix(in oklab, var(--accent) 35%, transparent);
    border-radius: 4px;
    background: var(--accent-soft);
    padding: 0.08rem 0.4rem;
    font-family: var(--font-mono);
    font-size: 0.64rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    color: var(--accent);
  }
  .titulo b {
    display: block;
    font-size: 0.95rem;
    font-weight: 650;
    letter-spacing: -0.01em;
  }
  .titulo small {
    display: block;
    margin-top: 0.15rem;
    font-family: var(--font-mono);
    font-size: 0.74rem;
    color: var(--muted);
    overflow-wrap: anywhere;
  }
  .cerrar {
    flex-shrink: 0;
    display: grid;
    place-items: center;
    width: 26px;
    height: 26px;
    border: 1px solid transparent;
    border-radius: 6px;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    transition:
      border-color 0.15s,
      color 0.15s;
  }
  .cerrar svg {
    width: 13px;
    height: 13px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.6;
    stroke-linecap: round;
  }
  .cerrar:hover {
    border-color: var(--hairline);
    color: var(--ink);
  }

  .cabecera {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.55rem 2rem;
    border-bottom: 1px solid var(--rule);
    margin: 0;
    padding: 0.8rem 1.1rem;
  }
  .cabecera div {
    min-width: 0;
  }
  .cabecera .ancho {
    flex: 1 1 22rem;
  }
  .cabecera .cuenta {
    margin-left: auto;
  }
  dt {
    font-size: 0.6rem;
    font-weight: 600;
    letter-spacing: 0.055em;
    text-transform: uppercase;
    color: var(--muted);
  }
  dd {
    margin: 0.15rem 0 0;
    font-size: 0.84rem;
    line-height: 1.4;
    color: var(--ink-2);
  }
  .pastilla {
    display: inline-block;
    border-radius: 999px;
    background: var(--accent-soft);
    padding: 0.1rem 0.55rem;
    font-size: 0.82rem;
    font-weight: 650;
    color: var(--accent);
  }

  .tabla {
    flex: 1;
    min-height: 0;
    overflow: auto;
    background: var(--surface-2);
  }
  table {
    border-collapse: separate;
    border-spacing: 0;
    width: max-content;
    min-width: 100%;
    font-size: 0.78rem;
  }

  /* -- la cabecera, a dos niveles y fija ---------------------------------- */
  thead th {
    position: sticky;
    z-index: 2;
    border-bottom: 1px solid var(--hairline);
    background: var(--plane);
    padding: 0.4rem 0.6rem;
    text-align: left;
    font-size: 0.66rem;
    font-weight: 650;
    line-height: 1.25;
    letter-spacing: 0.01em;
    /* Dieciséis columnas: sin un tope, el nombre largo de una las estira todas
       y la cabecera se come media pantalla. */
    max-width: 11rem;
    color: var(--ink-2);
    vertical-align: bottom;
  }
  .grupos th {
    top: 0;
  }
  .grupos th[rowspan] {
    /* Una columna sin segundo nivel ocupa las dos filas, así que su borde de
       abajo es el de la cabecera entera. */
    vertical-align: bottom;
  }
  /* Un grupo se anuncia: centrado, en versalitas y en el color del acento, para
     que se lea como el rótulo de una sección y no como una columna más. */
  .grupos th.agrupada {
    border-bottom: 1px solid var(--rule);
    text-align: center;
    font-size: 0.6rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--accent);
  }
  .sub th {
    top: var(--alto-grupos, 1.65rem);
    font-size: 0.64rem;
    font-weight: 600;
    color: var(--muted);
  }
  /* Un encabezado de cifras se alinea con sus cifras. Desalineados, la columna
     se lee como dos columnas estrechas en vez de como una. */
  thead th.cifra {
    text-align: right;
  }

  /* -- el cuerpo ---------------------------------------------------------- */
  td {
    border-bottom: 1px solid var(--rule);
    padding: 0.38rem 0.6rem;
    max-width: 17rem;
    vertical-align: top;
    line-height: 1.4;
    color: var(--ink-2);
    overflow-wrap: anywhere;
  }
  tbody tr:nth-child(even) td {
    background: color-mix(in oklab, var(--plane) 55%, transparent);
  }
  tbody tr:hover td {
    background: var(--accent-soft);
  }

  /* El filete que separa un grupo del formato del siguiente. Dentro de un grupo
     las columnas se rozan; entre dos hay una línea que se ve. */
  .corte {
    border-left: 1px solid var(--hairline);
  }

  /* La primera columna se queda fija al desplazarse a lo ancho: es el número de
     orden, y sin él las notas de la derecha no dicen de qué fila son. */
  .primera {
    position: sticky;
    left: 0;
    z-index: 1;
    border-right: 1px solid var(--hairline);
    /* Una sombra hacia la derecha, para que al desplazarse a lo ancho la
       columna fija se lea como puesta encima y no como pegada a una columna
       cortada por la mitad. Es lo único que distingue las dos cosas. */
    box-shadow: 3px 0 6px -3px color-mix(in oklab, var(--ink) 22%, transparent);
    background: var(--surface-2);
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    color: var(--ink);
  }
  thead .primera {
    z-index: 3;
  }
  tbody tr:nth-child(even) .primera {
    background: color-mix(in oklab, var(--plane) 55%, var(--surface-2));
  }
  tbody tr:hover .primera {
    background: color-mix(in oklab, var(--accent) 9%, var(--surface-2));
  }

  /* Lo que de verdad se lee de una fila: de qué es el documento. */
  .asunto {
    min-width: 14rem;
    font-weight: 550;
    color: var(--ink);
  }

  .cifra {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }

  /* Lo que no aplica se apaga. El formato manda escribir N/A y eso es correcto,
     pero no es un dato: apagarlo deja encendido exactamente lo que hay que
     comprobar, que es para lo que se abre esta vista. */
  .vacia {
    font-size: 0.72rem;
    color: color-mix(in oklab, var(--muted) 70%, transparent);
  }

  footer {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 1rem;
    border-top: 1px solid var(--hairline);
    background: var(--plane);
    padding: 0.7rem 1.1rem;
  }
  .bajar {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    border: 1px solid var(--accent);
    border-radius: 6px;
    background: var(--accent-soft);
    padding: 0.38rem 0.8rem;
    font-family: var(--font-mono);
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--accent);
    text-decoration: none;
    transition:
      background 0.15s,
      color 0.15s;
  }
  .bajar svg {
    width: 13px;
    height: 13px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.5;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .bajar:hover {
    background: var(--accent);
    color: var(--surface-2);
  }
  .nota {
    margin: 0;
    font-size: 0.78rem;
    line-height: 1.5;
    color: var(--muted);
    text-align: right;
  }

  .quiet {
    margin: 0;
    padding: 2rem 1.1rem;
    font-size: 0.84rem;
    color: var(--muted);
  }
  .bad {
    margin: 1.1rem;
    border: 1px solid var(--critical);
    border-radius: 9px;
    background: color-mix(in oklab, var(--critical) 8%, transparent);
    padding: 0.7rem 0.85rem;
    font-size: 0.84rem;
    line-height: 1.5;
    color: var(--critical);
  }
</style>
