<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { setIdentidad, setOperator } from '$lib/api';
  import { atraparErroresSueltos } from '$lib/avisos.svelte';
  import Avisos from '$lib/components/Avisos.svelte';
  import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
  import CompletionReport from '$lib/components/CompletionReport.svelte';
  import ConsoleDrawer from '$lib/components/ConsoleDrawer.svelte';
  import StaleServiceBanner from '$lib/components/StaleServiceBanner.svelte';
  import LoginScreen from '$lib/components/LoginScreen.svelte';
  import Migas from '$lib/components/Migas.svelte';
  import SessionMenu from '$lib/components/SessionMenu.svelte';
  import StatusRail from '$lib/components/StatusRail.svelte';
  import { jobStore } from '$lib/jobs.svelte';
  import { reports } from '$lib/report.svelte';
  import { session } from '$lib/session.svelte';

  let { children } = $props();

  // Opened here, not in a page: every screen reads the same stream, and one
  // owned by a page would drop on every navigation. The stream runs regardless
  // of who is at the console -- work in flight is the service's, not a
  // session's, and must not stop because somebody stepped away.
  onMount(() => {
    // Antes que nada: si conectar o arrancar la sesión fallan, eso también se ve.
    const soltar = atraparErroresSueltos();
    const release = jobStore.connect();
    const stop = session.start();
    return () => {
      release();
      stop();
      soltar();
    };
  });

  // One writer for attribution: the session decides, the client sends. Van los
  // dos juntos porque contestan preguntas distintas de la misma persona: el
  // nombre es la etiqueta que llega al libro mayor y la cédula es con lo que el
  // servicio averigua qué perfil tiene.
  $effect(() => {
    const dentro = session.state === 'active';
    setOperator(dentro ? session.name : null);
    setIdentidad(dentro ? session.cedula : null);
  });

  const inside = $derived(session.state === 'active');

  const active = $derived(jobStore.inFlight.length);
  const here = $derived(page.url.pathname);

  const ready = $derived(jobStore.finished.length);
  const pending = $derived(
    jobStore.finished.reduce((sum, job) => sum + (job.report?.review_queue?.length ?? 0), 0)
  );

  /**
   * Three destinations, one verb each: do the work, find the work, fix the work.
   *
   * The badges carry the whole navigation story. An operator should be able to
   * tell from the bar alone whether anything is waiting for them, without
   * opening a screen to find out.
   */
  const TABS = $derived([
    {
      href: '/',
      label: 'Procesar',
      match: (path: string) => path === '/',
      badge: active || null,
      tone: 'live'
    },
    {
      href: '/archivo',
      label: 'Archivo',
      match: (path: string) => path.startsWith('/archivo') || path.startsWith('/documento'),
      badge: ready || null,
      tone: 'quiet'
    },
    {
      href: '/revision',
      label: 'Revisión',
      match: (path: string) => path.startsWith('/revision'),
      badge: pending || null,
      tone: 'warn'
    }
    // Sin pestaña de Usuarios: se entra siempre como «siar», y con eso basta.
  ]);
</script>

{#if !inside}
  <!-- También delante de la entrada: contra un servicio que quedó corriendo
       desde antes de una actualización, entrar falla, y sin este aviso el
       operador no tiene cómo saber que lo que falta es reiniciarlo. -->
  <StaleServiceBanner />
  <LoginScreen />
{:else}
  <div class="beside">
    <StaleServiceBanner />

    <header class="topbar">
      <a class="brand" href="/">
        <!-- One sheet splitting into two: the whole product in a 24px square. -->
        <svg class="mark" viewBox="0 0 24 24" aria-hidden="true">
          <rect x="2.5" y="2.5" width="12" height="16" rx="2" />
          <rect class="second" x="9.5" y="5.5" width="12" height="16" rx="2" />
          <path class="split" d="M13 11h5M13 14h5M13 17h3" />
        </svg>
        <span class="titles">
          <b>Separador de resoluciones</b>
          <small>Clasificación y división automática de documentos</small>
        </span>
      </a>

      <!-- La marca de la empresa dueña del software, separada del producto por
           un filete: son dos cosas distintas y no deben leerse como una sola. -->
      <span class="owner" title="SIAR — Hacemos todo por su información">
        <img src="/siar-marca.png" alt="SIAR" width="72" height="38" />
      </span>

      <nav class="tabs segmented">
        {#each TABS as tab (tab.href)}
          <a href={tab.href} class:current={tab.match(here)}>
            {tab.label}
            {#if tab.badge}
              <span class="badge tabular" data-tone={tab.tone}>{tab.badge}</span>
            {/if}
          </a>
        {/each}
      </nav>

      <div class="rail">
        <StatusRail {active} />
        <SessionMenu />
      </div>
    </header>

    <main>
      <Migas />
      {@render children()}
    </main>
  </div>

  {#if reports.showing}
    <CompletionReport completion={reports.showing} />
  {/if}

  <ConsoleDrawer {active} />
{/if}

<!-- Fuera de la sesión también: un error al entrar debe verse, y la pregunta
     de confirmar la puede hacer cualquier pantalla. -->
<Avisos />
<ConfirmDialog />

<style>
  .topbar {
    position: sticky;
    top: 0;
    z-index: 30;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.75rem 1.5rem;
    border-bottom: 1px solid var(--hairline);
    /* Translucent so content scrolling under it reads as depth, not a seam. */
    background: color-mix(in oklab, var(--surface-1) 84%, transparent);
    padding: 0.7rem 1.5rem;
    backdrop-filter: blur(10px);
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    color: inherit;
    text-decoration: none;
  }

  .mark {
    width: 26px;
    height: 26px;
    flex-shrink: 0;
    fill: none;
    stroke: var(--accent);
    stroke-width: 1.5;
  }
  .mark .second {
    fill: var(--accent-soft);
  }
  .mark .split {
    stroke-linecap: round;
    opacity: 0.7;
  }

  .titles {
    display: flex;
    flex-direction: column;
    line-height: 1.25;
  }
  .titles b {
    font-size: var(--text-lg);
    font-weight: 650;
    letter-spacing: -0.011em;
  }
  .titles small {
    font-size: var(--text-xs);
    color: var(--muted);
  }

  .owner {
    display: flex;
    align-items: center;
    border-left: 1px solid var(--hairline);
    padding-left: 0.9rem;
  }
  .owner img {
    width: auto;
    height: 19px;
    border-radius: var(--radius-sm);
    /* Transparente en claro; en oscuro, una placa para no teñir la marca. */
    background: var(--logo-plate);
    padding: 3px 6px;
  }

  /* Las pestañas son el control segmentado común (`.segmented`): el mismo
     radio, el mismo relleno y la misma letra que «Por documento / Por PDF
     generado» o los filtros de Revisión. Aquí sólo se alinean el texto y el
     contador. */
  .tabs > a {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    transition:
      background 0.15s,
      color 0.15s;
  }

  .badge {
    border-radius: var(--radius-pill);
    padding: 0 0.35rem;
    font-size: var(--text-2xs);
    font-weight: 600;
  }
  .badge[data-tone='live'] {
    background: var(--good-soft);
    color: var(--good);
  }
  .badge[data-tone='quiet'] {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .badge[data-tone='warn'] {
    background: var(--warning-soft);
    color: var(--warning-ink);
  }

  .rail {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    margin-left: auto;
  }

  /* The console publishes how much room it is taking down the right edge; the
     chrome reserves exactly that, so nothing ends underneath it however wide
     the operator drags it. */
  .beside {
    margin-right: var(--console-space, 34px);
    transition: margin-right 0.12s ease-out;
  }

  main {
    display: block;
    min-height: calc(100dvh - 4.5rem);
    padding: 1.25rem 1.5rem 2rem;
  }
  @media (min-width: 1536px) {
    main {
      padding-inline: 2.5rem;
    }
  }
</style>
