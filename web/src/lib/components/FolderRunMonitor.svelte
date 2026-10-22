<script lang="ts">
  import { onMount } from 'svelte';

  import {
    descargarPlanilla,
    folderInventarioUrl,
    origenInventarioUrl,
    origenProcesosUrl
  } from '$lib/api';
  import Descargas, { type GrupoDeDescargas } from '$lib/components/Descargas.svelte';
  import { confirmar } from '$lib/confirmar.svelte';
  import FolderTree from '$lib/components/FolderTree.svelte';
  import Icono from '$lib/components/Icono.svelte';
  import PageRibbon from '$lib/components/PageRibbon.svelte';
  import RunStats from '$lib/components/RunStats.svelte';
  import PanelDeRendimiento from '$lib/components/PanelDeRendimiento.svelte';
  import { marcadasEnCinta, sumarConsumos } from '$lib/rendimiento';
  import { jobStore } from '$lib/jobs.svelte';
  import { unitFor } from '$lib/format';
  import { STAGE_LABELS } from '$lib/rungs';
  import type { FolderRun } from '$lib/types';

  interface Props {
    run: FolderRun;
  }

  let { run }: Props = $props();

  let now = $state(Date.now());
  onMount(() => {
    const tick = setInterval(() => (now = Date.now()), 250);
    return () => clearInterval(tick);
  });

  let stopping = $state(false);
  let forgetting = $state(false);
  let error = $state<string | null>(null);

  const STATES: Record<string, string> = {
    scanning: 'Explorando la carpeta',
    processing: 'Procesando',
    watching: 'Vigilando — esperando archivos nuevos',
    recovering: 'Recuperándose — en pausa tras unos fallos, sigue sola',
    done: 'Terminado',
    stopped: 'Detenido',
    failed: 'Falló'
  };

  const active = $derived(['scanning', 'processing', 'watching', 'recovering'].includes(run.state));

  /**
   * Cuántos documentos esperan turno. Lo cuenta el servicio, porque `run.queue`
   * sólo trae los primeros cuarenta: una carpeta de archivo real trae catorce
   * mil PDF, y mandarlos todos en cada aviso son cuatrocientos kilobytes por
   * documento procesado para enseñar cuarenta nombres.
   */
  const enCola = $derived(run.queued ?? run.queue.length);

  /**
   * El reloj de la corrida y su avance, que hasta ahora esta pantalla no daba.
   *
   * Una carpeta vigilada corre sola durante horas y era la única de las tres
   * cargas que no decía ni cuánto llevaba, ni cuántas páginas, ni a qué
   * velocidad -- justo la que más falta hace cuando nadie está delante.
   */
  const elapsedSeconds = $derived.by(() => {
    const from = Date.parse(run.started_at);
    if (Number.isNaN(from)) return 0;
    const to = run.finished_at ? Date.parse(run.finished_at) : now;
    return Math.max(0, ((Number.isNaN(to) ? now : to) - from) / 1000);
  });

  /**
   * Los documentos que la carpeta tiene abiertos ahora, varios a la vez. Un
   * servicio anterior sólo dice el actual, y entonces la lista es ése.
   */
  const abiertos = $derived(
    (run.en_curso ??
      (run.current && run.current_job_id
        ? [{ job_id: run.current_job_id, nombre: run.current }]
        : [])
    ).map((item) => ({ ...item, job: jobStore.get(item.job_id) }))
  );
  const job = $derived(abiertos[0]?.job);

  /**
   * Los documentos de la carpeta que siguen en pantalla, para sumar de dónde
   * salió cada página, cuántas quedaron por revisar y lo gastado con la IA.
   */
  const trabajos = $derived.by(() => {
    const ids = new Set(run.job_ids);
    return jobStore.jobs.filter((trabajo) => ids.has(trabajo.id));
  });

  /** Páginas del documento abierto ahora mismo, sobre el total ya contado. */
  const pagesDone = $derived(
    run.pages_total + abiertos.reduce((suma, item) => suma + (item.job?.progress.pages_done ?? 0), 0)
  );
  /** La velocidad de la carpeta es la suma de la de todos los que lee a la vez. */
  const rate = $derived(
    abiertos.reduce((suma, item) => suma + (item.job?.progress.pages_per_second ?? 0), 0)
  );
  const unitLabel = $derived(unitFor(job?.report?.stats, run.resolutions));

  function clock(at: string): string {
    const parsed = Date.parse(at);
    if (Number.isNaN(parsed)) return '';
    return new Date(parsed).toLocaleTimeString('es', { hour12: false });
  }

  async function stop() {
    const seguro = await confirmar({
      titulo: '¿Detener el procesamiento de esta carpeta?',
      mensaje:
        'Se cancela el documento que se está procesando y los que faltan no se empiezan. ' +
        'Lo que ya se entregó se queda en la carpeta de destino.',
      aceptar: 'Detener',
      volver: 'Seguir procesando',
      peligro: true
    });
    if (!seguro) return;
    stopping = true;
    error = null;
    try {
      await jobStore.stopFolder(run.id);
    } catch (problem) {
      error = (problem as Error).message;
    } finally {
      stopping = false;
    }
  }


  /**
   * Cuántas actas van ya en el inventario de la carpeta. Lo dice el servicio,
   * que es quien junta las filas; uno anterior a la revisión 20 no lo dice, y
   * entonces no hay inventario de actas que enseñar.
   */
  const actasDelInventario = $derived(run.inventario_filas ?? 0);

  /*
   * Al retomar una carpeta de libros de diplomas: qué había de cada PDF en el
   * destino y cómo quedó, contado página a página por el servicio.
   */
  const retomando = $derived(run.retomar === 'faltantes' || run.retomar === 'revisar');
  /** Lo que la corrida saltó, rehízo o no pudo entregar entero, y sus avisos. */
  const entrega = $derived({
    ya: run.ya_entregados ?? 0,
    sinConstancia: run.sin_constancia ?? 0,
    rehechos: run.rehechos ?? 0,
    incompletas: run.entregas_incompletas ?? 0,
    avisos: run.avisos ?? []
  });
  const controles = $derived(run.controles ?? []);
  const estadoDe = (control: (typeof controles)[number]) =>
    (control.despues ?? control.antes)?.estado ?? null;
  const completos = $derived(controles.filter((c) => estadoDe(c) === 'completo').length);
  const porEntregar = $derived(
    controles.filter((c) => estadoDe(c) && estadoDe(c) !== 'completo')
  );
  const conAvisos = $derived(controles.filter((c) => c.observaciones));
  const validacion = $derived(run.inventario_validacion ?? null);

  /**
   * Bajar el Excel con todas las actas de la carpeta. Por `fetch`, para que un
   * fallo se diga aquí con palabras en vez de abrir una página de error.
   */
  /**
   * Los inventarios generales de la carpeta, en la raíz del destino: el de la
   * habilidad -- el de actas, o el Índice Electrónico de las cajas de
   * correspondencia con una hoja por PDF -- y el general del bot, una fila por
   * PDF procesado. Se ofrecen en cuanto termina el primer PDF.
   */
  const descargas = $derived<GrupoDeDescargas[]>(
    run.processed + run.failed > 0
      ? [
          {
            titulo: 'Inventarios generales de la carpeta',
            items: [
              ...(run.inventario
                ? [
                    {
                      id: 'actas',
                      titulo: 'Inventario de actas',
                      detalle: 'Una fila por acta de toda la carpeta',
                      formato: 'Excel' as const,
                      principal: true,
                      bajar: () =>
                        descargarPlanilla(folderInventarioUrl(run.id), run.inventario ?? 'inventario.xlsx')
                    }
                  ]
                : run.task === 'segment' && run.processed > 0
                  ? [
                      {
                        id: 'indice',
                        titulo: 'Índice electrónico',
                        detalle: 'Plantilla del cliente, una hoja por PDF procesado',
                        formato: 'Excel' as const,
                        principal: true,
                        bajar: () =>
                          descargarPlanilla(origenInventarioUrl(run.id), '00.INDICE ELECTRONICO.xlsx')
                      }
                    ]
                  : []),
              {
                id: 'procesos',
                titulo: 'Inventario de procesos',
                detalle: 'Lo que hizo el bot con cada PDF: habilidad, lectura, resultado y revisión',
                formato: 'Excel' as const,
                bajar: () =>
                  descargarPlanilla(origenProcesosUrl(run.id), '00.INVENTARIO GENERAL DE PROCESOS.xlsx')
              }
            ]
          }
        ]
      : []
  );

  /**
   * Quitar la tarjeta de la pantalla.
   *
   * No deshace nada: lo entregado sigue en la carpeta de destino y el archivo
   * conserva sus filas. Sólo está disponible cuando la carpeta ya terminó,
   * porque quitar una viva dejaría el trabajo corriendo sin nadie que informara.
   */
  async function forget() {
    const seguro = await confirmar({
      titulo: '¿Quitar esta carpeta de la pantalla?',
      mensaje:
        'Sólo se quita la tarjeta: lo entregado sigue en la carpeta de destino y en el archivo.',
      aceptar: 'Quitar'
    });
    if (!seguro) return;
    forgetting = true;
    error = null;
    try {
      await jobStore.forgetRun(run.id);
    } catch (problem) {
      error = (problem as Error).message;
      forgetting = false;
    }
  }
</script>

<section class="run" data-state={run.state}>
  <header class="head">
    <span class="lamp" aria-hidden="true"></span>
    <div class="titles">
      <b>{STATES[run.state] ?? run.state}</b>
      <small class="paths">
        <span title={run.source}>{run.source}</span>
        <span class="arrow" aria-hidden="true">→</span>
        <span title={run.destination}>{run.destination}</span>
      </small>
    </div>
    {#if active}
      <button class="btn btn-sm btn-danger accion" onclick={stop} disabled={stopping}>
        {stopping ? 'Deteniendo…' : 'Detener'}
      </button>
    {:else}
      <button
        class="btn btn-sm btn-ghost accion"
        onclick={forget}
        disabled={forgetting}
        title="Quitar de la pantalla. Lo entregado se queda donde está."
      >
        {forgetting ? 'Quitando…' : 'Quitar'}
      </button>
    {/if}
  </header>

  {#if run.error}
    <p class="inline-error">{run.error}</p>
  {/if}
  {#if error}
    <p class="inline-error">{error}</p>
  {/if}

  <!-- El inventario general de la carpeta: un Excel con una fila por PDF, que
       se reescribe con cada acta. Va arriba de todo y con el botón grande
       porque es lo que se entrega: el «Excel de esta acta» de cada PDF, más
       abajo, es sólo de ese documento, y confundirlos dejaba al operador con
       una fila en vez de la carpeta entera. -->
  {#if actasDelInventario > 0 || run.inventario_error}
    <div class="inventario" data-listo={run.inventario ? 'si' : 'no'}>
      {#if run.inventario}
        <div class="texto">
          <b>Inventario general de la carpeta</b>
          <small>
            {actasDelInventario}
            {actasDelInventario === 1 ? 'acta' : 'actas'}{active ? ' hasta ahora' : ''}, una fila
            por PDF · quedó en la carpeta de destino como
            <code title={run.inventario_ruta ?? run.inventario}>{run.inventario}</code>
          </small>
          {#if validacion && validacion.filas}
            <!-- El control de calidad antes de entregar: qué tan completo va. -->
            <small class="validacion" data-pendientes={validacion.pendientes ? 'si' : 'no'}>
              Validación: {validacion.completas} de {validacion.filas} filas completas
              {#if validacion.razonadas}· {validacion.razonadas} completadas razonando con las actas vecinas{/if}
              {#if validacion.pendientes}
                · {validacion.pendientes} con datos que el papel no trae o no deja leer
                ({Object.entries(validacion.por_dato)
                  .map(([dato, cuantas]) => `${dato}: ${cuantas}`)
                  .join(', ')}) — cada una lo explica en observaciones
              {/if}
              {#if validacion.nombres_dudosos}
                · {validacion.nombres_dudosos}
                {validacion.nombres_dudosos === 1 ? 'nombre dudoso' : 'nombres dudosos'} para revisar en el
                papel
              {/if}
            </small>
          {/if}
        </div>
      {:else}
        <p class="inline-error">No se pudo escribir el inventario de actas: {run.inventario_error}</p>
      {/if}
    </div>
  {/if}

  {#if retomando && controles.length}
    <div class="inventario control" data-listo={porEntregar.length ? 'no' : 'si'}>
      <div class="texto">
        <b>{run.retomar === 'revisar' ? 'Revisión del destino' : 'Control de entrega'}</b>
        <small>
          {controles.length}
          {controles.length === 1 ? 'PDF mirado' : 'PDF mirados'}{active ? ' hasta ahora' : ''}
          · {completos} {completos === 1 ? 'completo' : 'completos'} en el destino
          {#if run.ya_entregados}· {run.ya_entregados} ya {run.ya_entregados === 1 ? 'estaba' : 'estaban'}
            y no se {run.ya_entregados === 1 ? 'volvió' : 'volvieron'} a procesar{/if}
          {#if run.control}
            · quedó en la carpeta de destino como
            <code title={run.control_ruta ?? run.control}>{run.control}</code>
          {/if}
        </small>
        {#each porEntregar.slice(0, 8) as control (control.pdf)}
          {@const ultima = control.despues ?? control.antes}
          <small class="validacion" data-pendientes="si">
            {control.pdf}: {ultima?.estado}{ultima?.faltantes_rangos
              ? ` — faltan las páginas ${ultima.faltantes_rangos}`
              : ''}
          </small>
        {/each}
        {#if porEntregar.length > 8}
          <small>y {porEntregar.length - 8} más: el control los lista todos.</small>
        {/if}
        {#each conAvisos.slice(0, 5) as control (control.pdf)}
          <small class="validacion" data-pendientes="si">{control.pdf}: {control.observaciones}</small>
        {/each}
      </div>
    </div>
  {/if}

  {#if run.analisis}
    <div class="inventario control" data-listo="si">
      <div class="texto">
        <b>Análisis de la entrega</b>
        <small>
          Procesados, ya entregados, fallidos y pendientes por carpeta y PDF, con el motivo.
          Archivo en la raíz del destino:
          <code title={run.analisis_ruta ?? run.analisis}>{run.analisis}</code>
        </small>
      </div>
    </div>
  {/if}

  {#if !retomando && (entrega.ya || entrega.rehechos || entrega.incompletas || entrega.avisos.length || run.recuperados || run.por_reintentar)}
    <div class="inventario control" data-listo={entrega.incompletas || entrega.avisos.length ? 'no' : 'si'}>
      <div class="texto">
        <b>{run.state === 'recovering' ? 'Recuperándose: la carpeta sigue sola' : 'Entrega y recuperación'}</b>
        <small>
          {#if entrega.ya}
            {entrega.ya} {entrega.ya === 1 ? 'PDF ya estaba entregado' : 'PDF ya estaban entregados'} y no se
            {entrega.ya === 1 ? 'volvió' : 'volvieron'} a leer{#if entrega.sinConstancia}
              ({entrega.sinConstancia} de una corrida anterior, sin constancia de entrega){/if}
          {/if}
          {#if entrega.rehechos}
            · {entrega.rehechos} {entrega.rehechos === 1 ? 'se rehízo' : 'se rehicieron'}: la entrega se había
            cortado o el original cambió (lo anterior quedó en <code>_reemplazados</code>)
          {/if}
          {#if run.recuperados}
            · {run.recuperados} {run.recuperados === 1 ? 'falló y salió bien' : 'fallaron y salieron bien'} al
            reintentarse
          {/if}
          {#if run.por_reintentar}
            · {run.por_reintentar} {run.por_reintentar === 1 ? 'espera' : 'esperan'} la vuelta de reintento del final
          {/if}
          {#if entrega.incompletas}
            · {entrega.incompletas}
            {entrega.incompletas === 1 ? 'no se pudo copiar entero' : 'no se pudieron copiar enteros'} al destino:
            al volver a lanzar la carpeta se rehacen
          {/if}
        </small>
        {#each entrega.avisos.slice(-5) as aviso (aviso)}
          <small class="validacion" data-pendientes="si">{aviso}</small>
        {/each}
      </div>
    </div>
  {/if}

  {#if descargas.length}
    <div class="descargas"><Descargas grupos={descargas} /></div>
  {/if}

  <RunStats
    {pagesDone}
    pagesTotal={0}
    units={run.resolutions}
    {unitLabel}
    bytesTotal={run.bytes_total}
    bytesDone={run.bytes_total}
    {rate}
    {elapsedSeconds}
    queued={enCola}
    failed={run.failed}
    settled={!active}
  />

  <PanelDeRendimiento
    paginasHechas={pagesDone}
    paginasTotal={0}
    velocidad={rate}
    segundos={elapsedSeconds}
    etapas={active ? abiertos.map((item) => item.job?.progress.stage) : []}
    procedencias={[
      ...trabajos.map((trabajo) => trabajo.progress.by_provenance),
      ...(run.retirados ? [run.retirados.procedencias] : [])
    ]}
    revision={trabajos.reduce((suma, trabajo) => suma + marcadasEnCinta(trabajo.progress.ribbon), 0) +
      (run.retirados?.revision ?? 0)}
    fallidas={trabajos.reduce((suma, trabajo) => suma + trabajo.progress.failed_pages, 0) +
      (run.retirados?.fallidas ?? 0)}
    documentos={{
      hechos: run.processed,
      fallidos: run.failed,
      enCola: enCola,
      total: run.watch ? null : run.discovered
    }}
    consumo={sumarConsumos([
      ...trabajos.map((trabajo) => trabajo.progress.consumo ?? trabajo.report?.consumo),
      run.retirados?.consumo
    ])}
    vivo={active}
  />

  <!-- Los que se leen ahora, varios a la vez: cada uno con su etapa y su
       avance. Una carpeta cerrada no está consumiendo nada, así que este bloque
       desaparece en vez de anunciar "ningún archivo abierto" para siempre. -->
  {#if active}
    <div class="column">
      <span class="section-label">
        Consumiendo ahora{abiertos.length > 1 ? ` (${abiertos.length} a la vez)` : ''}
      </span>
      {#if abiertos.length}
        {#each abiertos as item (item.job_id)}
          <article class="current">
            <div class="line">
              <span class="dot" aria-hidden="true"></span>
              <span class="file" title={item.nombre}>{item.nombre}</span>
              {#if item.job}
                <span class="stage">
                  {STAGE_LABELS[item.job.progress.stage] ?? item.job.progress.stage}
                </span>
                <span class="pages tabular">
                  {item.job.progress.pages_done}/{item.job.progress.page_count || '?'}
                </span>
              {/if}
            </div>
            {#if item.job?.progress.detail}
              <!-- Qué hace dentro de la etapa: con todas las páginas leídas, la
                   barra llena no dice si sigue trabajando o se quedó quieto. -->
              <small class="detalle">
                {item.job.progress.detail}{item.job.progress.stage_total
                  ? ` · ${item.job.progress.stage_done} de ${item.job.progress.stage_total}`
                  : ''}
              </small>
            {/if}
            {#if (item.job?.progress.silent_seconds ?? 0) >= 120}
              <small class="sin-novedad" role="status">
                Sin novedades desde hace {Math.floor((item.job?.progress.silent_seconds ?? 0) / 60)} min. Si
                sigue así, se da por atascado solo y se reintenta al final de la carpeta; los demás
                documentos siguen.
              </small>
            {/if}
            {#if item.job?.progress.page_count}
              <div class="bar">
                <div class="fill" style:width={`${item.job.progress.percent}%`}></div>
              </div>
              <PageRibbon
                ribbon={item.job.progress.ribbon}
                pageCount={item.job.progress.page_count}
              />
            {/if}
          </article>
        {/each}
      {:else}
        <p class="idle">
          {run.state === 'watching'
            ? 'Ningún archivo pendiente. La carpeta queda bajo vigilancia.'
            : 'Ningún archivo abierto.'}
        </p>
      {/if}
    </div>
  {/if}

  {#if enCola}
    <div class="column">
      <!-- Lo mismo dicho de dos maneras, porque no significa lo mismo. En una
           carpeta viva la cola es lo que va a procesarse; en una detenida es lo
           que se quedó sin procesar, y llamarlo "esperando turno" prometía un
           turno que no iba a llegar nunca. -->
      <span class="section-label" class:pendiente={!active}>
        {active
          ? `Esperando turno (${enCola})`
          : `Quedaron sin procesar (${enCola})`}
      </span>
      <ul class="queue">
        {#each run.queue.slice(0, 40) as name (name)}
          <li title={name}>{name}</li>
        {/each}
        {#if enCola > run.queue.length}
          <li class="more">+{enCola - run.queue.length} más</li>
        {/if}
      </ul>
    </div>
  {/if}

  <!-- Lo que salió de la carpeta, con la forma en que está guardado: la
       carpeta contiene PDF y cada PDF contiene las unidades en que se partió.
       La lista plana de entregados decía qué archivos aparecieron en el
       destino, pero no de cuál habían salido, y eso había que reconstruirlo de
       memoria. -->
  <div class="column">
    <span class="section-label">Lo que produjo</span>
    <FolderTree {run} />
  </div>
</section>

<style>
  .validacion {
    display: block;
    margin-top: 0.25rem;
    color: var(--good);
  }
  .validacion[data-pendientes='si'] {
    color: var(--ink-2);
  }
  .run {
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
    border: 1px solid color-mix(in oklab, var(--s4) 32%, var(--hairline));
    border-radius: var(--radius-lg);
    background: var(--surface-2);
    padding: 1.1rem 1.2rem;
    box-shadow: var(--shadow);
  }
  [data-state='done'],
  [data-state='stopped'] {
    border-color: var(--hairline);
  }
  [data-state='failed'] {
    border-color: color-mix(in oklab, var(--critical) 45%, var(--hairline));
  }

  .head {
    display: flex;
    align-items: flex-start;
    gap: 0.6rem;
  }
  .lamp {
    margin-top: 0.3rem;
    width: 8px;
    height: 8px;
    flex-shrink: 0;
    border-radius: 50%;
    background: var(--axis);
  }
  [data-state='processing'] .lamp,
  [data-state='scanning'] .lamp {
    background: var(--s4);
    box-shadow: 0 0 0 3px color-mix(in oklab, var(--s4) 18%, transparent);
    animation: breathe 1.6s ease-in-out infinite;
  }
  [data-state='recovering'] .lamp {
    background: var(--warning, var(--s4));
    animation: breathe 2.4s ease-in-out infinite;
  }
  [data-state='watching'] .lamp {
    background: var(--s4);
    animation: breathe 3s ease-in-out infinite;
  }
  [data-state='done'] .lamp {
    background: var(--good);
  }
  [data-state='failed'] .lamp {
    background: var(--critical);
  }

  .titles {
    display: flex;
    min-width: 0;
    flex-direction: column;
  }
  .titles b {
    font-size: var(--text-lg);
    font-weight: 650;
  }
  .paths {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 0.4rem;
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .paths span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .arrow {
    flex-shrink: 0;
    color: var(--s4);
  }

  /* Pegado a la derecha del encabezado; el aspecto es el de `.btn`. Detener
     interrumpe un trabajo y va en rojo; quitar sólo despeja la pantalla y no
     tiene por qué alarmar. */
  .head .accion {
    margin-left: auto;
    flex-shrink: 0;
  }

  .run > .inline-error,
  .inventario .inline-error {
    margin: 0;
  }

  .section-label.pendiente {
    color: var(--warning-ink);
  }

  .column {
    border-top: 1px solid var(--rule);
    padding-top: 0.8rem;
  }

  .inventario {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.8rem 1.2rem;
    border: 1px solid color-mix(in oklab, var(--s4) 45%, var(--hairline));
    border-radius: var(--radius-md);
    background: color-mix(in oklab, var(--s4) 9%, var(--surface-2));
    padding: 0.85rem 1rem;
  }
  .inventario .texto {
    display: flex;
    min-width: 0;
    flex: 1 1 18rem;
    flex-direction: column;
    gap: 0.2rem;
  }
  .inventario .texto b {
    font-size: var(--text-lg);
    font-weight: 650;
  }
  .inventario .texto small {
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .inventario code {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    overflow-wrap: anywhere;
  }
  /* La descarga es la tonal común: el relleno ámbar con letra blanca que
     tenía antes no se leía. */
  .section-label {
    display: block;
    margin-bottom: 0.45rem;
    font-size: var(--text-2xs);
    font-weight: 600;
    letter-spacing: var(--tracking-caps);
    text-transform: uppercase;
    color: var(--muted);
  }

  .current {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    border-radius: var(--radius-md);
    background: var(--plane);
    padding: 0.6rem 0.7rem;
  }
  .line {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
  }
  .dot {
    width: 6px;
    height: 6px;
    flex-shrink: 0;
    border-radius: 50%;
    background: var(--s4);
    animation: breathe 1.2s ease-in-out infinite;
  }
  .file {
    overflow: hidden;
    font-size: var(--text-sm);
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .stage {
    flex-shrink: 0;
    font-size: var(--text-xs);
    color: var(--ink-2);
  }
  .detalle {
    display: block;
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .sin-novedad {
    display: block;
    margin-top: 0.2rem;
    font-size: var(--text-xs);
    color: var(--ink);
    border-left: 3px solid var(--warning);
    padding-left: 0.4rem;
  }
  .pages {
    margin-left: auto;
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--muted);
  }

  .bar {
    height: 3px;
    overflow: hidden;
    border-radius: var(--radius-pill);
    background: var(--grid);
  }
  .fill {
    height: 100%;
    border-radius: var(--radius-pill);
    background: var(--s4);
    transition: width 0.3s ease-out;
  }

  .idle {
    margin: 0;
    font-size: var(--text-sm);
    color: var(--muted);
  }

  .queue {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .queue li {
    max-width: 14rem;
    overflow: hidden;
    border: 1px solid var(--hairline);
    border-radius: var(--radius-sm);
    background: var(--surface-1);
    padding: 0.12rem 0.45rem;
    font-size: var(--text-xs);
    color: var(--muted);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .queue .more {
    border-style: dashed;
  }

  .descargas {
    margin: 0.85rem 0;
    max-width: 34rem;
  }
</style>
