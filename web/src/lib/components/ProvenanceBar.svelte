<script lang="ts">
  import { RUNGS, UNREADABLE } from '$lib/rungs';
  import type { Stats } from '$lib/types';

  interface Props {
    stats: Stats;
    pageCount: number;
  }

  let { stats, pageCount }: Props = $props();

  const segments = $derived(
    [...RUNGS, UNREADABLE]
      .map((rung) => ({ ...rung, value: stats.by_provenance[rung.key] ?? 0 }))
      .filter((segment) => segment.value > 0)
  );

  const total = $derived(
    segments.reduce((sum, segment) => sum + segment.value, 0) || pageCount || 1
  );

  let hovered = $state<string | null>(null);
</script>

<figure class="m-0">
  <figcaption class="mb-2 text-[0.7rem] font-medium tracking-wide text-muted uppercase">
    Dónde se resolvió cada página
  </figcaption>

  <!-- 2px surface gaps between segments keep adjacent hues from touching. -->
  <div
    class="flex h-3.5 w-full gap-[2px] overflow-hidden rounded bg-surface"
    role="img"
    aria-label={segments.map((s) => `${s.label}: ${s.value} páginas`).join(', ')}
  >
    {#each segments as segment (segment.key)}
      <div
        class="h-full transition-opacity duration-150"
        style:width={`${(segment.value / total) * 100}%`}
        style:background={segment.color}
        style:opacity={hovered && hovered !== segment.key ? 0.35 : 1}
        onmouseenter={() => (hovered = segment.key)}
        onmouseleave={() => (hovered = null)}
        role="presentation"
      ></div>
    {/each}
  </div>

  <!--
    Legend with direct labels and counts. Two of the light-mode hues sit below
    3:1 on the surface, so this relief is required, not decorative.
  -->
  <ul class="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-sm">
    {#each segments as segment (segment.key)}
      <li
        class="flex items-center gap-2 transition-opacity duration-150"
        style:opacity={hovered && hovered !== segment.key ? 0.45 : 1}
        onmouseenter={() => (hovered = segment.key)}
        onmouseleave={() => (hovered = null)}
      >
        <span class="size-2 shrink-0 rounded-[2px]" style:background={segment.color}></span>
        <span class="text-ink-2">{segment.label}</span>
        <span class="tabular-nums text-ink">{segment.value}</span>
        <span class="text-xs text-muted">{((segment.value / total) * 100).toFixed(1)}%</span>
      </li>
    {/each}
  </ul>

  {#if hovered}
    <p class="mt-2 text-xs text-muted">
      {[...RUNGS, UNREADABLE].find((rung) => rung.key === hovered)?.hint}
    </p>
  {/if}
</figure>
