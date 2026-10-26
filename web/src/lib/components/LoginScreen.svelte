<script lang="ts">
  import { session } from '$lib/session.svelte';

  /**
   * Entrada sin contraseña: el usuario «siar» y el botón. El perfil lo
   * contesta el servicio.
   */
  let usuario = $state('siar');
  let attempted = $state(false);

  const valid = $derived(usuario.trim().length > 0);
  const resuming = $derived(session.state === 'idle');

  // Lo que se le dice al campo: el aviso de vacío y el rechazo del servicio.
  const describe = $derived(
    [attempted && !valid ? 'usuario-vacio' : '', session.error ? 'usuario-rechazado' : '']
      .filter(Boolean)
      .join(' ') || undefined
  );

  async function submit(event: Event) {
    event.preventDefault();
    attempted = true;
    if (!valid || session.entrando) return;
    await session.open(usuario);
  }
</script>

<div class="stage">
  <div class="panel entrada">
    <!-- El producto primero: es lo que el operador abre. La empresa dueña firma
         al pie, separada por un filete; son dos cosas distintas y no deben
         leerse como una sola. -->
    <header>
      <svg class="mark" viewBox="0 0 24 24" aria-hidden="true">
        <rect x="2.5" y="2.5" width="12" height="16" rx="2" />
        <rect class="second" x="9.5" y="5.5" width="12" height="16" rx="2" />
        <path class="split" d="M13 11h5M13 14h5M13 17h3" />
      </svg>
      <div>
        <h1>Folia</h1>
        <p>División inteligente de documentos</p>
      </div>
    </header>

    {#if resuming && session.operator}
      <div class="resume">
        <p class="lead">
          La sesión de <b>{session.name}</b> quedó inactiva.
        </p>
        <p class="muted">
          Nadie la bloqueó: sólo pasó una hora sin actividad y el sistema dejó de atribuirle
          trabajo. Continúe, o vuelva a ingresar.
        </p>
        <div class="actions">
          <button class="btn btn-primary" onclick={() => session.resume()}>
            Continuar como {session.name}
          </button>
          <button class="btn btn-ghost" onclick={() => session.close()}>Salir</button>
        </div>
      </div>
    {:else}
      <form onsubmit={submit}>
        <label>
          <span class="caps">Usuario</span>
          <input
            class="input"
            bind:value={usuario}
            placeholder="siar"
            autocomplete="username"
            spellcheck="false"
            aria-invalid={attempted && !valid}
            aria-describedby={describe}
          />
          {#if attempted && !valid}
            <small id="usuario-vacio" class="bad">Escriba el usuario.</small>
          {/if}
        </label>

        {#if session.error}
          <p id="usuario-rechazado" class="inline-error rejected" role="alert">{session.error}</p>
        {/if}

        <button class="btn btn-primary btn-block" type="submit" disabled={!valid || session.entrando}>
          {session.entrando ? 'Ingresando…' : 'Ingresar'}
        </button>
      </form>
    {/if}

    <footer>
      <span>Software de</span>
      <img src="/siar-marca.png" alt="SIAR — Hacemos todo por su información" width="72" height="38" />
    </footer>
  </div>
</div>

<style>
  .stage {
    display: grid;
    min-height: 100dvh;
    place-items: center;
    padding: var(--space-6) var(--space-4);
  }

  /* La tarjeta es el `.panel` común; la de entrada es la única de la pantalla
     y respira un poco más. */
  .entrada {
    display: flex;
    width: min(24rem, 100%);
    flex-direction: column;
    gap: var(--space-6);
    padding: var(--space-8) var(--space-6) var(--space-5);
  }

  header {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }
  .mark {
    width: 40px;
    height: 40px;
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
  h1 {
    margin: 0;
    font-size: var(--text-xl);
    font-weight: 650;
    line-height: 1.2;
    letter-spacing: -0.02em;
  }
  header p {
    margin: 2px 0 0;
    font-size: var(--text-sm);
    color: var(--muted);
  }

  form {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  label {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  /* El campo y los botones son los comunes (`.input`, `.btn`); aquí sólo lo
     que esta tarjeta tiene de propio. */
  .bad {
    font-size: var(--text-xs);
    color: var(--critical);
  }
  .rejected {
    margin: 0;
    line-height: 1.5;
  }

  .lead {
    margin: 0;
    font-size: var(--text-lg);
  }
  .muted {
    margin: var(--space-1) 0 0;
    font-size: var(--text-sm);
    line-height: 1.5;
    color: var(--muted);
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin-top: var(--space-4);
  }

  /* La firma: un filete, «Software de» y la marca de SIAR, que se monta en una
     placa clara en oscuro para no teñirla. */
  footer {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    border-top: 1px solid var(--rule);
    padding-top: var(--space-4);
    font-size: var(--text-xs);
    color: var(--muted);
  }
  footer img {
    width: auto;
    height: 22px;
    border-radius: var(--radius-sm);
    background: var(--logo-plate);
    padding: 3px 6px;
  }
</style>
