<script lang="ts">
  import { actasDelInforme } from '$lib/actas';
  import { documentInventoryUrl, downloadUrl } from '$lib/api';
  import GroupsChart from '$lib/components/GroupsChart.svelte';
  import Descargas from '$lib/components/Descargas.svelte';
  import Icono from '$lib/components/Icono.svelte';
  import PageRibbon from '$lib/components/PageRibbon.svelte';
  import ResolutionRow from '$lib/components/ResolutionRow.svelte';
  import ProvenanceBar from '$lib/components/ProvenanceBar.svelte';
  import RunControls from '$lib/components/RunControls.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import { pageRange, unitFor } from '$lib/format';
  import { SILENCE_THRESHOLD_SECONDS, STAGE_LABELS, STATE_LABELS, stageActivity } from '$lib/rungs';
  import type { Job } from '$lib/types';

  interface Props {
    job: Job;
  }

  let { job }: Props = $props();

  const report = $derived(job.report);
  const inventory = $derived(report?.inventory ?? null);
  /** La fila de un acta de consejo, cuando el trabajo fue eso. */
  const acta = $derived(report?.inventario_actas?.[0] ?? null);
  /** Todas las actas del PDF, cada una con su PDF si el libro se dividió. */
  const actas = $derived(actasDelInforme(report));
  const progress = $derived(job.progress);
  const live = $derived(job.state === 'running' && progress.page_count > 0);

  /**
   * Las listas del informe, siempre presentes aunque el informe no las traiga.
   *
   * No todos los documentos llenan las mismas casillas: un libro de folios no
   * tiene cuarentena porque ninguna página hereda de otra, y un inventario no
   * escribe salidas. Leerlas a pelo hacía que esta tarjeta reventara al
   * terminar un libro de diplomas, y con ella la pantalla entera.
   */
  const groups = $derived(report?.groups ?? []);
  const review = $derived(report?.review_queue ?? []);
  const repairs = $derived(report?.repairs ?? []);
  const quarantine = $derived(report?.quarantine ?? []);
  const stats = $derived(report?.stats ?? null);

  // Y se llaman por su nombre: "287 páginas → 287 resoluciones" delante de un
  // libro de registro de diplomas es una cifra correcta mal nombrada.
  const unit = $derived(unitFor(report, groups.length));
  const unitTitle = $derived(unit.charAt(0).toUpperCase() + unit.slice(1));
  const unitOne = $derived(unitFor(report, 1));
  const unitOneTitle = $derived(unitOne.charAt(0).toUpperCase() + unitOne.slice(1));

  /**
   * Qué está haciendo, ahora mismo, en una línea.
   *
   * Antes esta línea contaba siempre páginas, así que en cuanto el documento
   * terminaba de leerse se quedaba en "287 de 287 páginas" durante todo lo que
   * viniera después -- escribir doscientos ochenta y siete PDF, guardar la
   * planilla -- y desde fuera eso es indistinguible de un cuelgue. Ahora cada
   * etapa cuenta lo suyo: páginas la que lee, archivos la que escribe, filas la
   * que rellena el inventario.
   */
  const activity = $derived(stageActivity(progress));

  /** Cuánto lleva en la etapa actual, cuando ya lleva lo bastante como para notarse. */
  const stageElapsed = $derived(progress.stage_elapsed_seconds ?? 0);

  /**
   * Desde cuándo no llega noticia.
   *
   * Nunca es una alarma: es información. Un trabajo puede tardar diez segundos
   * en un paso sin que pase nada malo, y decirlo es justamente lo que evita que
   * parezca que se ha muerto.
   */
  const silence = $derived(progress.silent_seconds ?? 0);
  const quiet = $derived(silence >= SILENCE_THRESHOLD_SECONDS);

  /** El estado del trabajo, con las mismas píldoras que el resto de la aplicación. */
  const BADGE: Record<string, string> = {
    queued: 'pill pill-neutral',
    running: 'pill',
    paused: 'pill pill-warn',
    done: 'pill pill-good',
    failed: 'pill pill-bad',
    cancelled: 'pill pill-neutral'
  };

  /** Maps a group to the file the assembler actually wrote. */
  function fileFor(code: string): string | undefined {
    return inventory?.items.find((item) => item.code === code)?.file_name;
  }

</script>

<article class="panel tarjeta">
  <header class="flex items-start justify-between gap-4">
    <div class="min-w-0">
      <h2 class="nombre">{job.filename}</h2>
      <p class="resumen">
        {#if report}
          <span class="tabular">{report.page_count}</span> páginas →
          <span class="tabular">{groups.length}</span> {unit}
        {:else if live}
          {activity}
          {#if stageElapsed >= 2}<span> · {stageElapsed.toFixed(0)} s en este paso</span>{/if}
          {#if quiet}<span class="quiet"> · sin novedades hace {silence.toFixed(0)} s</span>{/if}
        {:else}
          {STAGE_LABELS[progress.stage] ?? 'En cola'}
        {/if}
      </p>
    </div>
    <div class="flex shrink-0 flex-col items-end gap-2">
      <span class={BADGE[job.state] ?? 'pill pill-neutral'}>
        {STATE_LABELS[job.state] ?? job.state}
      </span>
      <RunControls jobId={job.id} runState={job.state} />
    </div>
  </header>

  {#if job.state === 'cancelled'}
    <p class="texto mt-4">
      Cancelado por el operador tras leer {progress.pages_done} de {progress.page_count} páginas.
      Lo que se alcanzó a escribir está entero.
    </p>
  {/if}

  {#if job.state === 'failed'}
    <p class="inline-error mt-4">{job.error}</p>
  {/if}

  {#if live}
    <!-- The live view: one cell per page, painted by the rung that answered it. -->
    <div class="mt-4">
      <div class="barra mb-3">
        <div class="relleno transition-[width] duration-300" style:width={`${progress.percent}%`}></div>
      </div>
      <PageRibbon ribbon={progress.ribbon} pageCount={progress.page_count} />
    </div>
  {:else if job.state === 'queued'}
    <div class="barra fina mt-4">
      <div class="relleno w-1/3 animate-[slide_1.1s_ease-in-out_infinite]"></div>
    </div>
  {/if}

  {#if report}
    <div class="mt-5 flex flex-wrap gap-8">
      <StatTile label="Páginas" value={report.page_count} />
      <StatTile label={unitTitle} value={groups.length} />
      {#if stats}
        <StatTile
          label="Enviado al modelo"
          value={`${(stats.vision_page_ratio * 100).toFixed(1)}%`}
          note={`${stats.escalated} páginas · ${stats.vision_requests} consultas`}
          tone={stats.escalated > 0 ? 'warning' : 'good'}
        />
      {/if}
      <StatTile
        label="Requiere revisión"
        value={review.length}
        note={review.length ? 'Detalle abajo' : 'Sin pendientes'}
        tone={review.length ? 'warning' : 'good'}
      />
      <StatTile
        label="Tiempo"
        value={`${progress.elapsed_seconds.toFixed(1)} s`}
        note={progress.pages_per_second ? `${progress.pages_per_second.toFixed(1)} p/s` : undefined}
      />
      {#if report.consumo?.paginas_facturadas}
        <StatTile
          label="Páginas facturadas"
          value={report.consumo.paginas_facturadas}
          note={`${report.consumo.peticiones} peticiones al OCR de pago`}
        />
      {/if}
      {#if report.consumo?.tokens}
        <StatTile
          label="Tokens"
          value={report.consumo.tokens.toLocaleString('es-CO')}
          note={`${report.consumo.tokens_entrada.toLocaleString('es-CO')} entrada · ${report.consumo.tokens_salida.toLocaleString('es-CO')} salida`}
        />
      {/if}
      {#if report.consumo && report.consumo.coste_estimado !== null && report.consumo.coste_estimado !== undefined}
        <StatTile
          label="Costó"
          value={`${report.consumo.coste_estimado.toFixed(2)} ${report.consumo.moneda}`}
          note="Según el precio configurado"
        />
      {/if}
    </div>

    {#if report.notices?.length}
      <!-- Lo que el worker dice del trabajo en una frase. Sin esto, una caja
           pedida por mes que no tenía ni una fecha salía por documento y nada
           en la pantalla lo contaba. -->
      <ul class="avisos mt-4">
        {#each report.notices as aviso, i (i)}
          <li>{aviso}</li>
        {/each}
      </ul>
    {/if}

    <div class="mt-6 grid gap-7 md:grid-cols-2">
      {#if stats}
        <ProvenanceBar {stats} pageCount={report.page_count} />
      {/if}
      <GroupsChart {groups} />
    </div>

    <div class="mt-6 overflow-x-auto">
      <table class="tabla">
        <thead>
          <tr>
            <th>{unitOneTitle}</th>
            <th>Tipo y procedencia</th>
            <th>Páginas</th>
            <th>Fecha</th>
            <th>Archivo</th>
            <th class="derecha">Acciones</th>
          </tr>
        </thead>
        <tbody>
          {#each groups as group (group.code)}
            <ResolutionRow
              jobId={job.id}
              {group}
              fileName={fileFor(group.code)}
              pageRange={pageRange(group.pages)}
            />
          {/each}
        </tbody>
      </table>
    </div>

    {#if repairs.length}
      <section class="nota mt-5">
        <h3 class="caps mb-1.5">Correcciones de OCR aplicadas</h3>
        <ul class="lista">
          {#each repairs as repair}
            <li>
              Página <span class="tabular">{repair.page}</span>: se leyó
              <b class="codigo">{repair.observed}</b>, se mantuvo con
              <b class="codigo">{repair.applied}</b>
              (<span class="tabular">{repair.distance}</span> edición{repair.distance === 1 ? '' : 'es'})
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    {#if review.length}
      <section class="nota revision mt-4">
        <h3 class="caps mb-1.5">
          Requiere revisión humana (<span class="tabular">{review.length}</span>)
        </h3>
        <ul class="lista">
          {#each review as item}
            <li>Página <span class="tabular">{item.page}</span> — {item.reason}</li>
          {/each}
        </ul>
        {#if quarantine.length}
          <a
            class="btn btn-tonal btn-sm mt-2"
            href={downloadUrl(job.id, '_quarantine.pdf')}
            download
          >
            <Icono nombre="descargar" />
            Descargar páginas en cuarentena (PDF)
          </a>
        {/if}
      </section>
    {/if}

    {#if acta}
      <!-- Un acta de consejo no deja PDF: deja su fila del inventario. Se
           enseña aquí lo mismo que dirá el Excel, para no tener que abrirlo
           para saber si salió bien. -->
      <footer class="pie flex flex-col gap-1">
        {#if actas.length > 1}
          <!-- Un libro: todas sus actas, cada una con sus folios y, si se
               dividió, el PDF en que quedó. -->
          <span class="fuerte">
            Libro de {actas.length} actas{report?.dividido ? `, dividido en ${actas.filter((item) => item.pdf).length} PDF` : ''}
          </span>
          <ul class="mt-1 flex flex-col gap-1">
            {#each actas as item, indice (indice)}
              <li class="flex flex-wrap items-center gap-x-2">
                <b class="fuerte">{item.fila.acta}</b>
                <span class="tabular">{item.fila.fecha}</span>
                <span class="tabular">
                  folios {item.fila.folio_inicial} a {item.fila.folio_final} ({item.fila.folios})
                </span>
                {#if item.pdf}
                  <a
                    class="btn btn-icon"
                    href={downloadUrl(job.id, item.pdf)}
                    download
                    title="Descargar PDF"
                    aria-label={`Descargar el PDF del acta ${item.fila.acta}`}
                  >
                    <Icono nombre="descargar" />
                  </a>
                {/if}
                {#if item.fila.observaciones}
                  <span class="observacion basis-full">{item.fila.observaciones}</span>
                {/if}
              </li>
            {/each}
          </ul>
        {:else}
          <span class="fuerte">
            <b>{acta.acta}</b> · <span class="tabular">{acta.fecha}</span> · folios
            <span class="tabular">{acta.folio_inicial} a {acta.folio_final} ({acta.folios})</span>
          </span>
          {#if acta.observaciones}
            <span class="observacion">{acta.observaciones}</span>
          {/if}
        {/if}
        {#if report?.inventario}
          <a class="btn btn-tonal btn-sm mt-1 self-start" href={documentInventoryUrl(job.id)} download>
            <Icono nombre="descargar" />
            Descargar inventario del acta (Excel)
          </a>
        {:else if report?.inventario_error}
          <p class="inline-error">No se pudo escribir el Excel: {report.inventario_error}</p>
        {/if}
      </footer>
    {:else if inventory}
      <footer class="pie flex flex-wrap items-center justify-between gap-2">
        <span>
          Inventario: <span class="tabular">{inventory.generated_files}</span> archivos,
          <span class="tabular">{inventory.pages_accounted_for}/{inventory.source_pages}</span>
          páginas contabilizadas
        </span>
      </footer>
      <div class="mt-3 max-w-[34rem]">
        <Descargas
          grupos={[
            {
              titulo: 'Inventario',
              items: [
                {
                  id: 'excel',
                  titulo: report?.indice_electronico ? 'Índice electrónico' : 'Inventario del documento',
                  detalle: report?.indice_electronico
                    ? 'Plantilla del cliente, una fila por documento'
                    : 'Una fila por PDF generado',
                  formato: 'Excel',
                  principal: true,
                  href: documentInventoryUrl(job.id)
                },
                {
                  id: 'json',
                  titulo: 'Informe del proceso',
                  detalle: 'El mismo inventario con el detalle técnico de cada corte',
                  formato: 'JSON',
                  href: downloadUrl(job.id, 'inventory.json')
                }
              ]
            }
          ]}
        />
      </div>
    {/if}
  {/if}
</article>

<style>
  .tarjeta {
    margin-bottom: var(--space-4);
  }

  .nombre {
    margin: 0;
    overflow: hidden;
    font-size: var(--text-lg);
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .resumen {
    margin: 0.15rem 0 0;
    font-size: var(--text-md);
    color: var(--muted);
  }
  .texto {
    margin-bottom: 0;
    font-size: var(--text-md);
    color: var(--ink-2);
  }

  .quiet {
    color: var(--warning-ink);
  }

  /* La barra de avance. */
  .barra {
    height: 6px;
    overflow: hidden;
    border-radius: var(--radius-pill);
    background: var(--grid);
  }
  .barra.fina {
    height: 3px;
  }
  .relleno {
    height: 100%;
    border-radius: var(--radius-pill);
    background: var(--accent);
  }

  .avisos {
    display: grid;
    gap: var(--space-1);
    margin-bottom: 0;
    border: 1px solid var(--hairline);
    border-radius: var(--radius);
    padding: var(--space-2) var(--space-3);
    list-style: none;
    font-size: var(--text-sm);
    color: var(--ink-2);
  }

  /* La tabla de lo que se produjo: cabecera en versalitas, como todas. */
  .tabla {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-sm);
  }
  .tabla th {
    padding: 0 0.75rem 0.5rem 0;
    font-size: var(--text-2xs);
    font-weight: 600;
    letter-spacing: var(--tracking-caps);
    text-align: left;
    text-transform: uppercase;
    color: var(--muted);
  }
  .tabla th.derecha {
    padding-right: 0;
    text-align: right;
  }

  /* Correcciones y pendientes: notas sobre el plano, no tarjetas dentro de la
     tarjeta. La de revisión lleva el tinte de aviso. */
  .nota {
    border-radius: var(--radius-md);
    background: var(--plane);
    padding: var(--space-3);
    font-size: var(--text-sm);
  }
  .nota.revision {
    border-left: 3px solid var(--warning);
    background: var(--warning-soft);
  }
  .nota h3 {
    margin-top: 0;
  }
  .lista {
    margin: 0;
    padding-left: 1.25rem;
    list-style: disc;
    color: var(--ink-2);
  }
  .codigo {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--ink);
  }

  .pie {
    margin-top: var(--space-5);
    border-top: 1px solid var(--hairline);
    padding-top: var(--space-3);
    font-size: var(--text-sm);
    color: var(--muted);
  }
  .fuerte {
    color: var(--ink);
  }
  .observacion {
    font-size: var(--text-xs);
    color: var(--warning-ink);
  }

  /* Global: la clase de Tailwind `animate-[slide…]` lo busca por su nombre, y
     Svelte renombra los keyframes locales. */
  @keyframes -global-slide {
    from {
      transform: translateX(-100%);
    }
    to {
      transform: translateX(340%);
    }
  }
</style>
