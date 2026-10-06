<script lang="ts">
  import { fly } from 'svelte/transition';

  import { fetchHealth, type Health } from '$lib/api';
  import UploadSummary from '$lib/components/UploadSummary.svelte';
  import Callout from '$lib/components/wizard/Callout.svelte';
  import PasoAgrupar from '$lib/components/wizard/PasoAgrupar.svelte';
  import PasoCorte from '$lib/components/wizard/PasoCorte.svelte';
  import PasoLectura from '$lib/components/wizard/PasoLectura.svelte';
  import PasoOracle from '$lib/components/wizard/PasoOracle.svelte';
  import PasoOrigen from '$lib/components/wizard/PasoOrigen.svelte';
  import PasoResultado from '$lib/components/wizard/PasoResultado.svelte';
  import PasoTipoDocumento from '$lib/components/wizard/PasoTipoDocumento.svelte';
  import {
    HABILIDADES,
    RESULTADOS,
    motivoNoDisponible,
    motivoSinAgrupar,
    type AgruparChoice,
    type CorteChoice
  } from '$lib/habilidades';
  import { lecturaOptions, reasonForLectura, type LecturaChoice } from '$lib/lectura';
  import { oracleOptions, reasonFor, type OracleChoice } from '$lib/oracles';
  import type { TipoPedido } from '$lib/tipos';
  import type { TaskKind } from '$lib/types';

  interface Props {
    onfiles: (
      files: File[],
      asBatch: boolean,
      task: TaskKind,
      oracle: OracleChoice,
      lectura: LecturaChoice,
      tipo: TipoPedido,
      corte: CorteChoice,
      agrupar: AgruparChoice
    ) => void;
    disabled?: boolean;
  }

  let { onfiles, disabled = false }: Props = $props();

  const SINGLE_LIMIT = 5;

  type Mode = 'single' | 'batch' | 'folder';

  let mode = $state<Mode>('single');
  let paso = $state(1);
  let notice = $state<string | null>(null);

  let habilidadId = $state<string>('auto');
  let resultado = $state<TaskKind>('split');
  let oracle = $state<OracleChoice>('auto');
  let lectura = $state<LecturaChoice>('local');
  let corte = $state<CorteChoice>('pagina');
  let agrupar = $state<AgruparChoice>('documento');
  let health = $state<Health | null>(null);
  /** Files dropped and waiting for "Confirmar y subir". */
  let pendientes = $state<File[]>([]);

  $effect(() => {
    const preguntar = () =>
      void fetchHealth().then((value) => {
        health = value;
      });
    preguntar();
    const reloj = setInterval(preguntar, 15_000);
    return () => clearInterval(reloj);
  });

  const habilidad = $derived(
    HABILIDADES.find((item) => item.id === habilidadId) ?? HABILIDADES[HABILIDADES.length - 1]
  );

  const cortes = $derived(habilidad.cortes?.opciones ?? []);
  const corteElegido = $derived<CorteChoice>(
    cortes.some((opcion) => opcion.id === corte) ? corte : (cortes[0]?.id ?? 'pagina')
  );

  const agrupaciones = $derived(habilidad.agrupar?.opciones ?? []);
  const agruparElegido = $derived<AgruparChoice>(
    agrupaciones.some((opcion) => opcion.id === agrupar && !motivoSinAgrupar(opcion, health))
      ? agrupar
      : 'documento'
  );
  const opcionDeAgrupar = $derived(agrupaciones.find((opcion) => opcion.id === agruparElegido));

  /** Lo que se puede pedir de vuelta con esta habilidad. */
  const acciones = $derived(habilidad.acciones ?? RESULTADOS);
  /* La acción elegida si esta habilidad la admite; si no, su primera. Al cambiar
     de habilidad el «split» de la anterior no vale para un libro de actas, que
     se inventaría o se divide. */
  const task = $derived<TaskKind>(
    habilidad.task ??
      (acciones.some((accion) => accion.id === resultado) ? resultado : acciones[0].id)
  );
  const tipo = $derived<TipoPedido>(habilidad.tipo);
  const eligeResultado = $derived(habilidad.task === null);

  const oracles = $derived(oracleOptions(health));
  const blocked = $derived(reasonFor(oracle, oracles));
  const lecturas = $derived(lecturaOptions(health));
  const blockedLectura = $derived(reasonForLectura(lectura, lecturas));
  const noDisponible = $derived(motivoNoDisponible(habilidad, health));
  const conIa = $derived(lectura !== 'local');

  const faltaLectura = $derived(
    habilidad.pideLectura && lectura !== habilidad.pideLectura.id ? habilidad.pideLectura : null
  );

  const entrega = $derived(
    opcionDeAgrupar?.entrega ??
      (task === 'inventory' || task === 'inventory_file'
        ? 'Deja el inventario. No escribe ningún PDF.'
        : task === 'both' && habilidad.tipo === 'acta-consejo'
          ? 'Deja un PDF por sesión y el inventario.'
          : task === 'both'
            ? 'Deja un PDF por documento y el inventario.'
          : 'Deja un PDF por documento.')
  );

  /**
   * The steps of this path, in order, derived from the chosen skill.
   *
   * One list drives the progress bar, the step numbers and which step is on
   * screen. The previous arithmetic computed each of those separately and they
   * drifted apart: the correspondence box jumped from step 1 straight to the
   * origin and never showed its grouping or model steps.
   */
  type StepId = 'tipo' | 'lectura' | 'resultado' | 'corte' | 'agrupar' | 'oracle' | 'origen';

  const STEP_LABELS: Record<StepId, string> = {
    tipo: 'Tipo',
    lectura: 'Lectura',
    resultado: 'Resultado',
    corte: 'Corte',
    agrupar: 'Agrupar',
    oracle: 'Modelo IA',
    origen: 'Origen'
  };

  const pasos = $derived<StepId[]>([
    'tipo',
    ...(habilidad.pideLectura ? (['lectura'] as const) : []),
    ...(eligeResultado ? (['resultado'] as const) : []),
    ...(habilidad.cortes ? (['corte'] as const) : []),
    ...(habilidad.agrupar ? (['agrupar'] as const) : []),
    ...(task === 'segment' ? (['oracle'] as const) : []),
    'origen'
  ]);

  const totalPasos = $derived(pasos.length);
  const pasoActual = $derived(Math.min(paso, totalPasos));
  const pasoId = $derived<StepId>(pasos[pasoActual - 1] ?? 'tipo');
  const esUltimo = $derived(pasoActual === totalPasos);

  /** Why "Siguiente" cannot move on from this step, if it cannot. */
  const bloqueoDelPaso = $derived(
    pasoId === 'tipo'
      ? noDisponible
      : pasoId === 'lectura'
        ? blockedLectura
        : pasoId === 'oracle'
          ? blocked
          : null
  );

  const reduceMotion =
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

  function siguiente() {
    if (paso < totalPasos) paso++;
  }

  function anterior() {
    if (paso > 1) paso--;
  }

  function irAPaso(n: number) {
    if (n >= 1 && n <= totalPasos) paso = n;
  }

  /** The final submission, with the checks that guard it. */
  function recibirArchivos(files: File[]) {
    notice = null;
    if (task === 'segment' && blocked) {
      notice = blocked;
      return;
    }
    if (blockedLectura) {
      notice = blockedLectura;
      return;
    }
    if (mode === 'batch') {
      onfiles(files, true, task, oracle, lectura, tipo, corteElegido, agruparElegido);
      return;
    }
    if (files.length > SINGLE_LIMIT) {
      notice = `La carga individual admite ${SINGLE_LIMIT} documentos. Cambie a carga por lote para subir los ${files.length}.`;
      return;
    }
    onfiles(files, false, task, oracle, lectura, tipo, corteElegido, agruparElegido);
  }

  /**
   * Dropped files wait for review instead of leaving at once: the summary
   * shows what they are and how they will be processed, and "Confirmar y
   * subir" sends them. The same checks run here so a block is said before the
   * review, not after the click.
   */
  function prepararArchivos(files: File[]) {
    notice = null;
    if (task === 'segment' && blocked) {
      notice = blocked;
      return;
    }
    if (blockedLectura) {
      notice = blockedLectura;
      return;
    }
    if (mode !== 'batch' && files.length > SINGLE_LIMIT) {
      notice = `La carga individual admite ${SINGLE_LIMIT} documentos. Cambie a carga por lote para subir los ${files.length}.`;
      return;
    }
    pendientes = files;
  }

  function elegirHabilidad(id: string) {
    habilidadId = id;
    const pide = habilidad.pideLectura?.id;
    if (pide && lectura === 'local') {
      const ia = lecturas.find((item) => item.id === pide && item.available);
      if (ia) lectura = ia.id;
    }
    // Choices that belong to the previous skill do not travel to this one.
    corte = cortes[0]?.id ?? 'pagina';
    agrupar = agrupaciones[0]?.id ?? 'documento';
    oracle = 'auto';
    resultado = 'split';
    notice = null;
    pendientes = [];
    paso = 1;
  }

  function elegirResultado_(r: TaskKind) {
    resultado = r;
    notice = null;
    siguiente();
  }

  function elegirCorte(c: CorteChoice) {
    corte = c;
    notice = null;
    siguiente();
  }

  function elegirAgrupar(a: AgruparChoice) {
    agrupar = a;
    notice = null;
    siguiente();
  }

  function elegirOracle(o: OracleChoice) {
    oracle = o;
    notice = null;
    siguiente();
  }

  function elegirLectura(l: LecturaChoice) {
    lectura = l;
    notice = null;
    siguiente();
  }

  function elegirModo(m: Mode) {
    mode = m;
    notice = null;
    pendientes = [];
  }

  function confirmarSubida(files: File[] = pendientes) {
    recibirArchivos(files);
    if (!notice) pendientes = [];
  }

  function volverAlInicio() {
    paso = 1;
  }
</script>

<section
  class="wizard"
  data-paso={pasoActual}
  data-total={totalPasos}
  data-habilidad={habilidadId}
>
  <nav class="progress" aria-label="Pasos del asistente">
    <ol>
      {#each pasos as id, indice (id)}
        {@const numero = indice + 1}
        <li class:done={numero < pasoActual} class:current={numero === pasoActual}>
          <button
            type="button"
            onclick={() => irAPaso(numero)}
            disabled={numero > pasoActual}
            aria-current={numero === pasoActual ? 'step' : undefined}
          >
            <span class="dot">
              {#if numero < pasoActual}
                <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 8.5 3 3 6-7" /></svg>
              {:else}
                {numero}
              {/if}
            </span>
            <span class="label">{STEP_LABELS[id]}</span>
          </button>
        </li>
      {/each}
    </ol>
  </nav>

  <div class="card">
    {#key pasoId}
      <div class="stage" in:fly={{ y: 6, duration: reduceMotion ? 0 : 180 }}>
        {#if pasoId === 'tipo'}
          <PasoTipoDocumento
            {habilidadId}
            onElegir={elegirHabilidad}
            {disabled}
            {health}
            numero={pasoActual}
          />
        {:else if pasoId === 'lectura'}
          <PasoLectura
            {lectura}
            onElegir={elegirLectura}
            {lecturas}
            {faltaLectura}
            {conIa}
            {blockedLectura}
            numero={pasoActual}
          />
        {:else if pasoId === 'resultado'}
          <PasoResultado
            resultado={task}
            opciones={acciones}
            onElegir={elegirResultado_}
            {disabled}
            numero={pasoActual}
          />
        {:else if pasoId === 'corte'}
          <PasoCorte
            {cortes}
            {corte}
            onElegir={elegirCorte}
            {corteElegido}
            pregunta={habilidad.cortes?.pregunta}
            numero={pasoActual}
          />
        {:else if pasoId === 'agrupar'}
          <PasoAgrupar
            {agrupar}
            onElegir={elegirAgrupar}
            {agruparElegido}
            {agrupaciones}
            {health}
            pregunta={habilidad.agrupar?.pregunta}
            numero={pasoActual}
          />
        {:else if pasoId === 'oracle'}
          <PasoOracle {oracle} onElegir={elegirOracle} {oracles} {blocked} numero={pasoActual} />
        {:else}
          <div class="final">
            <PasoOrigen
              {mode}
              onCambiar={elegirModo}
              {task}
              {oracle}
              {lectura}
              {tipo}
              corte={corteElegido}
              agrupar={agruparElegido}
              {disabled}
              onfiles={prepararArchivos}
              {blocked}
              {blockedLectura}
              numero={pasoActual}
            />
            <aside>
              <UploadSummary
                files={pendientes}
                {mode}
                {habilidad}
                {lectura}
                {task}
                {tipo}
                corte={corteElegido}
                agrupar={agruparElegido}
                {oracle}
                {entrega}
                busy={disabled}
                onback={volverAlInicio}
                onconfirm={() => confirmarSubida()}
                onclear={() => (pendientes = [])}
              />
            </aside>
          </div>
        {/if}
      </div>
    {/key}

    {#if notice}
      <Callout tone="warning">{notice}</Callout>
    {/if}

    <footer class="nav">
      <button type="button" class="secondary" onclick={anterior} disabled={pasoActual === 1}>
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3.5 5.5 8l4.5 4.5" /></svg>
        Anterior
      </button>

      <span class="counter">Paso {pasoActual} de {totalPasos}</span>

      {#if !esUltimo}
        <button
          type="button"
          class="primary"
          onclick={siguiente}
          disabled={disabled || !!bloqueoDelPaso}
          title={bloqueoDelPaso ?? undefined}
        >
          Siguiente
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5 10.5 8 6 12.5" /></svg>
        </button>
      {:else}
        <span class="spacer" aria-hidden="true"></span>
      {/if}
    </footer>
  </div>
</section>

<style>
  /* Spacing, radius and type scale for every step: an 8px grid with a 4px
     half-step, so no component carries magic numbers of its own. Child
     components read these through inheritance. */
  .wizard {
    --wz-space-1: 4px;
    --wz-space-2: 8px;
    --wz-space-3: 12px;
    --wz-space-4: 16px;
    --wz-space-5: 20px;
    --wz-space-6: 24px;
    --wz-space-8: 32px;
    --wz-radius: 8px;
    --wz-radius-lg: 12px;
    --wz-text-xs: 0.75rem;
    --wz-text-sm: 0.8125rem;
    --wz-text-base: 0.9375rem;
    --wz-text-lg: 1.125rem;

    display: flex;
    flex-direction: column;
    gap: var(--wz-space-4);
    width: 100%;
    max-width: 68rem;
    margin: 0 auto;
    font-family: Inter, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
    color: var(--ink);
  }

  /* -- progress ------------------------------------------------------------ */

  .progress ol {
    display: flex;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .progress li {
    position: relative;
    display: flex;
    flex: 1;
    justify-content: center;
  }

  /* The connector to the previous step, drawn behind the dot. */
  .progress li + li::before {
    content: '';
    position: absolute;
    top: 14px;
    right: 50%;
    left: -50%;
    height: 2px;
    border-radius: 1px;
    background: var(--grid);
  }

  .progress li.done + li::before,
  .progress li.done + li.current::before {
    background: var(--accent);
  }

  .progress button {
    position: relative;
    z-index: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--wz-space-2);
    border: 0;
    background: none;
    padding: 0 var(--wz-space-1);
    font: inherit;
    cursor: pointer;
  }

  .progress button:disabled {
    cursor: default;
  }

  .progress button:focus-visible {
    outline: none;
  }

  .progress button:focus-visible .dot {
    box-shadow: 0 0 0 3px var(--ring);
  }

  .dot {
    display: grid;
    width: 30px;
    height: 30px;
    place-items: center;
    border: 1.5px solid var(--axis);
    border-radius: 50%;
    background: var(--surface-2);
    font-size: var(--wz-text-sm);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    color: var(--muted);
    transition:
      background-color 0.2s ease,
      border-color 0.2s ease,
      color 0.2s ease;
  }

  .dot svg {
    width: 14px;
    height: 14px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  .done .dot {
    border-color: var(--accent);
    background: var(--accent);
    color: #fff;
  }

  .current .dot {
    border-color: var(--accent);
    color: var(--accent);
    box-shadow: 0 0 0 4px var(--accent-soft);
  }

  .label {
    font-size: var(--wz-text-xs);
    font-weight: 500;
    white-space: nowrap;
    color: var(--muted);
  }

  .done .label {
    color: var(--ink-2);
  }

  .current .label {
    font-weight: 600;
    color: var(--ink);
  }

  .done button:hover .label {
    color: var(--accent);
  }

  /* -- content ------------------------------------------------------------- */

  .wizard {
    container: wizard / inline-size;
  }

  .card {
    display: flex;
    flex-direction: column;
    gap: var(--wz-space-5);
    border: 1px solid var(--hairline);
    border-radius: var(--wz-radius-lg);
    background: var(--surface-2);
    padding: var(--wz-space-6) var(--wz-space-6) 0;
    box-shadow: var(--shadow);
  }

  .stage {
    min-height: 18rem;
  }

  /* An explicit track: the implicit `auto` one grows to the summary's
     min-content and pushes the cards past the frame on a phone. */
  .final {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    align-items: start;
    gap: var(--wz-space-6);
  }

  .final > :global(*) {
    min-width: 0;
  }

  @container wizard (min-width: 56rem) {
    .final {
      grid-template-columns: minmax(0, 1fr) 21rem;
    }

    .final aside {
      position: sticky;
      top: var(--wz-space-4);
    }
  }

  /* -- navigation ---------------------------------------------------------- */

  /* Pegada al pie de la pantalla mientras el paso sea más alto que ella:
     elegir una opción de abajo y tener que bajar otra vez a buscar
     «Siguiente» era la mitad del recorrido del ratón. */
  .nav {
    position: sticky;
    bottom: 0;
    z-index: 3;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--wz-space-3);
    margin-inline: calc(var(--wz-space-6) * -1);
    border-top: 1px solid var(--rule);
    border-radius: 0 0 var(--wz-radius-lg) var(--wz-radius-lg);
    background: var(--surface-2);
    padding: var(--wz-space-3) var(--wz-space-6);
  }

  .counter {
    font-size: var(--wz-text-xs);
    font-variant-numeric: tabular-nums;
    color: var(--muted);
  }

  .spacer {
    width: 7.5rem;
  }

  .nav button {
    display: inline-flex;
    min-width: 7.5rem;
    align-items: center;
    justify-content: center;
    gap: var(--wz-space-2);
    border-radius: var(--wz-radius);
    padding: var(--wz-space-2) var(--wz-space-4);
    font: inherit;
    font-size: var(--wz-text-sm);
    font-weight: 600;
    cursor: pointer;
    transition:
      background-color 0.15s ease,
      border-color 0.15s ease,
      color 0.15s ease;
  }

  .nav button svg {
    width: 14px;
    height: 14px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.8;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  .nav button:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 2px;
  }

  .secondary {
    border: 1px solid var(--hairline);
    background: var(--surface-2);
    color: var(--ink-2);
  }

  .secondary:hover:not(:disabled) {
    border-color: var(--axis);
    color: var(--ink);
  }

  .primary {
    border: 1px solid var(--accent);
    background: var(--accent);
    color: #fff;
  }

  .primary:hover:not(:disabled) {
    background: color-mix(in oklab, var(--accent) 88%, #000);
  }

  /* Disabled says so with more than a lighter shade: no fill, dashed edge,
     and the reason as a tooltip on "Siguiente". */
  .nav button:disabled {
    border-style: dashed;
    border-color: var(--axis);
    background: transparent;
    color: var(--muted);
    cursor: not-allowed;
  }

  /* -- small screens ------------------------------------------------------- */

  @container wizard (max-width: 36rem) {
    .card {
      padding: var(--wz-space-4) var(--wz-space-4) 0;
    }

    .nav {
      margin-inline: calc(var(--wz-space-4) * -1);
      padding-inline: var(--wz-space-4);
    }

    /* Only the current step keeps its name; the others stay as dots. */
    .progress li:not(.current) .label {
      display: none;
    }

    .counter {
      display: none;
    }

    .nav button {
      min-width: 0;
      flex: 1;
    }

    .spacer {
      display: none;
    }
  }
</style>
