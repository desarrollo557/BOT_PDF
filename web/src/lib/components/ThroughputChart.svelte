<script lang="ts">
  import { onMount } from 'svelte';

  interface Props {
    /** Pages per second right now. Sampled on a clock, not per frame. */
    rate: number;
    /** Stop sampling once the work is over, so the trace freezes as a record. */
    live?: boolean;
    /** Series colour. One hue: this chart never carries a second series. */
    color?: string;
    label?: string;
  }

  let { rate, live = true, color = 'var(--s1)', label = 'Páginas por segundo' }: Props = $props();

  /**
   * One sample a second, for four minutes.
   *
   * Sampling on a clock rather than on every frame keeps the x axis honest --
   * frames arrive four times a second and pause when nothing changes, so a
   * point-per-frame trace would compress and stretch time silently.
   */
  const INTERVAL_MS = 1000;
  const CAPACITY = 240;

  const WIDTH = 560;
  const HEIGHT = 108;
  const PAD = { top: 10, right: 8, bottom: 4, left: 30 };

  let samples = $state<{ t: number; value: number }[]>([]);
  let hovered = $state<number | null>(null);

  onMount(() => {
    const tick = setInterval(() => {
      if (!live) return;
      const next = [...samples, { t: Date.now(), value: Math.max(0, rate) }];
      samples = next.length > CAPACITY ? next.slice(-CAPACITY) : next;
    }, INTERVAL_MS);
    return () => clearInterval(tick);
  });

  const peak = $derived(samples.reduce((top, point) => Math.max(top, point.value), 0));
  const mean = $derived(
    samples.length ? samples.reduce((sum, point) => sum + point.value, 0) / samples.length : 0
  );

  /** The y ceiling, rounded up so the axis label is a number a human would say. */
  const ceiling = $derived.by(() => {
    const raw = Math.max(peak, 1);
    const magnitude = 10 ** Math.floor(Math.log10(raw));
    return Math.ceil(raw / magnitude) * magnitude;
  });

  const plotWidth = $derived(WIDTH - PAD.left - PAD.right);
  const plotHeight = $derived(HEIGHT - PAD.top - PAD.bottom);

  function x(index: number): number {
    const span = Math.max(samples.length - 1, 1);
    return PAD.left + (index / span) * plotWidth;
  }
  function y(value: number): number {
    return PAD.top + plotHeight - (value / ceiling) * plotHeight;
  }

  const line = $derived(samples.map((point, index) => `${x(index)},${y(point.value)}`).join(' '));
  const area = $derived(
    samples.length
      ? `${PAD.left},${PAD.top + plotHeight} ${line} ${x(samples.length - 1)},${PAD.top + plotHeight}`
      : ''
  );

  const marker = $derived(hovered === null ? null : samples[hovered]);

  function track(event: PointerEvent) {
    if (!samples.length) return;
    const box = (event.currentTarget as SVGSVGElement).getBoundingClientRect();
    const local = ((event.clientX - box.left) / box.width) * WIDTH;
    const span = Math.max(samples.length - 1, 1);
    const index = Math.round(((local - PAD.left) / plotWidth) * span);
    hovered = Math.min(samples.length - 1, Math.max(0, index));
  }

  function clock(at: number): string {
    return new Date(at).toLocaleTimeString('es', { hour12: false });
  }
</script>

<figure class="chart">
  <figcaption>
    <span class="label">{label}</span>
    <!-- The numbers live in text as well as in the trace, so the chart is not
         the only way to read them. A single series needs no legend. -->
    <span class="readout tabular">
      ahora <b>{rate.toFixed(1)}</b> · media {mean.toFixed(1)} · pico {peak.toFixed(1)}
    </span>
  </figcaption>

  <svg
    viewBox="0 0 {WIDTH} {HEIGHT}"
    preserveAspectRatio="none"
    role="img"
    aria-label={`${label}: ahora ${rate.toFixed(1)}, media ${mean.toFixed(1)}, pico ${peak.toFixed(1)}`}
    onpointermove={track}
    onpointerleave={() => (hovered = null)}
  >
    <!-- Hairline grid, solid and one shade off the surface. -->
    {#each [0, 0.5, 1] as fraction (fraction)}
      <line
        class="grid"
        x1={PAD.left}
        x2={WIDTH - PAD.right}
        y1={PAD.top + plotHeight * fraction}
        y2={PAD.top + plotHeight * fraction}
      />
    {/each}
    <text class="axis" x={PAD.left - 6} y={PAD.top + 4} text-anchor="end">{ceiling}</text>
    <text class="axis" x={PAD.left - 6} y={PAD.top + plotHeight} text-anchor="end">0</text>

    {#if samples.length > 1}
      <polygon class="area" points={area} style:fill={color} />
      <polyline class="line" points={line} style:stroke={color} />
      <!-- The endpoint is the only point that gets a marker: it is "now". -->
      <circle
        class="head"
        cx={x(samples.length - 1)}
        cy={y(samples[samples.length - 1].value)}
        r="3.5"
        style:fill={color}
      />
    {/if}

    {#if marker && hovered !== null}
      <line class="crosshair" x1={x(hovered)} x2={x(hovered)} y1={PAD.top} y2={PAD.top + plotHeight} />
      <circle cx={x(hovered)} cy={y(marker.value)} r="4" class="hit" style:fill={color} />
    {/if}
  </svg>

  {#if marker}
    <div class="tooltip tabular">
      <b>{marker.value.toFixed(1)}</b> p/s · {clock(marker.t)}
    </div>
  {:else if !samples.length}
    <p class="waiting">Midiendo…</p>
  {/if}
</figure>

<style>
  .chart {
    margin: 0;
  }

  figcaption {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 0.35rem;
  }
  .label {
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.055em;
    text-transform: uppercase;
    color: var(--muted);
  }
  /* Text wears text tokens; the trace beside it carries the identity. */
  .readout {
    font-family: var(--font-mono);
    font-size: 0.7rem;
    color: var(--muted);
  }
  .readout b {
    color: var(--ink);
  }

  svg {
    display: block;
    width: 100%;
    height: 108px;
    overflow: visible;
    touch-action: none;
  }

  .grid {
    stroke: var(--grid);
    stroke-width: 1;
    vector-effect: non-scaling-stroke;
  }
  .axis {
    fill: var(--muted);
    font-family: var(--font-mono);
    font-size: 9px;
  }

  .area {
    opacity: 0.14;
  }
  .line {
    fill: none;
    stroke-width: 2;
    stroke-linejoin: round;
    stroke-linecap: round;
    vector-effect: non-scaling-stroke;
  }
  .head,
  .hit {
    stroke: var(--surface-2);
    stroke-width: 2;
    vector-effect: non-scaling-stroke;
  }
  .crosshair {
    stroke: var(--axis);
    stroke-width: 1;
    vector-effect: non-scaling-stroke;
  }

  .tooltip {
    margin-top: 0.3rem;
    font-family: var(--font-mono);
    font-size: 0.7rem;
    color: var(--muted);
  }
  .tooltip b {
    color: var(--ink);
  }

  .waiting {
    margin: 0.3rem 0 0;
    font-size: 0.72rem;
    color: var(--muted);
  }
</style>
