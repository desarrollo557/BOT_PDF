<script lang="ts">
  import type { Snippet } from 'svelte';

  /**
   * A short message tied to the step it sits in: a block, a missing key, a
   * recommendation. The tone sets the left rule and the icon; the text stays
   * in the body colour so it is read, not just noticed.
   */
  interface Props {
    tone?: 'info' | 'warning' | 'critical';
    children: Snippet;
  }

  let { tone = 'info', children }: Props = $props();
</script>

<div class="callout" data-tone={tone} role={tone === 'critical' ? 'alert' : 'status'}>
  <svg viewBox="0 0 16 16" aria-hidden="true">
    {#if tone === 'info'}
      <circle cx="8" cy="8" r="6.25" />
      <path d="M8 7.25v4M8 4.9v.1" />
    {:else}
      <path d="M8 2.2 14.3 13H1.7Z" />
      <path d="M8 6.5v3M8 11.2v.1" />
    {/if}
  </svg>
  <div class="text">{@render children()}</div>
</div>

<style>
  .callout {
    display: flex;
    align-items: flex-start;
    gap: var(--space-2);
    border: 1px solid var(--hairline);
    border-left: 3px solid var(--accent);
    border-radius: var(--radius);
    background: var(--surface-1);
    padding: var(--space-3) var(--space-4);
    font-size: var(--text-sm);
    line-height: 1.5;
    color: var(--ink-2);
  }

  .callout[data-tone='warning'] {
    border-left-color: var(--warning);
    background: color-mix(in oklab, var(--warning) 6%, var(--surface-2));
  }

  .callout[data-tone='critical'] {
    border-left-color: var(--critical);
    background: color-mix(in oklab, var(--critical) 6%, var(--surface-2));
  }

  svg {
    width: 16px;
    height: 16px;
    flex-shrink: 0;
    margin-top: 2px;
    fill: none;
    stroke: var(--accent);
    stroke-width: 1.5;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  [data-tone='warning'] svg {
    stroke: color-mix(in oklab, var(--warning) 70%, var(--ink));
  }

  [data-tone='critical'] svg {
    stroke: var(--critical);
  }

  .text {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-1) var(--space-3);
  }

  .text :global(button) {
    border: 0;
    background: none;
    padding: 0;
    font: inherit;
    font-weight: 600;
    color: var(--accent);
    text-decoration: underline;
    text-underline-offset: 2px;
    cursor: pointer;
  }
</style>
