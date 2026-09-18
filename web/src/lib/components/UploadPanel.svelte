<script lang="ts">
  import { fetchHealth, type Health } from '$lib/api';
  import Dropzone from '$lib/components/Dropzone.svelte';
  import FolderPanel from '$lib/components/FolderPanel.svelte';
  import { HABILIDADES, RESULTADOS, motivoNoDisponible } from '$lib/habilidades';
  import { lecturaOptions, reasonForLectura, type LecturaChoice } from '$lib/lectura';
  import { oracleOptions, reasonFor, type OracleChoice } from '$lib/oracles';
  import type { TipoPedido } from '$lib/tipos';
  import type { TaskKind } from '$lib/types';

  interface Props {
    /**
     * Called with the chosen files, whether they travel as a batch, what to do
     * with them, which model judges the boundaries structure cannot settle,
     * with what the paper gets read, and what the operator declared it is.
     */
    onfiles: (
      files: File[],
      asBatch: boolean,
      task: TaskKind,
      oracle: OracleChoice,
      lectura: LecturaChoice,
      tipo: TipoPedido
    ) => void;
    disabled?: boolean;
  }

  let { onfiles, disabled = false }: Props = $props();

  /**
   * The ceiling on a single upload. Not a technical limit -- the batch mode has
   * none -- but the line between "I am splitting these five documents" and "I am
   * running a job", which want different screens and different pacing.
   */
  const SINGLE_LIMIT = 5;

  type Mode = 'single' | 'batch' | 'folder';
  let mode = $state<Mode>('single');
  let notice = $state<string | null>(null);

  /**
   * Qué papel se está cargando. Es la primera pregunta porque es la única que
   * el operador puede contestar mirando su caja, y de ella sale todo lo demás:
   * a qué habilidad va el trabajo, por dónde se corta y cómo se nombra.
   */
  let habilidadId = $state<string>('auto');

  /** Y qué se quiere de vuelta, cuando la habilidad deja elegirlo. */
  let resultado = $state<TaskKind>('split');

  /**
   * A qué modelo se le pregunta por las costuras que la estructura no pudo
   * decidir. Sólo interviene al separar una caja revuelta: es la única
   * habilidad que decide bordes por continuidad.
   */
  let oracle = $state<OracleChoice>('auto');

  /**
   * Con qué se transcribe la imagen. Vale para todas las habilidades, porque
   * todas empiezan por leer, y lo que no se lee no lo recupera ningún paso
   * posterior.
   */
  let lectura = $state<LecturaChoice>('local');
  let health = $state<Health | null>(null);

  $effect(() => {
    void fetchHealth().then((value) => {
      health = value;
    });
  });

  const habilidad = $derived(
    HABILIDADES.find((item) => item.id === habilidadId) ?? HABILIDADES[HABILIDADES.length - 1]
  );
  /** La acción que se mandará: la que fija la habilidad, o la que se eligió. */
  const task = $derived<TaskKind>(habilidad.task ?? resultado);
  const tipo = $derived<TipoPedido>(habilidad.tipo);
  const eligeResultado = $derived(habilidad.task === null);

  const oracles = $derived(oracleOptions(health));
  const blocked = $derived(reasonFor(oracle, oracles));
  const lecturas = $derived(lecturaOptions(health));
  const blockedLectura = $derived(reasonForLectura(lectura, lecturas));
  const noDisponible = $derived(motivoNoDisponible(habilidad, health));

  /**
   * Si esta habilidad necesita un motor de lectura que no está elegido.
   *
   * Se dice aquí, antes de soltar los archivos, porque después no se nota: el
   * trabajo corre entero y sale bien cortado, sólo que sin los datos que hacían
   * falta para nombrarlo.
   */
  /** Si está encendida la ayuda de pago, que cambia lo que se puede leer. */
  const conIa = $derived(lectura !== 'local');

  const faltaLectura = $derived(
    habilidad.pideLectura && lectura !== habilidad.pideLectura.id
      ? habilidad.pideLectura
      : null
  );

  /** Lo que esta combinación va a dejar en la carpeta, dicho antes de empezar. */
  const entrega = $derived(
    task === 'inventory' || task === 'inventory_file'
      ? 'Deja el inventario. No escribe ningún PDF.'
      : task === 'both'
        ? 'Deja un PDF por documento y el inventario.'
        : 'Deja un PDF por documento.'
  );

  const MODES: { id: Mode; label: string; hint: string }[] = [
    { id: 'single', label: 'Carga individual', hint: `hasta ${SINGLE_LIMIT} documentos` },
    { id: 'batch', label: 'Carga por lotes', hint: 'sin límite de cantidad' },
    { id: 'folder', label: 'Carpeta local', hint: 'sin subir nada' }
  ];

  function receive(files: File[]) {
    notice = null;
    // Nunca se manda una elección imposible. El servicio la rechazaría igual,
    // pero después de recibir el archivo: una caja escaneada son cientos de
    // megabytes y el operador ya había decidido.
    if (task === 'segment' && blocked) {
      notice = blocked;
      return;
    }
    if (blockedLectura) {
      notice = blockedLectura;
      return;
    }
    if (mode === 'batch') {
      onfiles(files, true, task, oracle, lectura, tipo);
      return;
    }
    if (files.length > SINGLE_LIMIT) {
      // Never silently drop the rest: the operator would believe they were
      // queued. Say what happened and point at the mode that takes them.
      notice = `La carga individual admite ${SINGLE_LIMIT} documentos. Cambie a carga por lotes para subir los ${files.length}.`;
      return;
    }
    onfiles(files, false, task, oracle, lectura, tipo);
  }
</script>

<section class="panel" data-mode={mode} data-task={task} data-habilidad={habilidadId}>
  <fieldset class="paso">
    <legend><i>1</i> Qué vas a procesar</legend>

    <div class="papeles">
      {#each HABILIDADES as option (option.id)}
        {@const motivo = motivoNoDisponible(option, health)}
        <button
          type="button"
          class="papel"
          class:current={habilidadId === option.id}
          aria-pressed={habilidadId === option.id}
          disabled={motivo !== null}
          title={motivo ?? option.papel}
          onclick={() => {
            habilidadId = option.id;
            notice = null;
          }}
        >
          <b>{option.titulo}</b>
          <small>{option.papel}</small>
        </button>
      {/each}
    </div>

    <dl class="ficha">
      <div>
        <dt>Corta</dt>
        <dd>{habilidad.corta}</dd>
      </div>
      <div>
        <dt>Nombra</dt>
        <dd>
          {conIa && habilidad.nombraConIa ? habilidad.nombraConIa : habilidad.nombra}
        </dd>
      </div>
      <div>
        <dt>Entrega</dt>
        <dd>{entrega}</dd>
      </div>
    </dl>

    {#if noDisponible}
      <p class="notice">{noDisponible}</p>
    {/if}

    {#if habilidad.aportaIa}
      <p class="aporta">
        <b>{conIa ? 'Con Mistral OCR:' : 'Si activa Mistral OCR:'}</b>
        {habilidad.aportaIa}
      </p>
    {/if}

    {#if faltaLectura}
      {@const motor = lecturas.find((item) => item.id === faltaLectura.id)}
      <p class="notice">
        {faltaLectura.porque}
        {#if motor?.available}
          <button
            type="button"
            class="enlace"
            onclick={() => {
              lectura = faltaLectura.id;
              notice = null;
            }}
          >
            Usar {motor.label}
          </button>
        {:else}
          <span>Falta la llave del servicio para activarlo.</span>
        {/if}
      </p>
    {/if}
  </fieldset>

  {#if eligeResultado}
    <fieldset class="paso">
      <legend><i>2</i> Qué necesitas de vuelta</legend>
      <div class="opciones" role="radiogroup" aria-label="Qué necesitas de vuelta">
        {#each RESULTADOS as option (option.id)}
          <button
            type="button"
            role="radio"
            aria-checked={resultado === option.id}
            class:current={resultado === option.id}
            onclick={() => {
              resultado = option.id;
              notice = null;
            }}
          >
            <b>{option.label}</b>
            <small>{option.hint}</small>
          </button>
        {/each}
      </div>
    </fieldset>
  {/if}

  <fieldset class="paso">
    <legend><i>{eligeResultado ? 3 : 2}</i> De dónde salen los archivos</legend>
    <div class="opciones" role="tablist" aria-label="Modo de carga">
      {#each MODES as option (option.id)}
        <button
          type="button"
          role="tab"
          aria-selected={mode === option.id}
          class:current={mode === option.id}
          onclick={() => {
            mode = option.id;
            notice = null;
          }}
        >
          <b>{option.label}</b>
          <small>{option.hint}</small>
        </button>
      {/each}
    </div>

    {#if mode === 'folder'}
      <FolderPanel {task} {oracle} {lectura} {tipo} />
    {:else}
      <Dropzone onfiles={receive} {disabled} variant={mode} limit={SINGLE_LIMIT} />
    {/if}
  </fieldset>

  <details class="avanzado">
    <summary>
      Cómo se lee el papel
      <span>{lecturas.find((item) => item.id === lectura)?.label ?? lectura}</span>
    </summary>

    <p class="explains">
      Tesseract lee lo impreso y no lee lo escrito a mano. En un libro de registro antiguo eso
      último es el folio, el nombre, la cédula y la fecha, o sea todo lo que identifica al
      documento; en un expediente mecanografiado no hace falta.
    </p>

    <div class="opciones" role="radiogroup" aria-label="Con qué motor se lee el papel">
      {#each lecturas as option (option.id)}
        <button
          type="button"
          role="radio"
          aria-checked={lectura === option.id}
          class:current={lectura === option.id}
          disabled={!option.available}
          title={option.reason ?? option.hint}
          onclick={() => {
            lectura = option.id;
            notice = null;
          }}
        >
          <b>{option.label}</b>
          <small>{option.available ? option.hint : 'sin llave'}</small>
        </button>
      {/each}
    </div>

    {#if blockedLectura}
      <p class="notice">{blockedLectura}</p>
    {/if}

    {#if task === 'segment'}
      <p class="explains">
        Las costuras que la estructura no puede resolver sola se le preguntan a un modelo. Sólo
        ocurre al separar una caja revuelta: las demás habilidades cortan por algo que está
        impreso o escrito en la hoja.
      </p>

      <div class="opciones" role="radiogroup" aria-label="Qué modelo juzga los bordes dudosos">
        {#each oracles as option (option.id)}
          <button
            type="button"
            role="radio"
            aria-checked={oracle === option.id}
            class:current={oracle === option.id}
            disabled={!option.available}
            title={option.reason ?? option.hint}
            onclick={() => {
              oracle = option.id;
              notice = null;
            }}
          >
            <b>{option.label}</b>
            <small>{option.available ? option.hint : 'sin llave'}</small>
          </button>
        {/each}
      </div>

      {#if blocked}
        <p class="notice">{blocked}</p>
      {/if}
    {/if}
  </details>

  {#if notice}
    <p class="notice">{notice}</p>
  {/if}
</section>

<style>
  .panel {
    display: flex;
    flex-direction: column;
    gap: 1.1rem;
  }

  /* Cada paso es una decisión cerrada, no una fila de botones sueltos. El
     recuadro existe para que se vea dónde termina una pregunta y empieza la
     siguiente: antes eran cinco grupos con la misma pinta y el operador no
     tenía forma de saber cuál contestaba primero. */
  .paso {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    margin: 0;
    border: 1px solid var(--hairline);
    border-radius: 14px;
    background: var(--surface-1);
    padding: 0.85rem 0.9rem 0.9rem;
  }

  .paso legend {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0 0.3rem;
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--ink);
  }

  /* Numerados porque esto sí es una secuencia: no se puede elegir qué se quiere
     de vuelta sin haber dicho antes qué papel es. */
  .paso legend i {
    display: grid;
    place-items: center;
    width: 1.35rem;
    height: 1.35rem;
    border-radius: 50%;
    background: var(--accent-soft);
    color: var(--accent);
    font-family: var(--font-mono);
    font-size: 0.72rem;
    font-style: normal;
  }

  .papeles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(13.5rem, 1fr));
    gap: 6px;
  }

  .papel {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    border: 1px solid var(--hairline);
    border-radius: 10px;
    background: var(--plane);
    padding: 0.6rem 0.7rem;
    font: inherit;
    text-align: left;
    color: var(--ink-2);
    cursor: pointer;
    transition:
      background 0.16s,
      border-color 0.16s,
      color 0.16s;
  }

  .papel:not(:disabled):hover {
    border-color: var(--axis);
    color: var(--ink);
  }

  .papel.current {
    border-color: var(--accent);
    background: var(--surface-2);
    color: var(--ink);
  }

  .papel:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .papel b {
    font-size: 0.85rem;
    font-weight: 600;
  }

  .papel small {
    font-size: 0.72rem;
    line-height: 1.35;
    color: var(--muted);
  }

  /* La ficha de la habilidad elegida: por dónde corta, cómo nombra y qué deja.
     Son las tres preguntas que alguien se hace antes de lanzar media hora de
     proceso, y antes había que conocer el sistema para contestarlas. */
  .ficha {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
    gap: 0.1rem 1.2rem;
    margin: 0;
    border-top: 1px solid var(--rule);
    padding-top: 0.6rem;
  }

  .ficha div {
    display: grid;
    grid-template-columns: 4.2rem 1fr;
    align-items: baseline;
    gap: 0.5rem;
    padding: 0.18rem 0;
  }

  .ficha dt {
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--muted);
  }

  .ficha dd {
    margin: 0;
    font-size: 0.78rem;
    line-height: 1.4;
    color: var(--ink-2);
  }

  /* Qué gana esta habilidad al encender la ayuda de pago, dicho junto a la
     habilidad y no en la sección de lectura: lo que aporta depende del papel
     que se esté procesando, y en un expediente mecanografiado no aporta nada. */
  .aporta {
    margin: 0;
    border-left: 2px solid color-mix(in oklab, var(--s3) 50%, var(--hairline));
    padding-left: 0.65rem;
    font-size: 0.78rem;
    line-height: 1.5;
    color: var(--ink-2);
  }

  .aporta b {
    font-weight: 600;
    color: var(--ink);
  }

  .opciones {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
    gap: 4px;
    border: 1px solid var(--hairline);
    border-radius: 12px;
    background: var(--plane);
    padding: 4px;
  }

  .opciones button {
    display: flex;
    flex-direction: column;
    gap: 1px;
    border: 1px solid transparent;
    border-radius: 9px;
    background: transparent;
    padding: 0.5rem 0.85rem;
    font: inherit;
    text-align: left;
    color: var(--muted);
    cursor: pointer;
    transition:
      background 0.16s,
      color 0.16s,
      border-color 0.16s;
  }

  .opciones button:not(:disabled):hover {
    color: var(--ink-2);
  }

  .opciones button.current {
    border-color: var(--hairline);
    background: var(--surface-2);
    box-shadow: var(--shadow);
    color: var(--ink);
  }

  .opciones button:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .opciones b {
    font-size: 0.8rem;
    font-weight: 600;
  }

  .opciones small {
    font-family: var(--font-mono);
    font-size: 0.68rem;
    color: var(--muted);
  }

  /* Lo que casi nunca se toca va plegado, pero el resumen dice qué hay elegido
     dentro: plegar una opción no puede ser esconderla. */
  .avanzado {
    border: 1px solid var(--hairline);
    border-radius: 12px;
    background: var(--surface-1);
    padding: 0.2rem 0.9rem;
  }

  .avanzado summary {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.6rem;
    padding: 0.55rem 0;
    font-size: 0.82rem;
    font-weight: 600;
    color: var(--ink-2);
    cursor: pointer;
  }

  .avanzado summary span {
    font-family: var(--font-mono);
    font-size: 0.7rem;
    font-weight: 400;
    color: var(--muted);
  }

  .avanzado[open] summary {
    border-bottom: 1px solid var(--rule);
    margin-bottom: 0.6rem;
  }

  .avanzado > :global(*:last-child) {
    margin-bottom: 0.7rem;
  }

  /* La caja de correspondencia es la única que decide bordes sin leer un número
     impreso, y se marca aparte para que se vea de reojo que esta carga no se
     parece a las otras. */
  [data-task='segment'] .papel.current {
    border-color: color-mix(in oklab, var(--s4) 55%, var(--hairline));
  }
  [data-task='inventory'] .papel.current,
  [data-task='inventory_file'] .papel.current {
    border-color: color-mix(in oklab, var(--s2) 55%, var(--hairline));
  }

  /* Un párrafo que explica y otro que advierte. Se distinguen por el filo de la
     izquierda y no por el tamaño: los dos se leen igual de bien, pero sólo uno
     pide que se haga algo. */
  .explains {
    margin: 0;
    border-left: 2px solid color-mix(in oklab, var(--s2) 45%, var(--hairline));
    padding-left: 0.65rem;
    font-size: 0.82rem;
    line-height: 1.5;
    color: var(--ink-2);
  }

  .notice {
    margin: 0;
    border-left: 2px solid var(--warning);
    padding-left: 0.65rem;
    font-size: 0.82rem;
    line-height: 1.5;
    color: var(--ink-2);
  }

  /* Un aviso que se puede resolver desde el propio aviso. Decir qué falta y
     obligar a buscarlo en otro sitio de la pantalla es media ayuda. */
  .enlace {
    border: 0;
    background: none;
    padding: 0;
    font: inherit;
    font-weight: 600;
    color: var(--accent);
    text-decoration: underline;
    text-underline-offset: 2px;
    cursor: pointer;
  }

  /* En una pantalla estrecha los pasos pierden el recuadro y se separan por una
     línea: el marco costaba dos gutters de ancho y no aportaba nada que no
     dijera ya el número del paso. */
  @media (max-width: 34rem) {
    .paso {
      border-width: 0 0 1px;
      border-radius: 0;
      padding-inline: 0;
    }
  }
</style>
