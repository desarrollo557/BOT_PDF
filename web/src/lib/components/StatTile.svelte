<script lang="ts">
  interface Props {
    label: string;
    value: string | number;
    note?: string;
    tone?: 'neutral' | 'good' | 'warning';
  }

  let { label, value, note, tone = 'neutral' }: Props = $props();

  // Tone is carried by the value's ink, and the note always spells the meaning
  // out in words, so nothing here depends on colour alone.
  const toneClass = $derived(
    { neutral: 'text-ink', good: 'text-good', warning: 'text-warning' }[tone]
  );
</script>

<div class="flex flex-col gap-0.5">
  <span class="text-[0.7rem] font-medium tracking-wide text-muted uppercase">{label}</span>
  <span class="text-2xl leading-none {toneClass}">{value}</span>
  {#if note}
    <span class="text-xs text-ink-2">{note}</span>
  {/if}
</div>
