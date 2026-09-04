<script lang="ts">
  import StatTile from '$lib/components/StatTile.svelte';
  import type { Job } from '$lib/types';

  interface Props {
    name: string;
    jobs: Job[];
  }

  let { name, jobs }: Props = $props();

  const counts = $derived({
    done: jobs.filter((job) => job.state === 'done').length,
    failed: jobs.filter((job) => job.state === 'failed').length,
    running: jobs.filter((job) => job.state === 'running').length,
    queued: jobs.filter((job) => job.state === 'queued').length
  });

  const pagesTotal = $derived(jobs.reduce((sum, job) => sum + job.progress.page_count, 0));
  const pagesDone = $derived(jobs.reduce((sum, job) => sum + job.progress.pages_done, 0));
  const percent = $derived(pagesTotal ? (100 * pagesDone) / pagesTotal : 0);

  const rate = $derived(
    jobs
      .filter((job) => job.state === 'running')
      .reduce((sum, job) => sum + job.progress.pages_per_second, 0)
  );

  const resolutions = $derived(
    jobs.reduce((sum, job) => sum + (job.report?.groups?.length ?? 0), 0)
  );
  const review = $derived(
    jobs.reduce((sum, job) => sum + (job.report?.review_queue?.length ?? 0), 0)
  );

  /** Rough time left, from the throughput actually being achieved right now. */
  const eta = $derived.by(() => {
    if (!rate || pagesDone >= pagesTotal) return null;
    const seconds = Math.round((pagesTotal - pagesDone) / rate);
    if (seconds < 60) return `${seconds} s`;
    return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
  });
</script>

<article class="mb-5 rounded-xl border border-hairline bg-raised shadow-[var(--shadow)] p-5">
  <header class="flex flex-wrap items-baseline justify-between gap-3">
    <h3 class="text-base font-semibold">{name}</h3>
    <span class="text-sm text-muted">
      {counts.done + counts.failed} de {jobs.length} documentos
      {#if eta}· quedan ~{eta}{/if}
    </span>
  </header>

  <!-- One measure, one bar: pages read out of pages known. -->
  <div class="mt-3 h-2 overflow-hidden rounded bg-grid">
    <div
      class="h-full rounded-r-[4px] bg-accent transition-[width] duration-300"
      style:width={`${percent}%`}
    ></div>
  </div>

  <div class="mt-4 flex flex-wrap gap-7">
    <StatTile label="Páginas" value={`${pagesDone} / ${pagesTotal}`} />
    <StatTile label="Velocidad" value={rate ? `${rate.toFixed(1)} p/s` : '—'} note="páginas por segundo" />
    <StatTile label="Procesando" value={counts.running} note={`${counts.queued} en cola`} />
    <StatTile label="Resoluciones" value={resolutions} />
    <StatTile
      label="Requiere revisión"
      value={review}
      tone={review ? 'warning' : 'good'}
      note={review ? 'ver detalle abajo' : 'sin pendientes'}
    />
    <StatTile
      label="Fallaron"
      value={counts.failed}
      tone={counts.failed ? 'warning' : 'good'}
      note={counts.failed ? 'el resto del lote siguió' : 'ningún documento'}
    />
  </div>
</article>
