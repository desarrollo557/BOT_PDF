<script lang="ts">
  import { session } from '$lib/session.svelte';

  /**
   * Entry, not authentication.
   *
   * The screen says so out loud rather than implying a security it does not
   * have. Anyone at this machine can type any name; what the name buys is that
   * every document carries who ran it, and that a shift has a boundary.
   */
  let name = $state('');
  let station = $state('');
  let attempted = $state(false);

  const valid = $derived(name.trim().length >= 2);
  const resuming = $derived(session.state === 'idle');

  function submit(event: Event) {
    event.preventDefault();
    attempted = true;
    if (!valid) return;
    session.open(name, station || null);
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
          La sesión de <b>{session.operator.name}</b> quedó inactiva.
        </p>
        <p class="muted">
          Nadie la bloqueó: sólo pasó una hora sin actividad y el sistema dejó de atribuirle
          trabajo. Continúe, o entre con otro nombre.
        </p>
        <div class="actions">
          <button class="primary" onclick={() => session.resume()}>
            Continuar como {session.operator.name}
          </button>
          <button class="ghost" onclick={() => session.close()}>Entrar con otro nombre</button>
        </div>
      </div>
    {:else}
      <form onsubmit={submit}>
        <label>
          <span>Su nombre</span>
          <input
            bind:value={name}
            placeholder="Ana Martínez"
            autocomplete="name"
            spellcheck="false"
            aria-invalid={attempted && !valid}
          />
          {#if attempted && !valid}
            <small class="bad">Escriba al menos dos caracteres.</small>
          {/if}
        </label>

        <label>
          <span>Puesto <i>(opcional)</i></span>
          <input bind:value={station} placeholder="Archivo central" spellcheck="false" />
        </label>

        <button class="primary wide" type="submit" disabled={!valid}>Entrar</button>
      </form>

      <!-- Said plainly, on the screen, so nobody builds a habit on a promise
           the software is not making. -->
      <p class="disclaimer">
        <b>Sin contraseña.</b> Esto no restringe el acceso ni protege nada: identifica quién está
        operando, para que cada documento procesado quede con su nombre y los turnos se puedan
        separar. Cualquiera en este equipo puede entrar con cualquier nombre.
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
