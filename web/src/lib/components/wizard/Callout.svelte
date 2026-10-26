<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icono from '../Icono.svelte';

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
  <span class="glifo"><Icono nombre={tone === 'info' ? 'info' : 'aviso'} /></span>
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

  /* El ícono del tono, del juego común ([Icono]): información o aviso. */
  .glifo {
    --icono: 16px;
    display: grid;
    flex-shrink: 0;
    margin-top: 2px;
    color: var(--accent);
  }

  [data-tone='warning'] .glifo {
    color: var(--warning-ink);
  }

  [data-tone='critical'] .glifo {
    color: var(--critical);
  }

  .text {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-1) var(--space-3);
  }

  /* Un botón suelto dentro del aviso se lee como enlace. Los `.btn` no: son
     botones de verdad («Usar «…»» en la sugerencia de tipo), y esta regla les
     quitaba el borde y el fondo. */
  .text :global(button:not(.btn)) {
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
