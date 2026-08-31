<script lang="ts">
  import { PENDING_COLOR, RUNGS, UNREADABLE, colorForMark, rungForMark } from '$lib/rungs';

  interface Props {
    /** One character per page, straight from the server. */
    ribbon: string;
    pageCount: number;
  }

  let { ribbon, pageCount }: Props = $props();

  /**
   * Cap the number of drawn cells.
   *
   * A 400-page document is 400 nodes; fifty of them at once is twenty thousand,
   * and the browser starts dropping frames exactly when the live view matters
   * most. Past the cap each cell stands for a run of pages, and the caption says
   * so rather than pretending it is page-per-cell.
   */
  const MAX_CELLS = 240;

  interface Cell {
    mark: string;
    from: number;
    to: number;
  }

  const perCell = $derived(Math.max(1, Math.ceil((pageCount || ribbon.length) / MAX_CELLS)));

  const cells = $derived.by((): Cell[] => {
    const marks = ribbon.padEnd(pageCount, '.');
    const out: Cell[] = [];
    for (let start = 0; start < marks.length; start += perCell) {
      const slice = marks.slice(start, start + perCell);
      out.push({ mark: dominant(slice), from: start + 1, to: Math.min(start + perCell, marks.length) });
    }
    return out;
  });

  /** An unreadable page inside a run always wins: a problem must never hide. */
  function dominant(slice: string): string {
    if (slice.includes(UNREADABLE.mark)) return UNREADABLE.mark;
    const tally = new Map<string, number>();
    for (const mark of slice) tally.set(mark, (tally.get(mark) ?? 0) + 1);
    let best = '.';
    let bestCount = 0;
    for (const [mark, count] of tally) {
      if (mark !== '.' && count > bestCount) {
        best = mark;
        bestCount = count;
      }
    }
    return bestCount ? best : '.';
  }

  let hovered = $state<Cell | null>(null);

  const legend = $derived(
    [...RUNGS, UNREADABLE].filter((rung) => ribbon.includes(rung.mark))
  );
  const pending = $derived(ribbon.split('').filter((mark) => mark === '.').length);
</script>

<figure class="m-0">
  <figcaption class="mb-1.5 flex items-baseline justify-between gap-3">
    <span class="text-[0.7rem] font-medium tracking-wide text-muted uppercase">
      Páginas en vivo
    </span>
    <span class="text-xs text-muted">
      {#if hovered}
        {hovered.from === hovered.to
          ? `Página ${hovered.from}`
          : `Páginas ${hovered.from}–${hovered.to}`} ·
        {rungForMark(hovered.mark)?.label ?? 'Sin leer todavía'}
      {:else if perCell > 1}
        cada celda agrupa {perCell} páginas
      {:else}
        una celda por página
      {/if}
    </span>
  </figcaption>

  <div
    class="flex flex-wrap gap-[2px]"
    role="img"
    aria-label={`${pageCount - pending} de ${pageCount} páginas leídas`}
  >
    {#each cells as cell, index (index)}
      <span
        class="h-2.5 w-2.5 rounded-[2px] transition-colors duration-200"
        style:background={colorForMark(cell.mark)}
        style:opacity={cell.mark === '.' ? 0.5 : 1}
        onmouseenter={() => (hovered = cell)}
        onmouseleave={() => (hovered = null)}
        role="presentation"
      ></span>
    {/each}
  </div>

  {#if legend.length}
    <ul class="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-xs">
      {#each legend as rung (rung.key)}
        <li class="flex items-center gap-1.5">
          <span class="size-2 shrink-0 rounded-[2px]" style:background={rung.color}></span>
          <span class="text-ink-2">{rung.label}</span>
        </li>
      {/each}
      {#if pending}
        <li class="flex items-center gap-1.5">
          <span
            class="size-2 shrink-0 rounded-[2px] opacity-50"
            style:background={PENDING_COLOR}
          ></span>
          <span class="text-muted">Sin leer ({pending})</span>
        </li>
      {/if}
    </ul>
  {/if}
</figure>
