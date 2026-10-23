<script lang="ts">
  import { fly } from 'svelte/transition';

  import { fetchHealth, reconocerArchivo, type Health, type Sugerencia } from '$lib/api';
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

  const habilidades = HABILIDADES;

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
</script>

<!-- ========================================================================
     VISTA
     ======================================================================== -->
<div class="upload-panel">
  <header class="panel-header">
    <h1 class="panel-title">Nuevo trabajo</h1>
    {#if health}
      <HealthBadge {health} />
    {/if}
  </header>

  <div class="panel-body">
    <!-- Paso 1: Tipo de documento -->
    {#if pasoId === 'tipo'}
      <PasoTipoDocumento
        {habilidadId}
        {habilidades}
        {noDisponible}
        onElegir={elegirHabilidad}
        onUsarSugerencia={usarSugerencia}
        {sugerencias}
        {reconociendo}
        {errorDeReconocer}
        {disabled}
        numero={pasoActual}
      />
    {:else if pasoId === 'lectura'}
      <PasoLectura
        {lectura}
        onElegir={elegirLectura}
        {lecturas}
        {blockedLectura}
        {faltaLectura}
        {disabled}
        numero={pasoActual}
      />
    {:else if pasoId === 'resultado'}
      <PasoResultado
        {resultado}
        onElegir={elegirResultado_}
        {acciones}
        {entrega}
        {disabled}
        numero={pasoActual}
      />
    {:else if pasoId === 'corte'}
      <PasoCorte
        {cortes}
        {corteElegido}
        onElegir={elegirCorte}
        {disabled}
        numero={pasoActual}
      />
    {:else if pasoId === 'agrupar'}
      <PasoAgrupar
        {agruparElegido}
        onElegir={elegirAgrupar}
        {agrupacionesElegibles}
        {health}
        pregunta={habilidad.agrupar?.pregunta}
        {disabled}
        {territorial}
        onTerritorial={elegirTerritorial}
        onListo={siguiente}
        numero={pasoActual}
      />
    {:else if pasoId === 'oracle'}
      <PasoOracle {oracle} onElegir={elegirOracle} {oracles} {blocked} numero={pasoActual} />
    {:else if pasoId === 'origen'}
      <PasoOrigen
        {mode}
        onElegirModo={elegirModo}
        {prepararArchivos}
        {confirmarSubida}
        {pendientes}
        {sugerencias}
        {reconociendo}
        {errorDeReconocer}
        {disabled}
        {blocked}
        {blockedLectura}
        {territorial}
        onTerritorial={elegirTerritorial}
        numero={pasoActual}
      />
    {/if}
  </div>

  <!-- Barra de progreso -->
  <div class="progress-bar" role="navigation" aria-label="Pasos del asistente">
    {#each pasos as pasoId, i}
      <span class="progress-step" class:current={i + 1 === pasoActual} class:done={i + 1 < pasoActual}>
        <span class="step-number">{i + 1}</span>
        <span class="step-label">{STEP_LABELS[pasoId]}</span>
      </span>
      {#if i < pasos.length - 1}
        <span class="progress-separator" aria-hidden="true">/</span>
      {/if}
    {/each}
  </div>

  {#if notice}
    <div class="notice" role="alert" tabindex="-1">
      {notice}
    </div>
  {/if}
</div>

<style>
  .upload-panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 600px;
  }

  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-4) var(--space-6);
    border-bottom: 1px solid var(--color-border);
    background: var(--color-surface);
  }

  .panel-title {
    font-size: var(--text-lg);
    font-weight: 600;
    color: var(--color-text);
    margin: 0;
  }

  .panel-body {
    flex: 1;
    overflow-y: auto;
    padding: var(--space-6);
  }

  .notice {
    margin: var(--space-4) var(--space-6);
    padding: var(--space-3) var(--space-4);
    background: var(--color-warning-bg);
    border: 1px solid var(--color-warning-border);
    border-radius: var(--radius-md);
    color: var(--color-warning-text);
    font-size: var(--text-sm);
  }

  /* Progress bar */
  .progress-bar {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-6);
    border-top: 1px solid var(--color-border);
    background: var(--color-surface);
    flex-wrap: wrap;
  }

  .progress-step {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    font-size: var(--text-xs);
    color: var(--color-text-muted);
    white-space: nowrap;
  }

  .progress-step.current {
    color: var(--color-primary);
    font-weight: 600;
  }

  .progress-step.done {
    color: var(--color-success);
  }

  .progress-separator {
    color: var(--color-border);
  }

  @media (prefers-reduced-motion: reduce) {
    .progress-step {
      transition: none;
    }
  }
</style>