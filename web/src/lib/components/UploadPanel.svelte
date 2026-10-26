<script lang="ts">
  import { fly } from 'svelte/transition';

  import { fetchHealth, reconocerArchivo, type Health, type Sugerencia } from '$lib/api';
  import Icono from '$lib/components/Icono.svelte';
  import UploadSummary from '$lib/components/UploadSummary.svelte';
  import Callout from '$lib/components/wizard/Callout.svelte';
  import PasoAgrupar from '$lib/components/wizard/PasoAgrupar.svelte';
  import PasoCorte from '$lib/components/wizard/PasoCorte.svelte';
  import PasoLectura from '$lib/components/wizard/PasoLectura.svelte';
  import PasoOracle from '$lib/components/wizard/PasoOracle.svelte';
  import PasoOrigen from '$lib/components/wizard/PasoOrigen.svelte';
  import PasoResultado from '$lib/components/wizard/PasoResultado.svelte';
  import PasoTipoDocumento from '$lib/components/wizard/PasoTipoDocumento.svelte';
  import SugerenciaDeTipo from '$lib/components/wizard/SugerenciaDeTipo.svelte';
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
      agrupar: AgruparChoice,
      territorial: string,
      paralelo: number,
      tipoDocumento?: string
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
  /** La territorial de la caja (municipio), para el encabezado del Índice Electrónico. */
  let territorial = $state('');
  /** Cuántos archivos a la vez. Cero es el automático del servicio. */
  let paralelo = $state(0);
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

  /**
   * Qué plantilla de inventario usa esta habilidad.
   * - correspondencia (Afinia) → 'indice_electronico'
   * - kingspan → 'kingspan'
   * - demás → undefined (el servicio usa su default)
   */
  const tipoDocumento = $derived(
    habilidad.id === 'correspondencia' ? 'indice_electronico' :
    habilidad.id === 'kingspan' ? 'kingspan' :
    undefined
  );

  const cortes = $derived(habilidad.cortes?.opciones ?? []);
  const corteElegido = $derived<CorteChoice>(
    cortes.some((opcion) => opcion.id === corte) ? corte : (cortes[0]?.id ?? 'pagina')
  );

  /**
   * Las agrupaciones que esta habilidad ofrece.
   * Cada habilidad declara las suyas; no hay filtrado por tipo de documento.
   */
  const agrupaciones = $derived(habilidad.agrupar?.opciones ?? []);
  const agrupacionesElegibles = $derived(agrupaciones.filter((opcion) => !opcion.proximamente));
  const agruparElegido = $derived<AgruparChoice>(
    agrupacionesElegibles.some(
      (opcion) => opcion.id === agrupar && !motivoSinAgrupar(opcion, health)
    )
      ? agrupar
      : (agrupacionesElegibles[0]?.id ?? 'documento')
  );
  const opcionDeAgrupar = $derived(agrupaciones.find((opcion) => opcion.id === agruparElegido));

  /**
   * Lo que se puede pedir de vuelta con esta habilidad.
   * - Si la habilidad tiene `task` fijo (ej. 'segment' en correspondencia), no se elige.
   * - Si `task: null` y tiene `acciones` propias, se usan esas.
   * - Si `task: null` sin `acciones`, se usan `RESULTADOS` globales.
   */
  const acciones = $derived(
    habilidad.task ? [] : (habilidad.acciones ?? RESULTADOS)
  );
  const task = $derived<TaskKind>(
    habilidad.task ??
      (acciones.some((accion) => accion.id === resultado) ? resultado : (acciones[0]?.id ?? 'split'))
  );
  const tipo = $derived<TipoPedido>(habilidad.tipo);
  const eligeResultado = $derived(habilidad.task === null && acciones.length > 0);
  const eligeAgrupar = $derived(habilidad.agrupar !== undefined && agrupaciones.length > 0);

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
          : task === 'both' && habilidad.tipo === 'acta'
            ? 'Deja un PDF por graduado y el FUID.'
            : task === 'both'
              ? 'Deja un PDF por documento y el inventario.'
              : 'Deja un PDF por documento.')
  );

  /**
   * The steps of this path, in order, derived from the chosen skill.
   *
   * One list drives the progress bar, the step numbers and which step is on
   * screen.
   */
  type StepId =
    | 'tipo'
    | 'lectura'
    | 'resultado'
    | 'corte'
    | 'agrupar'
    | 'oracle'
    | 'origen';

  const STEP_LABELS: Record<StepId, string> = {
    tipo: 'Tipo',
    lectura: 'Lectura',
    resultado: 'Resultado',
    corte: 'Corte',
    agrupar: 'Agrupar',
    oracle: 'Modelo IA',
    origen: 'Origen'
  };

  /**
   * El paso de agrupar solo aparece si la habilidad lo declara y tiene opciones.
   */
  const pasos = $derived<StepId[]>([
    'tipo',
    // Todas las habilidades preguntan cómo se lee el papel, también «No estoy
    // seguro»: antes sólo lo preguntaban las que recomiendan IA, y las demás
    // corrían con «Solo OCR» sin que nadie lo eligiera -- una carpeta de actas
    // de grado entera salió sin folios por eso.
    'lectura',
    ...(eligeResultado ? (['resultado'] as const) : []),
    ...(habilidad.cortes ? (['corte'] as const) : []),
    ...(eligeAgrupar ? (['agrupar'] as const) : []),
    // El modelo de las costuras dudosas es una IA de pago: sólo se pregunta
    // con «OCR + IA». Con «Solo OCR» no se consulta ningún modelo y lo dudoso
    // va a revisión.
    ...(task === 'segment' && lectura !== 'local' ? (['oracle'] as const) : []),
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
      onfiles(files, true, task, oracle, lectura, tipo, corteElegido, agruparElegido, territorial, paralelo, tipoDocumento);
      return;
    }
    if (files.length > SINGLE_LIMIT) {
      notice = `La carga individual admite ${SINGLE_LIMIT} documentos. Cambie a carga por lote para subir los ${files.length}.`;
      return;
    }
    onfiles(files, false, task, oracle, lectura, tipo, corteElegido, agruparElegido, territorial, paralelo, tipoDocumento);
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
    void reconocerPendientes(files);
  }

  /* -- qué parecen los archivos ---------------------------------------------
     Al soltarlos, el bot mira su capa de texto y su nombre -- no gasta nada --
     y dice qué parecen. Sólo los primeros: con cinco se sabe de qué va un lote
     sin que la pantalla espere a cien. */
  const A_RECONOCER = 5;
  let sugerencias = $state<(Sugerencia & { nombre: string })[]>([]);
  let reconociendo = $state(false);
  let errorDeReconocer = $state<string | null>(null);
  let pedidoDeReconocer: AbortController | null = null;

  async function reconocerPendientes(files: File[]) {
    pedidoDeReconocer?.abort();
    sugerencias = [];
    errorDeReconocer = null;
    if (!files.length || !health?.features?.includes('reconocer')) return;
    const pedido = new AbortController();
    pedidoDeReconocer = pedido;
    reconociendo = true;
    try {
      const vistas: (Sugerencia & { nombre: string })[] = [];
      for (const file of files.slice(0, A_RECONOCER)) {
        vistas.push({ ...(await reconocerArchivo(file, pedido.signal)), nombre: file.name });
        if (pedido.signal.aborted) return;
        sugerencias = [...vistas];
      }
    } catch (problema) {
      if (!pedido.signal.aborted) errorDeReconocer = (problema as Error).message;
    } finally {
      if (pedidoDeReconocer === pedido) reconociendo = false;
    }
  }

  /** Cambiar a la habilidad sugerida sin perder los archivos ya elegidos. */
  function usarSugerencia(id: string) {
    const guardados = pendientes;
    const vistas = sugerencias;
    elegirHabilidad(id);
    pendientes = guardados;
    sugerencias = vistas;
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
    agrupar = (habilidad.agrupar?.opciones ?? []).find((o) => !o.proximamente)?.id ?? 'documento';
    territorial = '';
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
    // «Solo OCR» es sólo OCR: el modelo elegido antes no viaja.
    if (l === 'local') oracle = 'auto';
    notice = null;
    siguiente();
  }

  function elegirModo(m: Mode) {
    mode = m;
    notice = null;
    pendientes = [];
    sugerencias = [];
    pedidoDeReconocer?.abort();
  }

  function confirmarSubida(files: File[] = pendientes) {
    recibirArchivos(files);
    if (!notice) pendientes = [];
  }

  function elegirTerritorial(valor: string) {
    territorial = valor;
    notice = null;
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
  <nav class="pasos" aria-label="Pasos del asistente">
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
            <span class="circulo">
              {#if numero < pasoActual}
                <Icono nombre="hecho" />
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

  <div class="panel cuerpo">
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
              {tipoDocumento}
              {disabled}
              onfiles={prepararArchivos}
              {blocked}
              {blockedLectura}
              numero={pasoActual}
              {habilidadId}
              onusarHabilidad={usarSugerencia}
              {paralelo}
              onParalelo={(valor) => (paralelo = valor)}
              maximoEnParalelo={health?.document_workers ?? 0}
              automaticoEnParalelo={health?.folder_documents ?? 0}
            />
            {#if mode !== 'folder' && (reconociendo || sugerencias.length || errorDeReconocer)}
              <div class="sugerencia">
                <SugerenciaDeTipo
                  {habilidadId}
                  archivos={sugerencias}
                  cargando={reconociendo && !sugerencias.length}
                  error={errorDeReconocer}
                  onusar={usarSugerencia}
                />
              </div>
            {/if}
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
                onclear={() => {
                  pendientes = [];
                  sugerencias = [];
                }}
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
      <button type="button" class="btn" onclick={anterior} disabled={pasoActual === 1}>
        <Icono nombre="atras" />
        Anterior
      </button>

      <span class="counter">Paso {pasoActual} de {totalPasos}</span>

      {#if !esUltimo}
        <button
          type="button"
          class="btn btn-primary"
          onclick={siguiente}
          disabled={disabled || !!bloqueoDelPaso}
          title={bloqueoDelPaso ?? undefined}
        >
          Siguiente
          <Icono nombre="chevron" />
        </button>
      {:else}
        <span class="spacer" aria-hidden="true"></span>
      {/if}
    </footer>
  </div>
</section>

<style>
  /* El asistente usa la escala común de app.css (--space-*, --radius-*,
     --text-*): antes traía la suya, casi igual pero no del todo, y cada paso
     se veía un punto distinto del resto de la aplicación. */
  .wizard {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    width: 100%;
    max-width: 68rem;
    margin: 0 auto;
    font-family: inherit;
    color: var(--ink);
  }

  /* -- pasos --------------------------------------------------------------- */

  .pasos ol {
    display: flex;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .pasos li {
    position: relative;
    display: flex;
    flex: 1;
    justify-content: center;
  }

  /* The connector to the previous step, drawn behind the circle. */
  .pasos li + li::before {
    content: '';
    position: absolute;
    top: 14px;
    right: 50%;
    left: -50%;
    height: 2px;
    border-radius: 1px;
    background: var(--grid);
  }

  .pasos li.done + li::before,
  .pasos li.done + li.current::before {
    background: var(--accent);
  }

  .pasos button {
    position: relative;
    z-index: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-2);
    border: 0;
    background: none;
    padding: 0 var(--space-1);
    font: inherit;
    cursor: pointer;
  }

  .pasos button:disabled {
    cursor: default;
  }

  /* El foco va en el círculo, que es lo que se ve del botón. */
  .pasos button:focus-visible {
    outline: none;
  }

  .pasos button:focus-visible .circulo {
    outline: 2px solid var(--ring);
    outline-offset: 2px;
  }

  /* El círculo numerado de cada paso. No es un punto de estado: es el número
     del paso, y con él se vuelve a uno anterior. */
  .circulo {
    --icono: 14px;
    display: grid;
    width: 30px;
    height: 30px;
    place-items: center;
    border: 1.5px solid var(--control);
    border-radius: 50%;
    background: var(--surface-2);
    font-size: var(--text-sm);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    color: var(--muted);
    transition:
      background-color var(--duration) var(--ease-out),
      border-color var(--duration) var(--ease-out),
      color var(--duration) var(--ease-out);
  }

  .done .circulo {
    border-color: var(--accent);
    background: var(--accent);
    color: var(--on-accent);
  }

  .current .circulo {
    border-color: var(--accent);
    color: var(--accent);
    box-shadow: 0 0 0 4px var(--accent-soft);
  }

  .label {
    font-size: var(--text-xs);
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

  /* La tarjeta del paso es el `.panel` común; aquí sólo su maquetación y un
     relleno más holgado, que el pie pegajoso de abajo descuenta. */
  .cuerpo {
    display: flex;
    flex-direction: column;
    gap: var(--space-5);
    padding: var(--space-6) var(--space-6) 0;
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
    gap: var(--space-6);
  }

  .final > :global(*) {
    min-width: 0;
  }

  /* Lo que el bot reconoce, de lado a lado: es lo primero que hay que leer
     antes de confirmar la subida. */
  .sugerencia {
    grid-column: 1 / -1;
  }

  @container wizard (min-width: 56rem) {
    .final {
      grid-template-columns: minmax(0, 1fr) 21rem;
    }

    .final aside {
      position: sticky;
      top: var(--space-4);
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
    gap: var(--space-3);
    margin-inline: calc(var(--space-6) * -1);
    border-top: 1px solid var(--rule);
    border-radius: 0 0 var(--radius-lg) var(--radius-lg);
    background: var(--surface-2);
    padding: var(--space-3) var(--space-6);
  }

  .counter {
    font-size: var(--text-xs);
    font-variant-numeric: tabular-nums;
    color: var(--muted);
  }

  .spacer {
    width: 7.5rem;
  }

  /* Los botones son los globales (`.btn`, `.btn-primary`); aquí sólo el ancho
     mínimo, para que «Anterior» y «Siguiente» no bailen al cambiar de paso. */
  .nav .btn {
    min-width: 7.5rem;
  }

  /* Deshabilitado se dice con algo más que un tono más claro: sin relleno,
     borde punteado, y el motivo como tooltip de «Siguiente». */
  .nav .btn:disabled {
    border-style: dashed;
    border-color: var(--axis);
    background: transparent;
    color: var(--muted);
  }

  /* -- small screens ------------------------------------------------------- */

  @container wizard (max-width: 36rem) {
    .cuerpo {
      padding: var(--space-4) var(--space-4) 0;
    }

    .nav {
      margin-inline: calc(var(--space-4) * -1);
      padding-inline: var(--space-4);
    }

    /* Only the current step keeps its name; the others stay as circles. */
    .pasos li:not(.current) .label {
      display: none;
    }

    .counter {
      display: none;
    }

    .nav .btn {
      min-width: 0;
      flex: 1;
    }

    .spacer {
      display: none;
    }
  }
</style>
