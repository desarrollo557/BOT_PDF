<script lang="ts">
  interface Props {
    onfiles: (files: File[]) => void;
    disabled?: boolean;
    /** Individual carries a light surface; batch reads as a machine intake. */
    variant?: 'single' | 'batch';
    limit?: number;
  }

  let { onfiles, disabled = false, variant = 'single', limit }: Props = $props();

  let hovering = $state(false);
  let rejected = $state(0);
  let input: HTMLInputElement;

  function accept(list: FileList | null) {
    if (!list || disabled) return;
    const all = Array.from(list);
    const pdfs = all.filter((file) => file.name.toLowerCase().endsWith('.pdf'));
    // Say what was dropped and ignored. Silently discarding files is how an
    // operator ends up believing a document was processed when it never was.
    rejected = all.length - pdfs.length;
    if (pdfs.length) onfiles(pdfs);
  }
</script>

<div
  class="zone"
  data-variant={variant}
  class:hovering
  class:disabled
  role="button"
  tabindex="0"
  ondragover={(event) => {
    event.preventDefault();
    hovering = true;
  }}
  ondragleave={() => (hovering = false)}
  ondrop={(event) => {
    event.preventDefault();
    hovering = false;
    accept(event.dataTransfer?.files ?? null);
  }}
  onclick={() => !disabled && input.click()}
  onkeydown={(event) => {
    if (event.key === 'Enter' || event.key === ' ') input.click();
  }}
>
  <span class="glyph" aria-hidden="true">
    {#if variant === 'batch'}
      <svg viewBox="0 0 24 24">
        <path d="M3 7.5 12 3l9 4.5-9 4.5-9-4.5Z" />
        <path class="soft" d="M3 12l9 4.5 9-4.5" />
        <path class="soft" d="M3 16.5 12 21l9-4.5" />
      </svg>
    {:else}
      <svg viewBox="0 0 24 24">
        <path d="M12 15.5V4.5M12 4.5 8 8.5M12 4.5l4 4" />
        <path class="soft" d="M4 15v3.5a1.5 1.5 0 0 0 1.5 1.5h13a1.5 1.5 0 0 0 1.5-1.5V15" />
      </svg>
    {/if}
  </span>

  {#if variant === 'batch'}
    <strong>Suelte el lote completo aquí</strong>
    <span class="hint">
      cincuenta o quinientos documentos, sin límite de tamaño &mdash; se procesan en paralelo y
      verá cuál se está leyendo en cada momento
    </span>
  {:else}
    <strong>Arrastre los PDF aquí</strong>
    <span class="hint">
      o haga clic para seleccionarlos{limit ? ` — hasta ${limit} documentos` : ''}
    </span>
  {/if}

  {#if rejected}
    <span class="rejected">
      Se ignoraron {rejected} archivo{rejected === 1 ? '' : 's'} que no son PDF
    </span>
  {/if}

  <input
    bind:this={input}
    type="file"
    accept="application/pdf"
    multiple
    hidden
    onchange={(event) => {
      accept(event.currentTarget.files);
      event.currentTarget.value = '';
    }}
  />
</div>

<style>
  .zone {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.3rem;
    overflow: hidden;
    border: 1px dashed var(--axis);
    border-radius: 14px;
    background: var(--surface-1);
    padding: 2.4rem 1.5rem;
    text-align: center;
    cursor: pointer;
    transition:
      border-color 0.18s,
      background 0.18s;
  }

  /* A faint diagonal hatch: enough texture to read as a drop target without
     turning into decoration that competes with the folders below it. */
  .zone::before {
    content: '';
    position: absolute;
    inset: 0;
    background: repeating-linear-gradient(45deg, var(--texture) 0 1px, transparent 1px 9px);
    opacity: 0.65;
    pointer-events: none;
  }

  .zone:hover,
  .zone.hovering {
    border-color: var(--accent);
    background: var(--accent-soft);
  }

  .zone.disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  /* Batch intake is deliberately a different object: taller, darker, ruled
     rather than hatched. You should be able to tell the two modes apart with
     the labels covered. */
  [data-variant='batch'] {
    border-style: solid;
    border-color: color-mix(in oklab, var(--s3) 35%, var(--hairline));
    background: var(--plane);
    padding: 3.1rem 1.5rem;
  }
  [data-variant='batch']::before {
    background: repeating-linear-gradient(
      to right,
      var(--texture) 0 1px,
      transparent 1px 14px
    );
    opacity: 1;
  }
  [data-variant='batch']:hover,
  [data-variant='batch'].hovering {
    border-color: var(--s3);
    background: color-mix(in oklab, var(--s3) 7%, var(--plane));
  }
  [data-variant='batch'] .glyph svg {
    stroke: color-mix(in oklab, var(--s3) 75%, var(--muted));
  }
  [data-variant='batch']:hover .glyph svg,
  [data-variant='batch'].hovering .glyph svg {
    stroke: var(--s3);
  }

  .glyph svg {
    width: 30px;
    height: 30px;
    margin-bottom: 0.4rem;
    fill: none;
    stroke: var(--muted);
    stroke-width: 1.6;
    stroke-linecap: round;
    stroke-linejoin: round;
    transition: stroke 0.18s;
  }
  .zone:hover .glyph svg,
  .zone.hovering .glyph svg {
    stroke: var(--accent);
  }
  .glyph .soft {
    opacity: 0.55;
  }

  strong {
    font-size: 0.95rem;
    font-weight: 600;
  }

  .hint {
    max-width: 46ch;
    font-size: 0.8rem;
    line-height: 1.45;
    color: var(--muted);
  }

  .rejected {
    margin-top: 0.35rem;
    font-size: 0.8rem;
    color: var(--warning);
  }
</style>
