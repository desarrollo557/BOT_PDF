<script lang="ts">
  import { formatBytes } from '$lib/format';

  /**
   * One processed document, however it is being remembered.
   *
   * Live jobs and ledger history used to render as two different things -- tiles
   * and a row of code chips -- so the same document looked like two kinds of
   * object depending on how recently it ran. One card for both, and the codes
   * are gone: a fistful of numbers with no room to say what they mean is noise,
   * and the "por resolución" grain already lists them properly.
   */
  export interface Entry {
    key: string;
    jobId: string;
    name: string;
    at: number;
    resolutions: number;
    pages: number;
    bytes: number;
    review: number;
    operator: string | null;
    /** The resolution numbers it produced. Searched, never drawn on the card. */
    codes: string[];
    failed: boolean;
    error: string | null;
    /** Whether the full report is still on screen, so it can be opened. */
    live: boolean;
  }

  interface Props {
    entry: Entry;
  }

  let { entry }: Props = $props();

  const clock = $derived(
    new Date(entry.at).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' })
  );
</script>

<svelte:element
  this={entry.live ? 'a' : 'div'}
  class="card"
  class:failed={entry.failed}
  class:openable={entry.live}
  href={entry.live ? `/documento/${entry.jobId}` : undefined}
>
  <span class="tab" aria-hidden="true"></span>

  <header>
    <span class="name" title={entry.name}>{entry.name}</span>
    <time class="tabular">{clock}</time>
  </header>

  {#if entry.failed}
    <p class="error" title={entry.error ?? ''}>{entry.error ?? 'No se pudo procesar'}</p>
  {:else}
    <!-- Two numbers, always in the same place, always meaning the same thing. -->
    <dl class="figures">
      <div>
        <dt>Resoluciones</dt>
        <dd class="tabular">{entry.resolutions}</dd>
      </div>
      <div>
        <dt>Páginas</dt>
        <dd class="tabular">{entry.pages || '—'}</dd>
      </div>
      <div>
        <dt>Tamaño</dt>
        <dd class="tabular">{entry.bytes ? formatBytes(entry.bytes) : '—'}</dd>
      </div>
    </dl>
  {/if}

  <footer>
    {#if entry.operator}
      <span class="by">{entry.operator}</span>
    {:else}
      <span class="by anon">sin operador</span>
    {/if}

    {#if entry.review}
      <span class="review" title={`${entry.review} páginas requieren revisión`}>
        ⚠ {entry.review}
      </span>
    {/if}

    {#if entry.live}
      <span class="open" aria-hidden="true">ver detalle →</span>
    {:else}
      <span class="archived">archivado</span>
    {/if}
  </footer>
</svelte:element>

<style>
  /* Drawn as a folder: a finished document is something you open, not a row you
     scroll past. */
  .card {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    border: 1px solid var(--hairline);
    border-radius: 4px 10px 10px 10px;
    background: var(--surface-2);
    padding: 0.8rem 0.9rem;
    box-shadow: var(--shadow);
    color: inherit;
    text-decoration: none;
    transition:
      border-color 0.15s,
      transform 0.15s,
      box-shadow 0.15s;
  }
  .card.openable:hover {
    border-color: var(--accent);
    transform: translateY(-1px);
    box-shadow: 0 8px 22px rgb(0 0 0 / 0.12);
  }

  .tab {
    position: absolute;
    top: -7px;
    left: -1px;
    width: 46px;
    height: 8px;
    border: 1px solid var(--hairline);
    border-bottom: 0;
    border-radius: 4px 6px 0 0;
    background: var(--surface-2);
  }
  .card.failed,
  .card.failed .tab {
    border-color: color-mix(in oklab, var(--critical) 40%, var(--hairline));
  }

  header {
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
  }
  .name {
    overflow: hidden;
    flex: 1;
    font-size: 0.86rem;
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  time {
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: 0.7rem;
    color: var(--axis);
  }

  .figures {
    display: flex;
    gap: 1.25rem;
    margin: 0;
  }
  .figures div {
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .figures dt {
    font-size: 0.58rem;
    font-weight: 600;
    letter-spacing: 0.055em;
    text-transform: uppercase;
    color: var(--muted);
  }
  .figures dd {
    margin: 0;
    font-family: var(--font-mono);
    font-size: 0.95rem;
    color: var(--ink);
  }

  .error {
    margin: 0;
    overflow: hidden;
    font-family: var(--font-mono);
    font-size: 0.7rem;
    color: var(--critical);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  footer {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    border-top: 1px solid var(--rule);
    padding-top: 0.5rem;
  }
  .by {
    overflow: hidden;
    max-width: 11rem;
    border-radius: 999px;
    background: var(--accent-soft);
    padding: 0 0.45rem;
    font-size: 0.66rem;
    color: var(--accent);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .by.anon {
    background: transparent;
    padding: 0;
    color: var(--muted);
  }

  .review {
    flex-shrink: 0;
    border-radius: 999px;
    background: color-mix(in oklab, var(--warning) 16%, transparent);
    padding: 0 0.4rem;
    font-family: var(--font-mono);
    font-size: 0.66rem;
    color: var(--warning);
  }

  .open,
  .archived {
    margin-left: auto;
    flex-shrink: 0;
    font-size: 0.7rem;
    color: var(--muted);
  }
  .card.openable:hover .open {
    color: var(--accent);
  }
</style>
