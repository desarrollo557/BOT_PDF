<script lang="ts">
  interface Props {
    label: string;
    value: string | number;
    note?: string;
    tone?: 'neutral' | 'good' | 'warning';
  }

  let { label, value, note, tone = 'neutral' }: Props = $props();
</script>

<!-- Tone is carried by the value's ink, and the note always spells the meaning
     out in words, so nothing here depends on colour alone. -->
<div class="tile" data-tone={tone}>
  <span class="label">{label}</span>
  <span class="value tabular">{value}</span>
  {#if note}<span class="note">{note}</span>{/if}
</div>

<style>
  .tile {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    /* A hairline on the left instead of a box: at six tiles in a row, six boxes
       is six frames competing with the card that already holds them. */
    border-left: 2px solid var(--rule);
    padding-left: 0.75rem;
  }
  [data-tone='good'] {
    border-left-color: color-mix(in oklab, var(--good) 55%, transparent);
  }
  [data-tone='warning'] {
    border-left-color: color-mix(in oklab, var(--warning) 65%, transparent);
  }

  .label {
    font-size: 0.66rem;
    font-weight: 600;
    letter-spacing: 0.055em;
    text-transform: uppercase;
    color: var(--muted);
  }

  .value {
    font-size: 1.6rem;
    font-weight: 550;
    line-height: 1.15;
    letter-spacing: -0.02em;
  }
  [data-tone='good'] .value {
    color: var(--good);
  }
  [data-tone='warning'] .value {
    color: var(--warning);
  }

  .note {
    font-size: 0.74rem;
    color: var(--ink-2);
  }
</style>
