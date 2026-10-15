<script lang="ts">
  import { downloadUrl } from '$lib/api';
  import EncabezadoDePagina from '$lib/components/EncabezadoDePagina.svelte';
  import Icono from '$lib/components/Icono.svelte';
  import { jobStore } from '$lib/jobs.svelte';
  import { whereItLanded } from '$lib/revision';
  import { enlaceAlDocumento } from '$lib/navegacion.svelte';
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

<EncabezadoDePagina
  titulo="Revisión"
  descripcion="Lo que el separador no quiso adivinar. Nada de esto es un error del programa: son páginas donde la evidencia no alcanzó, y adivinar habría metido páginas ajenas en una resolución real sin que nadie se enterara. Una página sin encabezado no aparece aquí: es la vuelta de un folio o un anexo, y su sitio es el PDF de la resolución que venía abierta."
/>

{#if failedDocuments.length}
  <section class="failed">
    <h2 class="caps band">
      Documentos que no se pudieron procesar (<span class="tabular">{failedDocuments.length}</span>)
    </h2>
    <ul>
      {#each failedDocuments as job (job.id)}
        <li>
          <a href={enlaceAlDocumento(job.id, 'revision')}>{job.filename}</a>
          <span class="motivo">{job.error}</span>
        </li>
      {/each}
    </ul>
  </section>
{/if}

{#if !items.length}
  <div class="empty-state">
    <strong>No hay nada pendiente de revisión.</strong>
    {jobStore.reviewable.length
      ? `Los ${jobStore.finished.length} documentos en pantalla se resolvieron enteros.`
      : 'Todavía no se procesó ningún documento en esta sesión.'}
  </div>
{:else}
  <!-- Los filtros por motivo son el control segmentado común: el elegido lo
       marca `aria-selected`, que es lo que la clase ya sabe pintar. -->
  <div class="segmented filters" role="tablist" aria-label="Motivo">
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
      <article class="panel">
        <header class="doc">
          <a
            class="name"
            href={enlaceAlDocumento(bucket.job.id, 'revision')}
            title={bucket.job.filename}
          >
            {bucket.job.filename}
          </a>
          <!-- El total del documento, no el del filtro: es un hecho del PDF y
               tiene que decir lo mismo se esté mirando el motivo que se esté. -->
          <span class="pill pill-warn tabular count">
            {bucket.job.report?.review_queue?.length ?? bucket.items.length} de {bucket.job
              .report?.page_count ?? '?'} páginas
          </span>
          {#if bucket.job.report?.quarantine?.length}
            <a
              class="btn btn-tonal btn-sm"
              href={downloadUrl(bucket.job.id, '_quarantine.pdf')}
              download
              title={`${bucket.job.report.quarantine?.length} páginas en cuarentena`}
            >
              <Icono nombre="descargar" />
              Descargar cuarentena (PDF)
            </a>
          {/if}
        </header>

        <ul class="reasons">
          {#each bucket.items as item, index (`${item.page}-${index}`)}
            <li>
              <span class="page-no tabular">Pág. {item.page}</span>
              <span class="detail">
                <span class="why">{item.reason}</span>
                {#if item.file}
                  <a class="landed" href={downloadUrl(item.job.id, item.file)} download>
                    Quedó en {item.file}
                  </a>
                {:else if item.code}
                  <span class="landed">Quedó en {item.code}</span>
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
  .band {
    margin: 0 0 0.6rem;
    border-bottom: 1px solid var(--rule);
    padding-bottom: 0.4rem;
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
    font-size: var(--text-md);
    font-weight: 600;
    color: var(--critical);
  }
  /* El motivo del fallo, apagado y en una línea: el documento es lo que se
     busca; el porqué se lee al abrirlo. */
  .motivo {
    overflow: hidden;
    font-size: var(--text-xs);
    color: var(--muted);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .filters {
    margin-bottom: 0.9rem;
  }
  .filters button {
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }
  .filters b {
    font-size: var(--text-xs);
    font-weight: 600;
    color: var(--warning-ink);
  }

  .advice {
    margin: 0 0 1rem;
    max-width: 72ch;
    border-left: 2px solid var(--warning);
    padding-left: 0.75rem;
    font-size: var(--text-md);
    line-height: 1.5;
    color: var(--ink-2);
  }

  .documents {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(23rem, 1fr));
    gap: 0.8rem;
  }
  .doc {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem 0.6rem;
    border-bottom: 1px solid var(--rule);
    padding-bottom: 0.5rem;
  }
  .doc .name {
    overflow: hidden;
    flex: 1;
    min-width: 8rem;
    font-size: var(--text-md);
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
    font-size: var(--text-sm);
  }
  .reasons li:last-child {
    padding-bottom: 0;
    border-bottom: none;
  }
  .page-no {
    flex-shrink: 0;
    font-size: var(--text-xs);
    font-weight: 600;
    color: var(--warning-ink);
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
    font-size: var(--text-xs);
    color: var(--accent);
    text-decoration: none;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  a.landed:hover {
    text-decoration: underline;
  }
</style>
