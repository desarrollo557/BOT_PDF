<script lang="ts">
  import { session } from '$lib/session.svelte';

  /**
   * Entrada, no autenticación.
   *
   * Dos datos y ninguno más, que fue lo que pidió el archivo: la cédula y el
   * correo, que son los dos que ya tiene de cada empleado y que nadie tiene que
   * recordar aparte. Sin contraseña, y la pantalla lo dice en vez de insinuar
   * una seguridad que no hay.
   *
   * El perfil no se elige aquí. Lo contesta el servicio a partir del alta que
   * hizo el administrador, y por eso este formulario no tiene dónde escogerlo:
   * un selector de perfil en la pantalla de entrada sería pedirle a cada uno
   * que declare qué se le permite.
   */
  let cedula = $state('');
  let correo = $state('');
  let attempted = $state(false);

  const cedulaValida = $derived(cedula.replace(/\D/g, '').length >= 5);
  const correoValido = $derived(/^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/.test(correo.trim()));
  const valid = $derived(cedulaValida && correoValido);
  const resuming = $derived(session.state === 'idle');

  async function submit(event: Event) {
    event.preventDefault();
    attempted = true;
    if (!valid || session.entrando) return;
    await session.open(cedula, correo);
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
          trabajo. Continúe, o entre con otra cédula.
        </p>
        <div class="actions">
          <button class="primary" onclick={() => session.resume()}>
            Continuar como {session.name}
          </button>
          <button class="ghost" onclick={() => session.close()}>Entrar con otra cédula</button>
        </div>
      </div>
    {:else}
      <form onsubmit={submit}>
        <label>
          <span>Cédula</span>
          <input
            bind:value={cedula}
            placeholder="1 047 382 991"
            inputmode="numeric"
            autocomplete="username"
            spellcheck="false"
            aria-invalid={attempted && !cedulaValida}
          />
          {#if attempted && !cedulaValida}
            <small class="bad">Escriba su número de cédula.</small>
          {/if}
        </label>

        <label>
          <span>Correo</span>
          <input
            bind:value={correo}
            placeholder="nombre@unicartagena.edu.co"
            type="email"
            autocomplete="email"
            spellcheck="false"
            aria-invalid={attempted && !correoValido}
          />
          {#if attempted && !correoValido}
            <small class="bad">Escriba su correo electrónico.</small>
          {/if}
        </label>

        {#if session.error}
          <p class="bad rejected">{session.error}</p>
        {/if}

        <button class="primary wide" type="submit" disabled={!valid || session.entrando}>
          {session.entrando ? 'Entrando…' : 'Entrar'}
        </button>
      </form>

      <!-- Dicho en la pantalla, para que nadie construya una costumbre sobre
           una promesa que el programa no está haciendo. -->
      <p class="disclaimer">
        <b>Sin contraseña.</b> Esto no restringe el acceso ni protege nada frente a quien quiera
        saltárselo: identifica quién está operando, para que cada documento procesado quede con
        su nombre, y aplica el perfil que le asignó el administrador. Quien conozca la cédula y el
        correo de un compañero puede entrar como él.
      </p>
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
    border-radius: 16px;
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
    border-radius: 8px;
    /* Transparente en claro; en oscuro, una placa para no teñir la marca. */
    background: var(--logo-plate);
    padding: 6px 10px;
  }

  .owner-note {
    margin: 1.1rem 0 0;
    text-align: center;
    font-size: 0.72rem;
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
    font-size: 1.05rem;
    font-weight: 650;
    letter-spacing: -0.015em;
  }
  header p {
    margin: 0.1rem 0 0;
    font-size: 0.76rem;
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
  label span {
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.055em;
    text-transform: uppercase;
    color: var(--muted);
  }
  label i {
    font-style: normal;
    font-weight: 400;
    text-transform: none;
    letter-spacing: 0;
  }
  input {
    border: 1px solid var(--hairline);
    border-radius: 9px;
    background: var(--plane);
    padding: 0.55rem 0.75rem;
    font: inherit;
    font-size: 0.92rem;
    color: inherit;
    outline: none;
    transition: border-color 0.15s;
  }
  input:focus {
    border-color: var(--accent);
  }
  input[aria-invalid='true'] {
    border-color: var(--critical);
  }
  .bad {
    font-size: 0.74rem;
    color: var(--critical);
  }
  .rejected {
    margin: 0;
    border: 1px solid var(--critical);
    border-radius: 9px;
    padding: 0.55rem 0.75rem;
    line-height: 1.5;
    background: color-mix(in oklab, var(--critical) 10%, transparent);
  }

  .primary {
    border: 1px solid var(--accent);
    border-radius: 9px;
    background: var(--accent-soft);
    padding: 0.55rem 1rem;
    font: inherit;
    font-size: 0.88rem;
    font-weight: 600;
    color: var(--accent);
    cursor: pointer;
    transition:
      background 0.15s,
      opacity 0.15s;
  }
  .primary:hover:not(:disabled) {
    background: color-mix(in oklab, var(--accent) 20%, transparent);
  }
  .primary:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
  .wide {
    margin-top: 0.2rem;
    width: 100%;
  }

  .ghost {
    border: 1px solid var(--hairline);
    border-radius: 9px;
    background: transparent;
    padding: 0.55rem 1rem;
    font: inherit;
    font-size: 0.85rem;
    color: var(--muted);
    cursor: pointer;
  }
  .ghost:hover {
    border-color: var(--accent);
    color: var(--accent);
  }

  .resume {
    margin-top: 1.25rem;
  }
  .lead {
    margin: 0;
    font-size: 0.95rem;
  }
  .muted {
    margin: 0.35rem 0 0;
    font-size: 0.82rem;
    line-height: 1.5;
    color: var(--muted);
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-top: 1.1rem;
  }

  .disclaimer {
    margin: 1.25rem 0 0;
    border-top: 1px solid var(--rule);
    padding-top: 0.9rem;
    font-size: 0.76rem;
    line-height: 1.55;
    color: var(--muted);
  }
  .disclaimer b {
    color: var(--ink-2);
  }
</style>
