<script lang="ts">
  import { fly } from 'svelte/transition';

  import { fetchHealth, reconocerArchivo, type Health, type Sugerencia } from '$lib/api';
  import UploadSummary from '$lib/components/UploadSummary.svelte';
  import Callout from '$lib/components/wizard/Callout.svelte';
  import PasoAgrupar from '$lib/components/wizard/PasoAgrupar.svelte';
  import PasoClaseDocumento from '$lib/components/wizard/PasoClaseDocumento.svelte';
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
    type CorteChoice,
    type TipoDocumentoChoice
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
  /** El tipo de documento de la caja: Afinia, Kingspan o mixto. */
  let tipoDocumento = $state<TipoDocumentoChoice>('indice_electronico');
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

  const cortes = $derived(habilidad.cortes?.opciones ?? []);
  const corteElegido = $derived<CorteChoice>(
    cortes.some((opcion) => opcion.id === corte) ? corte : (cortes[0]?.id ?? 'pagina')
  );

  /** Las opciones de tipo de documento que declara la habilidad (sólo correspondencia). */
  const tiposDocumento = $derived(habilidad.tipoDocumento?.opciones ?? []);
  /** La opción elegida, si la habilidad la declara. */
  const opcionTipoDocumento = $derived(tiposDocumento.find((t) => t.id === tipoDocumento));
  /**
   * La plantilla del inventario. No se pregunta aparte: sale del tipo de
   * documento. «Mixto» deja que el servicio la detecte por documento.
   */
  const plantilla = $derived(opcionTipoDocumento?.plantilla ?? 'auto');

  /**
   * Las agrupaciones que este tipo de documento admite.
   *
   * Kingspan no agrupa (cada documento es único) y su lista queda vacía: el
   * paso ni se muestra. «Grupo de páginas» se anuncia pero todavía no se puede
   * elegir, así que va deshabilitado.
   */
  const agrupaciones = $derived(
    (habilidad.agrupar?.opciones ?? []).filter(
      (opcion) => !opcion.disponiblePara || opcion.disponiblePara.includes(tipoDocumento)
    )
  );
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
   * Lo que se puede pedir de vuelta con esta habilidad, acotado al tipo de
   * documento elegido.
   *
   * Con Kingspan no se ofrece «dividir por documento» a secas: esa salida es
   * de la plantilla de Afinia. Si el tipo no declara sus acciones, se ofrecen
   * todas las de la habilidad.
   */
  const acciones = $derived(
    (habilidad.acciones ?? RESULTADOS).filter(
      (accion) =>
        !opcionTipoDocumento?.accionesDisponibles ||
        opcionTipoDocumento.accionesDisponibles.includes(accion.id as TaskKind)
    )
  );
  /* La acción elegida si esta habilidad la admite; si no, su primera. Al cambiar
     de habilidad el «split» de la anterior no vale para un libro de actas, que
     se inventaría o se divide. */
  const task = $derived<TaskKind>(
    habilidad.task ??
      (acciones.some((accion) => accion.id === resultado) ? resultado : (acciones[0]?.id ?? 'split'))
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
        ? plantilla === 'kingspan'
          ? 'Deja el inventario Kingspan (No. DOCUMENTO / DESDE / HASTA). No escribe ningún PDF.'
          : 'Deja el inventario. No escribe ningún PDF.'
        : task === 'both' && habilidad.tipo === 'acta-consejo'
          ? 'Deja un PDF por sesión y el inventario.'
          : task === 'both' && habilidad.tipo === 'acta'
            ? 'Deja un PDF por graduado y el FUID.'
          : task === 'both'
            ? plantilla === 'kingspan'
              ? 'Los dos: PDFs por documento + inventario Kingspan (DESDE/HASTA).'
              : 'Deja un PDF por documento y el inventario.'
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
  type StepId =
    | 'tipo'
    | 'claseDocumento'
    | 'lectura'
    | 'resultado'
    | 'corte'
    | 'agrupar'
    | 'oracle'
    | 'origen';

  const STEP_LABELS: Record<StepId, string> = {
    tipo: 'Tipo',
    claseDocumento: 'Documento',
    lectura: 'Lectura',
    resultado: 'Resultado',
    corte: 'Corte',
    agrupar: 'Agrupar',
    oracle: 'Modelo IA',
    origen: 'Origen'
  };

  /**
   * El tipo de documento se pregunta sólo en la caja de correspondencia: es la
   * única habilidad que sirve para papeles con plantillas de inventario
   * distintas (Afinia o Kingspan).
   */
  const mostrarClaseDocumento = $derived(
    habilidadId === 'correspondencia' && tiposDocumento.length > 0
  );

  /** El agrupar sólo aparece si el tipo elegido admite alguna agrupación. */
  const mostrarAgrupar = $derived(habilidad.agrupar !== undefined && agrupaciones.length > 0);

  const pasos = $derived<StepId[]>([
    'tipo',
    // Qué tipo de documento trae la caja: de aquí cuelgan la plantilla del
    // inventario y las agrupaciones que tienen sentido.
    ...(mostrarClaseDocumento ? (['claseDocumento'] as const) : []),
    // Todas las habilidades preguntan cómo se lee el papel, también «No estoy
    // seguro»: antes sólo lo preguntaban las que recomiendan IA, y las demás
    // corrían con «Solo OCR» sin que nadie lo eligiera -- una carpeta de actas
    // de grado entera salió sin folios por eso.
    'lectura',
    ...(eligeResultado ? (['resultado'] as const) : []),
    ...(habilidad.cortes ? (['corte'] as const) : []),
    ...(mostrarAgrupar ? (['agrupar'] as const) : []),
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
    tipoDocumento = habilidad.tipoDocumento?.opciones[0]?.id ?? 'indice_electronico';
    territorial = '';
    oracle = 'auto';
    resultado = 'split';
    notice = null;
    pendientes = [];
    paso = 1;
  }

  /**
   * Elegir el tipo de documento fija la plantilla del inventario y qué
   * agrupaciones se ofrecen. Si la agrupación elegida antes no vale para el
   * tipo nuevo, vuelve a la primera que sí valga.
   */
  function elegirClaseDocumento(id: TipoDocumentoChoice) {
    tipoDocumento = id;
    const opcion = tiposDocumento.find((t) => t.id === id);
    const validas = (habilidad.agrupar?.opciones ?? [])
      .filter((o) => !o.disponiblePara || o.disponiblePara.includes(id))
      .filter((o) => !o.proximamente);
    if (!validas.some((o) => o.id === agrupar)) {
      agrupar = validas[0]?.id ?? 'documento';
    }
    // Y la acción elegida: Kingspan no ofrece «dividir por documento» a secas.
    const accionesValidas = (habilidad.acciones ?? RESULTADOS).filter(
      (accion) =>
        !opcion?.accionesDisponibles || opcion.accionesDisponibles.includes(accion.id as TaskKind)
    );
    if (!accionesValidas.some((accion) => accion.id === resultado)) {
      resultado = accionesValidas[0]?.id ?? 'split';
    }
    notice = null;
    siguiente();
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
        {:else if pasoId === 'claseDocumento'}
          <PasoClaseDocumento
            {tipoDocumento}
            onElegir={elegirClaseDocumento}
            opciones={tiposDocumento}
            pregunta={habilidad.tipoDocumento?.pregunta}
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
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3.5 5.5 8l4.5 4.5" /></svg>
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
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5 10.5 8 6 12.5" /></svg>
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
    gap: var(--space-2);
    border: 0;
    background: none;
    padding: 0 var(--space-1);
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
    font-size: var(--text-sm);
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
    color: var(--on-accent);
  }

  .current .dot {
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

  .card {
    display: flex;
    flex-direction: column;
    gap: var(--space-5);
    border: 1px solid var(--hairline);
    border-radius: var(--radius-lg);
    background: var(--surface-2);
    padding: var(--space-6) var(--space-6) 0;
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
    .card {
      padding: var(--space-4) var(--space-4) 0;
    }

    .nav {
      margin-inline: calc(var(--space-4) * -1);
      padding-inline: var(--space-4);
    }

    /* Only the current step keeps its name; the others stay as dots. */
    .progress li:not(.current) .label {
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
