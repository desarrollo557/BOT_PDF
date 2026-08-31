<script lang="ts">
  import { downloadUrl } from '$lib/api';
  import GroupsChart from '$lib/components/GroupsChart.svelte';
  import PageRibbon from '$lib/components/PageRibbon.svelte';
  import ProvenanceBar from '$lib/components/ProvenanceBar.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import { STAGE_LABELS, STATE_LABELS } from '$lib/rungs';
  import type { Job } from '$lib/types';

  interface Props {
    job: Job;
  }

  let { job }: Props = $props();

  const report = $derived(job.report);
  const inventory = $derived(report?.inventory ?? null);
  const progress = $derived(job.progress);
  const live = $derived(job.state === 'running' && progress.page_count > 0);

  const BADGE: Record<string, string> = {
    queued: 'text-muted',
    running: 'text-s1',
    done: 'text-good',
    failed: 'text-critical'
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

<article class="mb-4 rounded-xl border border-hairline bg-surface p-5">
  <header class="flex items-start justify-between gap-4">
    <div class="min-w-0">
      <h3 class="truncate text-base font-semibold">{job.filename}</h3>
      <p class="mt-0.5 text-sm text-muted">
        {#if report}
          {report.page_count} páginas → {report.groups.length} resoluciones
        {:else if live}
          {STAGE_LABELS[progress.stage] ?? progress.stage} · {progress.pages_done} de {progress.page_count}
          páginas
          {#if progress.pages_per_second}· {progress.pages_per_second.toFixed(1)} p/s{/if}
        {:else}
          {STAGE_LABELS[progress.stage] ?? 'En cola'}
        {/if}
      </p>
    </div>
    <span
      class="shrink-0 rounded-full border border-hairline px-2.5 py-0.5 text-[0.7rem] tracking-wide uppercase {BADGE[
        job.state
      ]}"
    >
      {STATE_LABELS[job.state] ?? job.state}
    </span>
  </header>

  {#if job.state === 'failed'}
    <p class="mt-4 font-mono text-sm text-critical">{job.error}</p>
  {/if}

  {#if live}
    <!-- The live view: one cell per page, painted by the rung that answered it. -->
    <div class="mt-4">
      <div class="mb-3 h-1.5 overflow-hidden rounded bg-grid">
        <div
          class="h-full rounded-r-[4px] bg-s1 transition-[width] duration-300"
          style:width={`${progress.percent}%`}
        ></div>
      </div>
      <PageRibbon ribbon={progress.ribbon} pageCount={progress.page_count} />
    </div>
  {:else if job.state === 'queued'}
    <div class="mt-4 h-[3px] overflow-hidden rounded bg-grid">
      <div class="h-full w-1/3 animate-[slide_1.1s_ease-in-out_infinite] bg-s1"></div>
    </div>
  {/if}

  {#if report}
    <div class="mt-5 flex flex-wrap gap-8">
      <StatTile label="Páginas" value={report.page_count} />
      <StatTile label="Resoluciones" value={report.groups.length} />
      <StatTile
        label="Enviado al modelo"
        value={`${(report.stats.vision_page_ratio * 100).toFixed(1)}%`}
        note={`${report.stats.escalated} páginas · ${report.stats.vision_requests} consultas`}
        tone={report.stats.escalated > 0 ? 'warning' : 'good'}
      />
      <StatTile
        label="Requiere revisión"
        value={report.review_queue.length}
        note={report.review_queue.length ? 'detalle abajo' : 'sin pendientes'}
        tone={report.review_queue.length ? 'warning' : 'good'}
      />
      <StatTile
        label="Tiempo"
        value={`${progress.elapsed_seconds.toFixed(1)} s`}
        note={progress.pages_per_second ? `${progress.pages_per_second.toFixed(1)} p/s` : undefined}
      />
    </div>

    <div class="mt-6 grid gap-7 md:grid-cols-2">
      <ProvenanceBar stats={report.stats} pageCount={report.page_count} />
      <GroupsChart groups={report.groups} />
    </div>

    <div class="mt-6 overflow-x-auto">
      <table class="w-full border-collapse text-sm">
        <thead>
          <tr class="text-[0.7rem] tracking-wide text-muted uppercase">
            <th class="pb-2 text-left font-medium">Resolución</th>
            <th class="pb-2 text-left font-medium">Título</th>
            <th class="pb-2 text-left font-medium">Páginas</th>
            <th class="pb-2"></th>
          </tr>
        </thead>
        <tbody>
          {#each report.groups as group (group.code)}
            <tr class="border-t border-hairline">
              <td class="py-2 pr-3 font-mono text-xs whitespace-nowrap">{group.code}</td>
              <td class="py-2 pr-3 text-ink-2">{group.title ?? '—'}</td>
              <td class="py-2 pr-3 font-mono text-xs whitespace-nowrap tabular-nums">
                {pageRange(group.pages)}
                <span class="text-muted">({group.size})</span>
              </td>
              <td class="py-2 text-right">
                {#if fileFor(group.code)}
                  <a
                    class="text-s1 hover:underline"
                    href={downloadUrl(job.id, fileFor(group.code)!)}
                    download
                  >
                    PDF
                  </a>
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    {#if report.repairs.length}
      <section class="mt-5 rounded-lg bg-plane p-3 text-sm">
        <h4 class="mb-1.5 text-[0.7rem] font-medium tracking-wide text-muted uppercase">
          Correcciones de OCR aplicadas
        </h4>
        <ul class="list-disc pl-5 font-mono text-xs text-ink-2">
          {#each report.repairs as repair}
            <li>
              página {repair.page}: se leyó <b class="text-ink">{repair.observed}</b>, se mantuvo con
              <b class="text-ink">{repair.applied}</b>
              ({repair.distance} edición{repair.distance === 1 ? '' : 'es'})
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    {#if report.review_queue.length}
      <section class="mt-4 rounded-lg border-l-[3px] border-warning bg-plane p-3 text-sm">
        <h4 class="mb-1.5 text-[0.7rem] font-medium tracking-wide text-muted uppercase">
          Requiere revisión humana ({report.review_queue.length})
        </h4>
        <ul class="list-disc pl-5 text-ink-2">
          {#each report.review_queue as item}
            <li>página {item.page} — {item.reason}</li>
          {/each}
        </ul>
        {#if report.quarantine.length}
          <a
            class="mt-2 inline-block text-s1 hover:underline"
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
          <a class="text-s1 hover:underline" href={downloadUrl(job.id, 'inventory.csv')} download>
            CSV
          </a>
          <a class="text-s1 hover:underline" href={downloadUrl(job.id, 'inventory.json')} download>
            JSON
          </a>
        </span>
      </footer>
    {/if}
  {/if}
</article>

<style>
  @keyframes slide {
    from {
      transform: translateX(-100%);
    }
    to {
      transform: translateX(340%);
    }
  }
</style>
