<script lang="ts">
  import { downloadUrl } from '$lib/api';
  import { jobStore } from '$lib/jobs.svelte';
  import { whereItLanded } from '$lib/revision';
  import type { Job } from '$lib/types';

  /**
   * The queue of what the machine refused to guess at.
   *
   * Every other screen answers "what did it do". This one answers "what needs
   * me", which for the person running the archive is the only question with a
   * deadline attached. Buried one document at a time it was invisible; gathered
   * here it is a morning's work with an end.
   */

  interface Item {
    job: Job;
    page: number;
    reason: string;
    family: string;
    /** El PDF en el que quedó archivada la página, si se llegó a escribir uno. */
    file: string | null;
    /** El número de la unidad documental que se llevó la página. */
    code: string | null;
  }


  /** Reasons collapse into families, because the fix differs by family. */
  const FAMILIES: { key: string; match: RegExp; label: string; advice: string }[] = [
    {
      key: 'sin-codigo',
      match: /sin código de resolución/i,
      label: 'Sin resolución antes de la página',
      advice:
        'Páginas que llegaron antes del primer encabezado. Están en el PDF de cuarentena del documento; hay que decidir a qué resolución pertenecen.'
    },
    {
      key: 'conflicto',
      match: /conflicto/i,
      label: 'Números en conflicto',
      advice:
        'La página tenía más de un número candidato y ninguno ganó con claridad. Suele ser una cita en el cuerpo compitiendo con el encabezado.'
    },
    {
      key: 'no-copiada',
      match: /no pudo copiarse/i,
      label: 'No se pudo copiar al PDF',
      advice:
        'El PDF de origen tiene objetos dañados en esa página. El resto del documento sí se escribió; esa página falta en su resolución.'
    },
    {
      key: 'no-procesada',
      match: /no pudo procesarse/i,
      label: 'No se pudo leer',
      advice: 'La página no se pudo abrir ni rasterizar. Suele necesitar volver a escanearse.'
    }
  ];

  function familyOf(reason: string): string {
    return FAMILIES.find((family) => family.match.test(reason))?.key ?? 'otro';
  }

  const items = $derived.by((): Item[] => {
    const out: Item[] = [];
    for (const job of jobStore.reviewable) {
      for (const entry of job.report?.review_queue ?? []) {
        out.push({
          job,
          page: entry.page,
          reason: entry.reason,
          family: familyOf(entry.reason),
          ...whereItLanded(job, entry.page)
        });
      }
    }
    return out;
  });

  let filter = $state<string>('todas');
  const shown = $derived(filter === 'todas' ? items : items.filter((i) => i.family === filter));

  const counts = $derived.by(() => {
    const tally: Record<string, number> = {};
    for (const item of items) tally[item.family] = (tally[item.family] ?? 0) + 1;
    return tally;
  });

  /** Grouped by document, because that is the unit somebody opens to fix it. */
  const byDocument = $derived.by(() => {
    const buckets = new Map<string, { job: Job; items: Item[] }>();
    for (const item of shown) {
      let bucket = buckets.get(item.job.id);
      if (!bucket) buckets.set(item.job.id, (bucket = { job: item.job, items: [] }));
      bucket.items.push(item);
    }
    for (const bucket of buckets.values()) bucket.items.sort((a, b) => a.page - b.page);
    return [...buckets.values()];
  });

  const failedDocuments = $derived(jobStore.reviewable.filter((job) => job.state === 'failed'));

</script>

<header class="head">
  <div>
    <h2>Revisión</h2>
    <p>
      Lo que el separador no quiso adivinar. Nada de esto es un error del programa: son páginas
      donde la evidencia no alcanzó, y adivinar habría metido páginas ajenas en una resolución
      real sin que nadie se enterara. Una página sin encabezado no aparece aquí: es la vuelta de
      un folio o un anexo, y su sitio es el PDF de la resolución que venía abierta.
    </p>
  </div>
</header>

{#if failedDocuments.length}
  <section class="failed">
    <h3 class="band">Documentos que no se pudieron procesar ({failedDocuments.length})</h3>
    <ul>
      {#each failedDocuments as job (job.id)}
        <li>
          <a href={`/documento/${job.id}`}>{job.filename}</a>
          <code>{job.error}</code>
        </li>
      {/each}
    </ul>
  </section>
{/if}

{#if !items.length}
  <div class="clear">
    <span class="tick" aria-hidden="true">✓</span>
    <div>
      <p><b>No hay nada pendiente de revisión.</b></p>
      <p class="muted">
        {jobStore.reviewable.length
          ? `Los ${jobStore.finished.length} documentos en pantalla se resolvieron enteros.`
          : 'Todavía no se procesó ningún documento en esta sesión.'}
      </p>
    </div>
  </div>
{:else}
  <div class="filters" role="tablist" aria-label="Motivo">
    <button
      role="tab"
      aria-selected={filter === 'todas'}
      class:current={filter === 'todas'}
      onclick={() => (filter = 'todas')}
    >
      Todas <b class="tabular">{items.length}</b>
    </button>
    {#each FAMILIES as family (family.key)}
      {#if counts[family.key]}
        <button
          role="tab"
          aria-selected={filter === family.key}
          class:current={filter === family.key}
          onclick={() => (filter = family.key)}
        >
          {family.label} <b class="tabular">{counts[family.key]}</b>
        </button>
      {/if}
    {/each}
  </div>

  {#if filter !== 'todas'}
    {@const family = FAMILIES.find((f) => f.key === filter)}
    {#if family}
      <p class="advice">{family.advice}</p>
    {/if}
  {/if}

  <div class="documents">
    {#each byDocument as bucket (bucket.job.id)}
      <article>
        <header class="doc">
          <a class="name" href={`/documento/${bucket.job.id}`} title={bucket.job.filename}>
            {bucket.job.filename}
          </a>
          <!-- El total del documento, no el del filtro: es un hecho del PDF y
               tiene que decir lo mismo se esté mirando el motivo que se esté. -->
          <span class="count tabular">
            {bucket.job.report?.review_queue?.length ?? bucket.items.length} de {bucket.job
              .report?.page_count ?? '?'} páginas
          </span>
          {#if bucket.job.report?.quarantine?.length}
            <a class="quarantine" href={downloadUrl(bucket.job.id, '_quarantine.pdf')} download>
              cuarentena ({bucket.job.report.quarantine?.length})
            </a>
          {/if}
        </header>

        <ul class="reasons">
          {#each bucket.items as item, index (`${item.page}-${index}`)}
            <li>
              <span class="page-no tabular">pág. {item.page}</span>
              <span class="detail">
                <span class="why">{item.reason}</span>
                {#if item.file}
                  <a class="landed" href={downloadUrl(item.job.id, item.file)} download>
                    quedó en {item.file}
                  </a>
                {:else if item.code}
                  <span class="landed">quedó en {item.code}</span>
                {/if}
              </span>
            </li>
          {/each}
        </ul>
      </article>
    {/each}
  </div>
{/if}

<style>
  .head {
    margin-bottom: 1.25rem;
  }
  .head h2 {
    margin: 0;
    font-size: 1.25rem;
    font-weight: 650;
    letter-spacing: -0.015em;
  }
  .head p {
    margin: 0.3rem 0 0;
    max-width: 68ch;
    font-size: 0.85rem;
    line-height: 1.55;
    color: var(--ink-2);
  }

  .band {
    margin: 0 0 0.6rem;
    border-bottom: 1px solid var(--rule);
    padding-bottom: 0.4rem;
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.055em;
    text-transform: uppercase;
    color: var(--muted);
  }

  .failed {
    margin-bottom: 1.5rem;
  }
  .failed ul {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .failed li {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.6rem;
    border-left: 2px solid var(--critical);
    padding-left: 0.7rem;
  }
  .failed a {
    font-size: 0.86rem;
    font-weight: 600;
    color: var(--critical);
  }
  .failed code {
    overflow: hidden;
    font-family: var(--font-mono);
    font-size: 0.72rem;
    color: var(--muted);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .clear {
    display: flex;
    align-items: center;
    gap: 1rem;
    border: 1px solid color-mix(in oklab, var(--good) 30%, var(--hairline));
    border-radius: 14px;
    background: var(--surface-2);
    padding: 1.5rem;
    box-shadow: var(--shadow);
  }
  .tick {
    display: grid;
    width: 34px;
    height: 34px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 50%;
    background: color-mix(in oklab, var(--good) 14%, transparent);
    font-size: 1rem;
    color: var(--good);
  }
  .clear p {
    margin: 0;
    font-size: 0.9rem;
  }
  .clear .muted {
    margin-top: 0.15rem;
    font-size: 0.82rem;
    color: var(--muted);
  }

  .filters {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-bottom: 0.9rem;
  }
  .filters button {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    border: 1px solid var(--hairline);
    border-radius: 999px;
    background: var(--surface-2);
    padding: 0.3rem 0.75rem;
    font: inherit;
    font-size: 0.8rem;
    color: var(--muted);
    cursor: pointer;
    transition:
      border-color 0.15s,
      color 0.15s;
  }
  .filters button:hover {
    color: var(--ink-2);
  }
  .filters button.current {
    border-color: var(--warning);
    color: var(--ink);
  }
  .filters b {
    font-family: var(--font-mono);
    font-size: 0.74rem;
    font-weight: 600;
    color: var(--warning);
  }

  .advice {
    margin: 0 0 1rem;
    max-width: 72ch;
    border-left: 2px solid var(--warning);
    padding-left: 0.75rem;
    font-size: 0.83rem;
    line-height: 1.5;
    color: var(--ink-2);
  }

  .documents {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(23rem, 1fr));
    gap: 0.8rem;
  }
  article {
    border: 1px solid var(--hairline);
    border-radius: 12px;
    background: var(--surface-2);
    padding: 0.85rem 1rem;
    box-shadow: var(--shadow);
  }

  .doc {
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
    border-bottom: 1px solid var(--rule);
    padding-bottom: 0.5rem;
  }
  .doc .name {
    overflow: hidden;
    flex: 1;
    font-size: 0.87rem;
    font-weight: 600;
    color: inherit;
    text-decoration: none;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .doc .name:hover {
    color: var(--accent);
  }
  .count {
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: 0.72rem;
    color: var(--warning);
  }
  .quarantine {
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: 0.7rem;
    color: var(--accent);
    text-decoration: none;
  }
  .quarantine:hover {
    text-decoration: underline;
  }

  .reasons {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    margin: 0.6rem 0 0;
    padding: 0;
    list-style: none;
  }
  .reasons li {
    display: grid;
    align-items: baseline;
    gap: 0 0.6rem;
    grid-template-columns: 4.4rem 1fr;
    padding-bottom: 0.3rem;
    border-bottom: 1px solid var(--rule);
    font-size: 0.8rem;
  }
  .reasons li:last-child {
    padding-bottom: 0;
    border-bottom: none;
  }
  .page-no {
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: 0.74rem;
    font-weight: 600;
    color: var(--warning);
  }
  .detail {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    min-width: 0;
  }
  .why {
    color: var(--ink-2);
    line-height: 1.4;
  }
  .landed {
    overflow: hidden;
    font-family: var(--font-mono);
    font-size: 0.7rem;
    color: var(--accent);
    text-decoration: none;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  a.landed:hover {
    text-decoration: underline;
  }
</style>
