<script lang="ts">
  import { documentInventoryUrl, downloadUrl } from '$lib/api';
  import GroupsChart from '$lib/components/GroupsChart.svelte';
  import PageRibbon from '$lib/components/PageRibbon.svelte';
  import ResolutionRow from '$lib/components/ResolutionRow.svelte';
  import ProvenanceBar from '$lib/components/ProvenanceBar.svelte';
  import RunControls from '$lib/components/RunControls.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import { unitFor } from '$lib/format';
  import { SILENCE_THRESHOLD_SECONDS, STAGE_LABELS, STATE_LABELS } from '$lib/rungs';
  import type { Job } from '$lib/types';

  interface Props {
    job: Job;
  }

  let { job }: Props = $props();

  const report = $derived(job.report);
  const inventory = $derived(report?.inventory ?? null);
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
  const activity = $derived.by(() => {
    const label = STAGE_LABELS[progress.stage] ?? progress.stage;
    if (progress.stage === 'analysing') {
      const rate = progress.pages_per_second
        ? ` · ${progress.pages_per_second.toFixed(1)} p/s`
        : '';
      return `${label} · ${progress.pages_done} de ${progress.page_count} páginas${rate}`;
    }
    const done = progress.stage_done ?? 0;
    const total = progress.stage_total ?? 0;
    const counter = total ? ` · ${done} de ${total}` : '';
    const detail = progress.detail ? ` · ${progress.detail}` : '';
    return `${label}${counter}${detail}`;
  });

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

  const BADGE: Record<string, string> = {
    queued: 'text-muted',
    running: 'text-accent',
    paused: 'text-warning',
    done: 'text-good',
    failed: 'text-critical',
    cancelled: 'text-muted'
  };

  /** Maps a group to the file the assembler actually wrote. */
  function fileFor(code: string): string | undefined {
    return inventory?.items.find((item) => item.code === code)?.file_name;
  }

  function pageRange(pages: number[]): string {
    if (!pages.length) return '';
    const parts: string[] = [];
    let start = pages[0];
    let previous = pages[0];
    for (const page of pages.slice(1)) {
      if (page === previous + 1) {
        previous = page;
        continue;
      }
      parts.push(start === previous ? `${start}` : `${start}–${previous}`);
      start = previous = page;
    }
    parts.push(start === previous ? `${start}` : `${start}–${previous}`);
    return parts.join(', ');
  }
</script>

<article class="mb-4 rounded-xl border border-hairline bg-raised shadow-[var(--shadow)] p-5">
  <header class="flex items-start justify-between gap-4">
    <div class="min-w-0">
      <h3 class="truncate text-base font-semibold">{job.filename}</h3>
      <p class="mt-0.5 text-sm text-muted">
        {#if report}
          {report.page_count} páginas → {groups.length} {unit}
        {:else if live}
          {activity}
          {#if stageElapsed >= 2}<span class="text-muted"> · {stageElapsed.toFixed(0)} s en este paso</span>{/if}
          {#if quiet}<span class="quiet"> · sin novedades hace {silence.toFixed(0)} s</span>{/if}
        {:else}
          {STAGE_LABELS[progress.stage] ?? 'En cola'}
        {/if}
      </p>
    </div>
    <div class="flex shrink-0 flex-col items-end gap-2">
      <span
        class="rounded-full border border-hairline px-2.5 py-0.5 text-[0.7rem] tracking-wide uppercase {BADGE[
          job.state
        ]}"
      >
        {STATE_LABELS[job.state] ?? job.state}
      </span>
      <RunControls jobId={job.id} runState={job.state} />
    </div>
  </header>

  {#if job.state === 'cancelled'}
    <p class="mt-4 text-sm text-ink-2">
      Cancelado por el operador tras leer {progress.pages_done} de {progress.page_count} páginas.
      Lo que se alcanzó a escribir está entero.
    </p>
  {/if}

  {#if job.state === 'failed'}
    <p class="mt-4 font-mono text-sm text-critical">{job.error}</p>
  {/if}

  {#if live}
    <!-- The live view: one cell per page, painted by the rung that answered it. -->
    <div class="mt-4">
      <div class="mb-3 h-1.5 overflow-hidden rounded bg-grid">
        <div
          class="h-full rounded-r-[4px] bg-accent transition-[width] duration-300"
          style:width={`${progress.percent}%`}
        ></div>
      </div>
      <PageRibbon ribbon={progress.ribbon} pageCount={progress.page_count} />
    </div>
  {:else if job.state === 'queued'}
    <div class="mt-4 h-[3px] overflow-hidden rounded bg-grid">
      <div class="h-full w-1/3 animate-[slide_1.1s_ease-in-out_infinite] bg-accent"></div>
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
        note={review.length ? 'detalle abajo' : 'sin pendientes'}
        tone={review.length ? 'warning' : 'good'}
      />
      <StatTile
        label="Tiempo"
        value={`${progress.elapsed_seconds.toFixed(1)} s`}
        note={progress.pages_per_second ? `${progress.pages_per_second.toFixed(1)} p/s` : undefined}
      />
    </div>

    <div class="mt-6 grid gap-7 md:grid-cols-2">
      {#if stats}
        <ProvenanceBar {stats} pageCount={report.page_count} />
      {/if}
      <GroupsChart {groups} />
    </div>

    <div class="mt-6 overflow-x-auto">
      <table class="w-full border-collapse text-sm">
        <thead>
          <tr class="text-[0.7rem] tracking-wide text-muted uppercase">
            <th class="pb-2 text-left font-medium">{unitOneTitle}</th>
            <th class="pb-2 text-left font-medium">Tipo y procedencia</th>
            <th class="pb-2 text-left font-medium">Páginas</th>
            <th class="pb-2 text-left font-medium">Fecha</th>
            <th class="pb-2 text-left font-medium">Archivo</th>
            <th class="pb-2 text-right font-medium">Acciones</th>
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
      <section class="mt-5 rounded-lg bg-plane p-3 text-sm">
        <h4 class="mb-1.5 text-[0.7rem] font-medium tracking-wide text-muted uppercase">
          Correcciones de OCR aplicadas
        </h4>
        <ul class="list-disc pl-5 font-mono text-xs text-ink-2">
          {#each repairs as repair}
            <li>
              página {repair.page}: se leyó <b class="text-ink">{repair.observed}</b>, se mantuvo con
              <b class="text-ink">{repair.applied}</b>
              ({repair.distance} edición{repair.distance === 1 ? '' : 'es'})
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    {#if review.length}
      <section class="mt-4 rounded-lg border-l-[3px] border-warning bg-plane p-3 text-sm">
        <h4 class="mb-1.5 text-[0.7rem] font-medium tracking-wide text-muted uppercase">
          Requiere revisión humana ({review.length})
        </h4>
        <ul class="list-disc pl-5 text-ink-2">
          {#each review as item}
            <li>página {item.page} — {item.reason}</li>
          {/each}
        </ul>
        {#if quarantine.length}
          <a
            class="mt-2 inline-block text-accent hover:underline"
            href={downloadUrl(job.id, '_quarantine.pdf')}
            download
          >
            Descargar páginas en cuarentena
          </a>
        {/if}
      </section>
    {/if}

    {#if inventory}
      <footer
        class="mt-5 flex flex-wrap items-center justify-between gap-2 border-t border-hairline pt-3 text-sm text-muted"
      >
        <span>
          Inventario: {inventory.generated_files} archivos, {inventory.pages_accounted_for}/{inventory.source_pages}
          páginas contabilizadas
        </span>
        <span class="flex gap-4">
          <a
            class="text-accent hover:underline"
            href={documentInventoryUrl(job.id)}
            download
          >
            Inventario en Excel
          </a>
          <a class="text-accent hover:underline" href={downloadUrl(job.id, 'inventory.json')} download>
            JSON
          </a>
        </span>
      </footer>
    {/if}
  {/if}
</article>

<style>
  .quiet {
    color: var(--warning);
  }

  @keyframes slide {
    from {
      transform: translateX(-100%);
    }
    to {
      transform: translateX(340%);
    }
  }
</style>
