<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchHealth, type Health } from '$lib/api';

  interface Props {
    /** Documents queued or running right now, from the live stream. */
    active?: number;
  }

  let { active = 0 }: Props = $props();

  /**
   * The service does not change shape often; the live stream already carries
   * everything that moves per second. Polling this slowly keeps the rail honest
   * about the connection without adding a request per second to say so.
   */
  const POLL_MS = 15_000;

  let health = $state<Health | null>(null);
  let checked = $state(false);
  let since = $state(Date.now());
  let now = $state(Date.now());

  const online = $derived(health?.status === 'ok');
  const condition = $derived(!checked ? 'probing' : !online ? 'down' : active ? 'busy' : 'idle');

  const LABEL: Record<string, string> = {
    probing: 'Conectando',
    down: 'Sin conexión',
    busy: 'Procesando',
    idle: 'En servicio'
  };

  /** Time the operator has had this console open, which is what they can see. */
  const uptime = $derived.by(() => {
    const seconds = Math.floor((now - since) / 1000);
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (hours) return `${hours}h ${String(minutes).padStart(2, '0')}m`;
    if (minutes) return `${minutes}m ${String(seconds % 60).padStart(2, '0')}s`;
    return `${seconds}s`;
  });

  onMount(() => {
    const probe = async () => {
      const next = await fetchHealth();
      // A dropped connection restarts the clock, because an uptime that counts
      // through an outage is worse than no uptime at all.
      if (!next && health) since = Date.now();
      health = next;
      checked = true;
    };
    probe();
    const poll = setInterval(probe, POLL_MS);
    const tick = setInterval(() => (now = Date.now()), 1000);
    return () => {
      clearInterval(poll);
      clearInterval(tick);
    };
  });
</script>

<div class="rail" data-state={condition}>
  <span class="lamp" aria-hidden="true"></span>
  <span class="state">{LABEL[condition]}</span>

  <span class="sep" aria-hidden="true"></span>

  {#if online && health}
    <span class="item" title="Procesos que trabajan un documento cada uno">
      <b class="tabular">{health.document_workers}</b> procesos
    </span>
    <span class="item" title="Documentos aceptados y todavía sin terminar">
      cola <b class="tabular">{health.queued}</b>
    </span>
    <span class="item vision" class:on={health.vision === 'claude'}>
      visión {health.vision === 'claude' ? 'activa' : 'apagada'}
    </span>
  {:else if checked}
    <span class="item">el servicio no responde</span>
  {:else}
    <span class="item">…</span>
  {/if}

  <span class="item uptime tabular" title="Tiempo con la consola abierta">{uptime}</span>
</div>

<style>
  .rail {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.55rem;
    border: 1px solid var(--hairline);
    border-radius: 999px;
    background: var(--surface-2);
    padding: 0.35rem 0.85rem;
    font-family: var(--font-mono);
    font-size: 0.7rem;
    letter-spacing: 0.01em;
    color: var(--muted);
    white-space: nowrap;
  }

  /* One lamp, four states, and the word beside it always says which -- the
     colour is a second reading of the label, never the only one. */
  .lamp {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--axis);
  }
  [data-state='idle'] .lamp {
    background: var(--good);
    box-shadow: 0 0 0 3px color-mix(in oklab, var(--good) 18%, transparent);
  }
  [data-state='busy'] .lamp {
    background: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-soft);
    animation: breathe 1.6s ease-in-out infinite;
  }
  [data-state='down'] .lamp {
    background: var(--critical);
    box-shadow: 0 0 0 3px color-mix(in oklab, var(--critical) 18%, transparent);
  }
  [data-state='probing'] .lamp {
    animation: breathe 1.6s ease-in-out infinite;
  }

  .state {
    font-weight: 600;
    color: var(--ink-2);
  }
  [data-state='down'] .state {
    color: var(--critical);
  }

  .sep {
    width: 1px;
    height: 12px;
    background: var(--hairline);
  }

  .item b {
    font-weight: 600;
    color: var(--ink-2);
  }

  .vision.on {
    color: var(--ink-2);
  }

  .uptime {
    margin-left: auto;
    padding-left: 0.5rem;
    color: var(--axis);
  }

  @keyframes breathe {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.4;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .lamp {
      animation: none;
    }
  }
</style>
