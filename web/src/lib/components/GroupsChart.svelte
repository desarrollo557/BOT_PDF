<script lang="ts">
  import type { Group } from '$lib/types';

  interface Props {
    groups: Group[];
    limit?: number;
  }

  let { groups, limit = 12 }: Props = $props();

  const ranked = $derived([...groups].sort((a, b) => b.size - a.size));
  const shown = $derived(ranked.slice(0, limit));
  const hidden = $derived(ranked.length - shown.length);
  const max = $derived(Math.max(1, ...shown.map((group) => group.size)));

  let hovered = $state<string | null>(null);
</script>

<figure class="m-0">
  <figcaption class="mb-2 text-[0.7rem] font-medium tracking-wide text-muted uppercase">
    Páginas por resolución
  </figcaption>

  <!-- One measure, one series: a single hue, no legend to look up. -->
  <ul class="flex flex-col gap-1.5">
    {#each shown as group (group.code)}
      <li
        class="grid grid-cols-[minmax(6rem,auto)_1fr_2.5rem] items-center gap-3 text-sm transition-opacity duration-150"
        style:opacity={hovered && hovered !== group.code ? 0.45 : 1}
        onmouseenter={() => (hovered = group.code)}
        onmouseleave={() => (hovered = null)}
        title={group.title ?? undefined}
      >
        <span class="truncate font-mono text-xs text-ink-2">{group.code}</span>
        <span class="h-2.5 rounded-r-[4px] bg-s1" style:width={`${(group.size / max) * 100}%`}
        ></span>
        <span class="text-right tabular-nums text-ink">{group.size}</span>
      </li>
    {/each}
  </ul>

  {#if hidden > 0}
    <!-- Never truncate silently: say what was left out of the plot. -->
    <p class="mt-2 text-xs text-muted">
      {hidden} resolución{hidden === 1 ? '' : 'es'} más sin graficar — están todas en la tabla.
    </p>
  {/if}
</figure>
