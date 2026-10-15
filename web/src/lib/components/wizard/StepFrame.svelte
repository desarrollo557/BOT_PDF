<script lang="ts">
  import type { Snippet } from 'svelte';

  /**
   * The shell every wizard step shares: a numbered eyebrow, a title, an
   * optional lead paragraph, the step body and an optional closing note.
   *
   * Keeping it in one place is what makes the seven steps read as one form
   * instead of seven screens that happen to sit next to each other.
   */
  interface Props {
    number: number;
    title: string;
    description?: string;
    /** A short closing remark: what this choice does not change, or costs. */
    note?: string | null;
    children: Snippet;
  }

  let { number, title, description, note = null, children }: Props = $props();
</script>

<fieldset class="step">
  <legend>
    <span class="eyebrow">Paso {number}</span>
    <span class="title">{title}</span>
  </legend>

  {#if description}
    <p class="description">{description}</p>
  {/if}

  <div class="body">
    {@render children()}
  </div>

  {#if note}
    <p class="note">{note}</p>
  {/if}
</fieldset>

<style>
  .step {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: var(--space-3);
    margin: 0;
    border: 0;
    padding: 0;
  }

  /* «Paso 1» y el título en un solo renglón: apilados gastaban una línea
     entera de alto en cada paso. */
  legend {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-1) var(--space-3);
    margin-bottom: var(--space-2);
    padding: 0;
  }

  .eyebrow {
    font-size: var(--text-xs);
    font-weight: 600;
    letter-spacing: var(--tracking-caps);
    text-transform: uppercase;
    color: var(--accent);
  }

  .title {
    font-size: var(--text-xl);
    font-weight: 650;
    letter-spacing: -0.01em;
    color: var(--ink);
  }

  .description {
    max-width: 44rem;
    margin: calc(var(--space-1) * -1) 0 0;
    font-size: var(--text-sm);
    line-height: 1.55;
    color: var(--ink-2);
  }

  .body {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: var(--space-3);
  }

  .note {
    margin: 0;
    font-size: var(--text-xs);
    line-height: 1.5;
    color: var(--muted);
  }
</style>
