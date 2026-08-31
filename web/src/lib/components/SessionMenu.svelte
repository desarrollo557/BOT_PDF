<script lang="ts">
  import { formatDuration } from '$lib/format';
  import { jobStore } from '$lib/jobs.svelte';
  import { session } from '$lib/session.svelte';

  let open = $state(false);
  let confirming = $state(false);
  let alsoClear = $state(false);
  let busy = $state(false);
  let error = $state<string | null>(null);

  const running = $derived(jobStore.inFlight.length);
  const onScreen = $derived(jobStore.finished.length);

  /** Initials, so the trigger stays a chip rather than a whole name. */
  const initials = $derived(
    (session.name ?? '?')
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase() ?? '')
      .join('')
  );

  async function close() {
    busy = true;
    error = null;
    try {
      // Handing over a screen full of someone else's work is its own kind of
      // confusion, so leaving may clear it -- but never the files, and never
      // without being asked.
      if (alsoClear) await jobStore.clear();
      session.close();
      open = false;
      confirming = false;
    } catch (problem) {
      error = (problem as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<div class="menu">
  <button
    class="trigger"
    onclick={() => {
      open = !open;
      confirming = false;
    }}
    aria-expanded={open}
    title={session.name ?? ''}
  >
    <span class="avatar">{initials}</span>
    <span class="who">{session.name}</span>
    <span class="chevron" aria-hidden="true">▾</span>
  </button>

  {#if open}
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <div class="scrim" role="presentation" onclick={() => (open = false)}></div>

    <div class="sheet" role="dialog" aria-label="Sesión">
      <header>
        <span class="avatar big">{initials}</span>
        <div>
          <b>{session.name}</b>
          {#if session.operator?.station}
            <small>{session.operator.station}</small>
          {/if}
        </div>
      </header>

      <dl>
        <div>
          <dt>En sesión</dt>
          <dd class="tabular">{formatDuration(session.elapsedSeconds)}</dd>
        </div>
        <div>
          <dt>Desde</dt>
          <dd class="tabular">
            {session.operator
              ? new Date(session.operator.startedAt).toLocaleTimeString('es', {
                  hour: '2-digit',
                  minute: '2-digit'
                })
              : '—'}
          </dd>
        </div>
      </dl>

      <p class="note">
        El nombre viaja con cada documento que procese y queda en el archivo. No restringe
        nada: no hay contraseña detrás.
      </p>

      {#if confirming}
        <div class="confirm">
          {#if running}
            <p class="warn">
              Hay {running} documento{running === 1 ? '' : 's'} en proceso. Cerrar la sesión
              <b>no los detiene</b> — el servicio sigue trabajando.
            </p>
          {/if}

          {#if onScreen}
            <label class="check">
              <input type="checkbox" bind:checked={alsoClear} />
              <span>
                Limpiar también la pantalla ({onScreen} documento{onScreen === 1 ? '' : 's'})
                <small>Los PDF generados y el archivo se conservan.</small>
              </span>
            </label>
          {/if}

          {#if error}<p class="bad">{error}</p>{/if}

          <div class="actions">
            <button class="danger" onclick={close} disabled={busy}>
              {busy ? 'cerrando…' : 'Sí, cerrar sesión'}
            </button>
            <button class="ghost" onclick={() => (confirming = false)} disabled={busy}>
              Cancelar
            </button>
          </div>
        </div>
      {:else}
        <button class="ghost wide" onclick={() => (confirming = true)}>Cerrar sesión</button>
      {/if}
    </div>
  {/if}
</div>

<style>
  .menu {
    position: relative;
  }

  .trigger {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    border: 1px solid var(--hairline);
    border-radius: 999px;
    background: var(--surface-2);
    padding: 0.2rem 0.55rem 0.2rem 0.2rem;
    font: inherit;
    font-size: 0.8rem;
    color: var(--ink-2);
    cursor: pointer;
    transition: border-color 0.15s;
  }
  .trigger:hover {
    border-color: var(--accent);
  }

  .avatar {
    display: grid;
    width: 22px;
    height: 22px;
    place-items: center;
    border-radius: 50%;
    background: var(--accent-soft);
    font-family: var(--font-mono);
    font-size: 0.64rem;
    font-weight: 600;
    color: var(--accent);
  }
  .avatar.big {
    width: 34px;
    height: 34px;
    font-size: 0.85rem;
  }

  .who {
    max-width: 10rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .chevron {
    color: var(--muted);
  }

  .scrim {
    position: fixed;
    inset: 0;
    z-index: 60;
  }

  .sheet {
    position: absolute;
    top: calc(100% + 0.5rem);
    right: 0;
    z-index: 61;
    width: 19rem;
    border: 1px solid var(--hairline);
    border-radius: 12px;
    background: var(--surface-2);
    padding: 0.9rem;
    box-shadow: 0 18px 48px rgb(0 0 0 / 0.28);
  }

  .sheet header {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    border-bottom: 1px solid var(--rule);
    padding-bottom: 0.75rem;
  }
  .sheet header b {
    display: block;
    font-size: 0.9rem;
    font-weight: 650;
  }
  .sheet header small {
    font-size: 0.74rem;
    color: var(--muted);
  }

  dl {
    display: flex;
    gap: 1.5rem;
    margin: 0.8rem 0;
  }
  dt {
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.055em;
    text-transform: uppercase;
    color: var(--muted);
  }
  dd {
    margin: 0.1rem 0 0;
    font-family: var(--font-mono);
    font-size: 0.85rem;
  }

  .note {
    margin: 0 0 0.85rem;
    border-left: 2px solid var(--rule);
    padding-left: 0.6rem;
    font-size: 0.74rem;
    line-height: 1.5;
    color: var(--muted);
  }

  .confirm {
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
  }
  .warn {
    margin: 0;
    border-left: 2px solid var(--warning);
    padding-left: 0.6rem;
    font-size: 0.78rem;
    line-height: 1.45;
    color: var(--ink-2);
  }
  .bad {
    margin: 0;
    font-size: 0.78rem;
    color: var(--critical);
  }

  .check {
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    font-size: 0.8rem;
    cursor: pointer;
  }
  .check input {
    margin-top: 0.15rem;
    accent-color: var(--accent);
  }
  .check small {
    display: block;
    font-size: 0.72rem;
    color: var(--muted);
  }

  .actions {
    display: flex;
    gap: 0.45rem;
  }

  .ghost,
  .danger {
    border: 1px solid var(--hairline);
    border-radius: 8px;
    background: transparent;
    padding: 0.4rem 0.8rem;
    font: inherit;
    font-size: 0.82rem;
    color: var(--muted);
    cursor: pointer;
    transition:
      color 0.15s,
      border-color 0.15s,
      background 0.15s;
  }
  .ghost:hover {
    border-color: var(--accent);
    color: var(--accent);
  }
  .ghost.wide {
    width: 100%;
  }
  .danger {
    border-color: var(--critical);
    color: var(--critical);
  }
  .danger:hover {
    background: var(--critical);
    color: #fff;
  }
  button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
