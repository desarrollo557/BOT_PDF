<script lang="ts">
  import { onMount } from 'svelte';
  import { createBatch, listJobs, streamJobs, uploadDocument, withConcurrency } from '$lib/api';
  import BatchCard from '$lib/components/BatchCard.svelte';
  import Dropzone from '$lib/components/Dropzone.svelte';
  import JobCard from '$lib/components/JobCard.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import type { Job } from '$lib/types';

  /**
   * Uploads in flight at once. Fifty parallel transfers of a few hundred
   * megabytes each only starve one another; a small window keeps every one of
   * them moving and the queue filling steadily.
   */
  const UPLOAD_CONCURRENCY = 3;

  let jobs = $state<Job[]>([]);
  let batchNames = $state<Record<string, string>>({});
  let uploaded = $state(0);
  let uploadTotal = $state(0);
  let errors = $state<string[]>([]);

  const uploading = $derived(uploadTotal > 0 && uploaded < uploadTotal);
  const active = $derived(
    jobs.filter((job) => job.state === 'queued' || job.state === 'running').length
  );
  const pagesDone = $derived(jobs.reduce((sum, job) => sum + job.progress.pages_done, 0));
  const rate = $derived(
    jobs
      .filter((job) => job.state === 'running')
      .reduce((sum, job) => sum + job.progress.pages_per_second, 0)
  );

  /** Jobs grouped by batch, newest batch first, loose jobs last. */
  const groupedJobs = $derived.by(() => {
    const buckets = new Map<string, Job[]>();
    for (const job of jobs) {
      const key = job.batch_id ?? '';
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key)!.push(job);
    }
    return [...buckets.entries()];
  });

  function upsert(incoming: Job) {
    const index = jobs.findIndex((job) => job.id === incoming.id);
    if (index === -1) jobs = [incoming, ...jobs];
    else jobs[index] = incoming;
  }

  onMount(() => {
    listJobs().then((initial) => (jobs = initial));
    // The stream replays current state on connect, so a reconnect after a dropped
    // socket resynchronises without any extra request.
    return streamJobs(upsert);
  });

  async function handle(files: File[]) {
    errors = [];
    uploaded = 0;
    uploadTotal = files.length;

    let batchId: string | undefined;
    const name = `Lote de ${files.length} documento${files.length === 1 ? '' : 's'}`;
    try {
      batchId = (await createBatch(name)).id;
      batchNames = { ...batchNames, [batchId]: name };
    } catch (error) {
      // A batch is a label, not a prerequisite. If it fails, the documents still
      // get processed; they just show up ungrouped.
      errors = [...errors, `No se pudo abrir el lote: ${(error as Error).message}`];
    }

    await withConcurrency(files, UPLOAD_CONCURRENCY, async (file) => {
      try {
        await uploadDocument(file, batchId);
      } catch (error) {
        errors = [...errors, `${file.name}: ${(error as Error).message}`];
      } finally {
        uploaded += 1;
      }
    });
  }
</script>

<Dropzone onfiles={handle} disabled={uploading} />

{#if uploading}
  <div class="mt-4">
    <div class="h-1.5 overflow-hidden rounded bg-grid">
      <div
        class="h-full rounded-r-[4px] bg-s1 transition-[width] duration-200"
        style:width={`${(uploaded / uploadTotal) * 100}%`}
      ></div>
    </div>
    <p class="mt-2 text-sm text-muted">Subiendo {uploaded} de {uploadTotal} archivos…</p>
  </div>
{/if}

{#each errors as message}
  <p class="mt-3 text-sm text-critical">{message}</p>
{/each}

{#if jobs.length}
  <section class="mt-8 flex flex-wrap gap-8 rounded-xl border border-hairline bg-surface p-5">
    <StatTile label="Documentos" value={jobs.length} note={`${active} en curso`} />
    <StatTile label="Páginas leídas" value={pagesDone} />
    <StatTile
      label="Velocidad total"
      value={rate ? `${rate.toFixed(1)} p/s` : '—'}
      note="páginas por segundo"
    />
  </section>

  {#each groupedJobs as [batchId, batchJobs] (batchId)}
    {#if batchId}
      <div class="mt-8">
        <BatchCard
          name={batchNames[batchId] ?? `Lote de ${batchJobs.length} documentos`}
          jobs={batchJobs}
        />
      </div>
    {:else}
      <h2 class="mt-8 mb-4 text-lg font-semibold">Documentos sueltos</h2>
    {/if}

    {#each batchJobs as job (job.id)}
      <JobCard {job} />
    {/each}
  {/each}
{:else}
  <p class="mt-6 text-sm text-muted">Todavía no se procesó ningún documento.</p>
{/if}
