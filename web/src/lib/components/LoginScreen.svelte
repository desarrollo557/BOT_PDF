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

  async function submit(event: Event) {
    event.preventDefault();
    attempted = true;
    if (!valid || session.entrando) return;
    await session.open(usuario);
  }
</script>

<div class="stage">
  <div class="card">
    <div class="owner">
      <img
        src="/siar.png"
        alt="SIAR — Hacemos todo por su información"
        width="148"
        height="93"
      />
    </div>

    <header>
      <svg class="mark" viewBox="0 0 24 24" aria-hidden="true">
        <rect x="2.5" y="2.5" width="12" height="16" rx="2" />
        <rect class="second" x="9.5" y="5.5" width="12" height="16" rx="2" />
        <path class="split" d="M13 11h5M13 14h5M13 17h3" />
      </svg>
      <div>
        <h1>Separador de resoluciones</h1>
        <p>Clasificación y división automática de documentos</p>
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
          />
          {#if attempted && !valid}
            <small class="bad">Escriba el usuario.</small>
          {/if}
        </label>

        {#if session.error}
          <p class="inline-error rejected">{session.error}</p>
        {/if}

        <button class="btn btn-primary btn-block wide" type="submit" disabled={!valid || session.entrando}>
          {session.entrando ? 'Ingresando…' : 'Ingresar'}
        </button>
      </form>
    {/if}

    <p class="owner-note">Software de <b>SIAR</b></p>
  </div>
</div>

<style>
  .stage {
    display: grid;
    min-height: 100dvh;
    place-items: center;
    padding: 1.5rem;
  }

  .card {
    width: min(28rem, 100%);
    border: 1px solid var(--hairline);
    border-radius: var(--radius-xl);
    background: var(--surface-2);
    padding: 1.75rem;
    box-shadow: var(--shadow);
  }

  .owner {
    display: flex;
    justify-content: center;
    border-bottom: 1px solid var(--rule);
    padding-bottom: 1.25rem;
  }
  .owner img {
    width: 148px;
    height: auto;
    border-radius: var(--radius);
    /* Transparente en claro; en oscuro, una placa para no teñir la marca. */
    background: var(--logo-plate);
    padding: 6px 10px;
  }

  .owner-note {
    margin: 1.1rem 0 0;
    text-align: center;
    font-size: var(--text-xs);
    letter-spacing: 0.02em;
    color: var(--muted);
  }
  .owner-note b {
    font-weight: 600;
    color: var(--ink-2);
  }

  header {
    display: flex;
    align-items: center;
    gap: 0.85rem;
    border-top: 1px solid var(--rule);
    border-bottom: 1px solid var(--rule);
    margin-top: 1.25rem;
    padding: 1.1rem 0;
  }
  .mark {
    width: 34px;
    height: 34px;
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
    font-size: var(--text-lg);
    font-weight: 650;
    letter-spacing: -0.015em;
  }
  header p {
    margin: 0.1rem 0 0;
    font-size: var(--text-xs);
    color: var(--muted);
  }

  form {
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
    margin-top: 1.25rem;
  }
  label {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
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
  .wide {
    margin-top: 0.2rem;
  }

  .resume {
    margin-top: 1.25rem;
  }
  .lead {
    margin: 0;
    font-size: var(--text-lg);
  }
  .muted {
    margin: 0.35rem 0 0;
    font-size: var(--text-sm);
    line-height: 1.5;
    color: var(--muted);
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-top: 1.1rem;
  }

</style>
