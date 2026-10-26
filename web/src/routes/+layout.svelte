<script lang="ts">
  // Las fuentes van dentro del build: el servicio corre en la intranet y no
  // puede depender de Google Fonts. Cada archivo declara su `unicode-range`, así
  // que el navegador sólo baja los alfabetos que la página usa.
  import '@fontsource-variable/inter';
  import '@fontsource-variable/jetbrains-mono';
  import '../app.css';
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { alPedirCredenciales, setIdentidad, setOperator } from '$lib/api';
  import CredencialesDeRed from '$lib/components/CredencialesDeRed.svelte';
  import { preguntaDeRed } from '$lib/red.svelte';
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
    // Una carpeta de red que pide usuario y clave: se le preguntan al operador.
    alPedirCredenciales(({ recurso, mensaje }) => preguntaDeRed.pedir(recurso, mensaje));
    const release = jobStore.connect();
    const stop = session.start();
    return () => {
      release();
      stop();
      soltar();
      alPedirCredenciales(null);
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
   *
   * Los contadores son la `.pill` común: lo que corre, en el acento (algo en
   * curso); lo terminado, neutro; lo que espera una mirada, en aviso.
   */
  const TABS = $derived([
    {
      href: '/',
      label: 'Procesar',
      match: (path: string) => path === '/',
      badge: active || null,
      tone: ''
    },
    {
      href: '/archivo',
      label: 'Archivo',
      match: (path: string) => path.startsWith('/archivo') || path.startsWith('/documento'),
      badge: ready || null,
      tone: 'pill-neutral'
    },
    {
      href: '/revision',
      label: 'Revisión',
      match: (path: string) => path.startsWith('/revision'),
      badge: pending || null,
      tone: 'pill-warn'
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
          <b>Folia</b>
          <small>División inteligente de documentos</small>
        </span>
      </a>

      <!-- La marca de la empresa dueña del software, separada del producto por
           un filete: son dos cosas distintas y no deben leerse como una sola. -->
      <span class="owner" title="SIAR — Hacemos todo por su información">
        <img src="/siar-marca.png" alt="SIAR" width="72" height="38" />
      </span>

      <nav class="tabs segmented" aria-label="Secciones">
        {#each TABS as tab (tab.href)}
          <a href={tab.href} aria-current={tab.match(here) ? 'page' : undefined}>
            {tab.label}
            {#if tab.badge}
              <span class="pill pill-sm {tab.tone}">{tab.badge}</span>
            {/if}
          </a>
        {/each}
      </nav>

      <div class="estado"><StatusRail {active} /></div>
      <!-- Sólo en el teléfono: ahí la consola no deja riel en el borde. -->
      <button
        type="button"
        class="btn btn-ghost btn-sm consola-movil"
        onclick={() => window.dispatchEvent(new CustomEvent('folia:consola'))}
      >
        Consola
      </button>
      <div class="sesion"><SessionMenu /></div>
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
<CredencialesDeRed />

<style>
  /* Una fila en pantalla ancha: marca · SIAR · pestañas · estado · sesión.
     Por debajo de 1024 px, dos: arriba quién es y quién opera, abajo adónde ir
     y cómo está el servicio. Por debajo de 640 px el subtítulo se calla y el
     riel se queda en su luz y su palabra. */
  .topbar {
    position: sticky;
    top: 0;
    z-index: 30;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3) var(--space-6);
    border-bottom: 1px solid var(--hairline);
    /* Sólida: el filete de abajo ya separa la barra del contenido, y un fondo
       translúcido y desenfocado es un adorno que esta consola no lleva. */
    background: var(--surface-1);
    padding: var(--space-3) var(--space-6);
  }

  .brand {
    display: flex;
    align-items: center;
    gap: var(--space-3);
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
    padding-left: var(--space-4);
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
    gap: var(--space-2);
    transition:
      background-color var(--duration-fast) var(--ease-out),
      color var(--duration-fast) var(--ease-out);
  }

  .estado {
    margin-left: auto;
  }
  .consola-movil {
    display: none;
  }

  @media (max-width: 1023px) {
    .brand {
      order: 1;
    }
    .owner {
      order: 2;
    }
    .sesion {
      order: 3;
      margin-left: auto;
    }
    .tabs {
      order: 4;
    }
    .estado {
      order: 5;
    }
  }

  @media (max-width: 639px) {
    .topbar {
      gap: var(--space-2) var(--space-3);
      padding: var(--space-2) var(--space-4);
    }
    .titles small {
      display: none;
    }
    .owner {
      padding-left: var(--space-3);
    }
    .tabs > a {
      padding-inline: 0.6rem;
    }
    .consola-movil {
      display: inline-flex;
      order: 3;
      margin-left: auto;
    }
    .sesion {
      margin-left: 0;
    }
  }

  /* The console publishes how much room it is taking down the right edge; the
     chrome reserves exactly that, so nothing ends underneath it however wide
     the operator drags it. */
  .beside {
    margin-right: var(--console-space, 34px);
    transition: margin-right var(--duration-fast) var(--ease-out);
  }

  main {
    display: block;
    min-height: calc(100dvh - 4.5rem);
    padding: var(--space-5) var(--space-6) var(--space-8);
  }
  @media (max-width: 639px) {
    main {
      padding: var(--space-4) var(--space-4) var(--space-6);
    }
  }
  @media (min-width: 1536px) {
    main {
      padding-inline: 2.5rem;
    }
  }
</style>
