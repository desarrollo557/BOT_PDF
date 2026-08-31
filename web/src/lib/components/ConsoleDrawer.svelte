<script lang="ts">
  import { onMount } from 'svelte';
  import { consoleLog } from '$lib/console.svelte';

  interface Props {
    /** Documents queued or running, for the status light. */
    active?: number;
  }

  let { active = 0 }: Props = $props();

  /**
   * Docked vertically down the right edge, open by default.
   *
   * Watching the run go by is the reason this console exists, so it is not
   * hidden behind a seam: closed, it stays on the same edge as a labelled rail
   * you can see and click. Whichever way the operator leaves it -- open, closed,
   * wider, narrower -- is how they find it next time.
   */
  const OPEN_KEY = 'resolutions.console.open';
  const WIDTH_KEY = 'resolutions.console.width';

  const MIN_WIDTH = 300;
  const MAX_WIDTH = 1000;
  const DEFAULT_WIDTH = 580;
  /** The rail that remains when it is closed. */
  const RAIL = 34;

  function remembered<T>(key: string, fallback: T, parse: (raw: string) => T): T {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? fallback : parse(raw);
    } catch {
      // A private window or blocked storage means "use the default", never a
      // crash on the way to showing the console.
      return fallback;
    }
  }

  function remember(key: string, value: string): void {
    try {
      localStorage.setItem(key, value);
    } catch {
      // Losing the preference costs one click next time.
    }
  }

  let open = $state(true);
  let width = $state(DEFAULT_WIDTH);

  onMount(() => {
    open = remembered(OPEN_KEY, true, (raw) => raw !== '0');
    width = remembered(WIDTH_KEY, DEFAULT_WIDTH, (raw) => {
      const value = Number(raw);
      return Number.isFinite(value)
        ? Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, value))
        : DEFAULT_WIDTH;
    });
  });

  function toggle() {
    open = !open;
    remember(OPEN_KEY, open ? '1' : '0');
  }

  // -- drag the left edge to resize -------------------------------------------

  let dragging = $state(false);

  function startDrag(event: PointerEvent) {
    event.preventDefault();
    dragging = true;
    const startX = event.clientX;
    const startWidth = width;
    const move = (moved: PointerEvent) => {
      width = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth - (moved.clientX - startX)));
    };
    const end = () => {
      dragging = false;
      remember(WIDTH_KEY, String(Math.round(width)));
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', end);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', end);
  }

  /** The page reserves exactly the room the console is taking, however wide. */
  $effect(() => {
    document.documentElement.style.setProperty(
      '--console-space',
      `${open ? width : RAIL}px`
    );
    return () => document.documentElement.style.removeProperty('--console-space');
  });

  const lines = $derived(consoleLog.lines);

  let viewport = $state<HTMLDivElement | null>(null);
  let pinned = $state(true);

  function onScroll() {
    if (!viewport) return;
    pinned = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 24;
  }

  $effect(() => {
    lines.length;
    if (open && pinned && viewport) viewport.scrollTop = viewport.scrollHeight;
  });
</script>

{#if open}
  <aside class="dock" style:width={`${width}px`} aria-label="Consola de procesamiento">
    <div
      class="grip"
      class:dragging
      role="separator"
      aria-label="Ajustar ancho de la consola"
      onpointerdown={startDrag}
    ></div>

    <header class="bar">
      <span class="dots" aria-hidden="true"><i></i><i></i><i></i></span>
      <span class="title">resolutions@siar — <b>/proc/split</b></span>
      <span class="led" class:on={active > 0} aria-hidden="true"></span>
      <button class="hide" onclick={toggle} aria-label="Ocultar la consola">✕</button>
    </header>

    <div class="viewport" bind:this={viewport} onscroll={onScroll} role="log" aria-live="polite">
      <p class="line lvl-sys">
        <span class="time">--:--:--</span><span class="tag">BOOT</span>
        <span class="text">separador de resoluciones · consola lista</span>
      </p>
      {#each lines as line (line.id)}
        <p class="line lvl-{line.level}">
          <span class="time">{line.time}</span>
          <span class="tag">{line.tag}</span>
          {#if line.scope}<span class="scope">{line.scope}</span>{/if}
          <span class="text">{line.text}</span>
        </p>
      {/each}
      <p class="line prompt">
        <span class="ps1">&gt;</span><span class="caret" aria-hidden="true"></span>
      </p>
    </div>

    <footer class="bar foot">
      <span class="count">{lines.length} líneas</span>
      <span class="spacer"></span>
      {#if !pinned}
        <button
          onclick={() => {
            pinned = true;
            if (viewport) viewport.scrollTop = viewport.scrollHeight;
          }}
        >
          seguir
        </button>
      {/if}
      <button
        class:armed={consoleLog.paused}
        onclick={() => (consoleLog.paused = !consoleLog.paused)}
      >
        {consoleLog.paused ? 'reanudar' : 'pausar'}
      </button>
      <button onclick={() => consoleLog.clear()}>limpiar</button>
    </footer>

    <div class="scanlines" aria-hidden="true"></div>
  </aside>
{:else}
  <!-- Closed, it stays on the same edge as something you can see and click,
       never a seam. Losing the console once was enough. -->
  <button class="rail" onclick={toggle} aria-label="Mostrar la consola">
    <span class="led" class:on={active > 0} aria-hidden="true"></span>
    <span class="vertical">consola</span>
  </button>
{/if}

<style>
  /*
   * The console keeps its own palette in both themes on purpose: a terminal
   * that turns into a white box in light mode stops reading as a terminal.
   */
  .dock,
  .rail {
    --term-bg: #05080a;
    --term-dim: #4d6b74;
    --term-fg: #b6d8cf;
    --term-green: #2ce69b;
    --term-cyan: #38bdf8;
    --term-amber: #fbbf24;
    --term-red: #fb5c6b;
    --term-violet: #c084fc;
  }

  .dock {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    z-index: 45;
    display: flex;
    flex-direction: column;
    border-left: 1px solid #133038;
    background:
      radial-gradient(120% 60% at 50% 0%, #0b1a1e 0%, var(--term-bg) 70%),
      var(--term-bg);
    box-shadow: -18px 0 40px rgb(0 0 0 / 0.3);
    font-family: var(--font-mono);
  }

  .grip {
    position: absolute;
    top: 0;
    bottom: 0;
    left: -3px;
    z-index: 1;
    width: 6px;
    background: transparent;
    cursor: ew-resize;
    transition: background 0.15s;
  }
  .grip:hover,
  .grip.dragging {
    background: var(--term-green);
  }

  .bar {
    display: flex;
    flex-shrink: 0;
    align-items: center;
    gap: 0.5rem;
    border-bottom: 1px solid #123038;
    background: linear-gradient(#0c1a1f, #081215);
    padding: 0.5rem 0.7rem;
    font-size: 0.68rem;
    letter-spacing: 0.04em;
    color: var(--term-dim);
  }

  .dots {
    display: flex;
    flex-shrink: 0;
    gap: 4px;
  }
  .dots i {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #1d3d46;
  }
  .dots i:first-child {
    background: #3b2a2f;
  }

  .title {
    overflow: hidden;
    text-overflow: ellipsis;
    text-transform: uppercase;
    white-space: nowrap;
  }
  .title b {
    font-weight: 500;
    color: var(--term-green);
  }

  .led {
    width: 7px;
    height: 7px;
    flex-shrink: 0;
    margin-left: auto;
    border-radius: 50%;
    background: #1d3d46;
  }
  .led.on {
    background: var(--term-green);
    box-shadow: 0 0 8px var(--term-green);
    animation: pulse 1.4s ease-in-out infinite;
  }

  .hide {
    flex-shrink: 0;
    border: 0;
    background: none;
    padding: 0 0 0 0.3rem;
    font: inherit;
    font-size: 0.75rem;
    color: var(--term-dim);
    cursor: pointer;
  }
  .hide:hover {
    color: var(--term-fg);
  }

  .viewport {
    flex: 1;
    overflow-x: hidden;
    overflow-y: auto;
    padding: 0.6rem 0.7rem 0.9rem;
    font-size: 0.7rem;
    line-height: 1.45;
    color: var(--term-fg);
    scrollbar-width: thin;
    scrollbar-color: #1d3d46 transparent;
  }

  .line {
    display: flex;
    margin: 0;
    gap: 0.5ch;
    overflow-wrap: anywhere;
  }
  .time {
    flex-shrink: 0;
    color: #2f545d;
  }
  .tag {
    min-width: 5ch;
    flex-shrink: 0;
    font-weight: 600;
    letter-spacing: 0.04em;
  }
  .scope {
    max-width: 14ch;
    flex-shrink: 0;
    overflow: hidden;
    color: var(--term-dim);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .text {
    min-width: 0;
  }

  /* One colour per kind of event; the tag always carries the word too, so the
     meaning never rests on colour alone. */
  .lvl-sys .tag {
    color: var(--term-dim);
  }
  .lvl-net .tag {
    color: var(--term-cyan);
  }
  .lvl-page .tag {
    color: var(--term-green);
  }
  .lvl-page .text {
    color: #7fb8ac;
  }
  .lvl-model .tag,
  .lvl-model .text {
    color: var(--term-violet);
  }
  .lvl-ok .tag {
    color: var(--term-green);
  }
  .lvl-ok .text {
    color: #d6fff0;
    text-shadow: 0 0 8px rgb(44 230 155 / 0.35);
  }
  .lvl-warn .tag,
  .lvl-warn .text {
    color: var(--term-amber);
  }
  .lvl-fail .tag,
  .lvl-fail .text {
    color: var(--term-red);
  }

  .prompt {
    align-items: center;
    gap: 0.6ch;
  }
  .ps1 {
    color: var(--term-green);
  }
  .caret {
    display: inline-block;
    width: 7px;
    height: 13px;
    background: var(--term-green);
    box-shadow: 0 0 8px rgb(44 230 155 / 0.6);
    animation: blink 1.05s steps(1) infinite;
  }

  .foot {
    border-top: 1px solid #123038;
    border-bottom: 0;
    gap: 0.35rem;
  }
  .spacer {
    flex: 1;
  }
  .count {
    color: #2f545d;
  }
  .foot button {
    border: 1px solid #1d3d46;
    border-radius: 4px;
    background: transparent;
    padding: 0.1rem 0.45rem;
    font: inherit;
    font-size: 0.66rem;
    color: var(--term-dim);
    cursor: pointer;
    transition:
      color 0.15s,
      border-color 0.15s;
  }
  .foot button:hover {
    border-color: var(--term-green);
    color: var(--term-green);
  }
  .foot button.armed {
    border-color: var(--term-amber);
    color: var(--term-amber);
  }

  .scanlines {
    position: absolute;
    inset: 0;
    background: repeating-linear-gradient(
      to bottom,
      rgb(255 255 255 / 0.025) 0 1px,
      transparent 1px 3px
    );
    mix-blend-mode: overlay;
    pointer-events: none;
  }

  .rail {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    z-index: 45;
    display: flex;
    width: 34px;
    flex-direction: column;
    align-items: center;
    gap: 0.75rem;
    border: 0;
    border-left: 1px solid #133038;
    background: linear-gradient(#0c1a1f, #05080a);
    padding-top: 0.85rem;
    font-family: var(--font-mono);
    color: var(--term-dim);
    cursor: pointer;
    transition: color 0.15s;
  }
  .rail:hover {
    color: var(--term-green);
  }
  .rail .led {
    margin-left: 0;
  }
  .vertical {
    font-size: 0.68rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    writing-mode: vertical-rl;
  }

  @keyframes blink {
    0%,
    49% {
      opacity: 1;
    }
    50%,
    100% {
      opacity: 0;
    }
  }
  @keyframes pulse {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.35;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .caret,
    .led.on {
      animation: none;
    }
  }
</style>
