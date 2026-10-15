<script lang="ts">
  import Icono from '$lib/components/Icono.svelte';
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
          {#if session.operator}
            <small>{session.operator.perfilLabel}</small>
          {/if}
        </div>
        <button class="btn btn-icon cerrar" onclick={() => (open = false)} aria-label="Cerrar">
          <Icono nombre="cerrar" />
        </button>
      </header>

      <dl>
        <div>
          <dt class="caps">En sesión</dt>
          <dd class="tabular">{formatDuration(session.elapsedSeconds)}</dd>
        </div>
        <div>
          <dt class="caps">Perfil</dt>
          <dd>{session.operator?.perfilLabel ?? '—'}</dd>
        </div>
        <div>
          <dt class="caps">Cédula</dt>
          <dd class="tabular">{session.cedula ?? '—'}</dd>
        </div>
        <div>
          <dt class="caps">Desde</dt>
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
        Su nombre viaja con cada documento que procese y queda en el archivo. El perfil decide
        qué se le deja hacer, y lo asigna el administrador. No hay contraseña detrás: esto
        identifica, no protege.
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

          {#if error}<p class="inline-error m-0">{error}</p>{/if}

          <div class="actions">
            <button class="btn btn-danger" onclick={close} disabled={busy}>
              {busy ? 'Cerrando…' : 'Sí, cerrar sesión'}
            </button>
            <button class="btn btn-ghost" onclick={() => (confirming = false)} disabled={busy}>
              Cancelar
            </button>
          </div>
        </div>
      {:else}
        <button class="btn btn-block" onclick={() => (confirming = true)}>Cerrar sesión</button>
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
    border-radius: var(--radius-pill);
    background: var(--surface-2);
    padding: 0.2rem 0.55rem 0.2rem 0.2rem;
    font: inherit;
    font-size: var(--text-sm);
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
    font-size: var(--text-2xs);
    font-weight: 600;
    color: var(--accent);
  }
  .avatar.big {
    width: 34px;
    height: 34px;
    font-size: var(--text-md);
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

  /* El velo común de los diálogos: el menú se lee como algo puesto encima
     de la pantalla, y un clic fuera lo cierra. */
  .scrim {
    position: fixed;
    inset: 0;
    z-index: 60;
    background: var(--scrim);
  }

  .sheet {
    position: absolute;
    top: calc(100% + 0.5rem);
    right: 0;
    z-index: 61;
    width: 19rem;
    border: 1px solid var(--hairline);
    border-radius: var(--radius-xl);
    background: var(--surface-2);
    padding: 0.9rem;
    box-shadow: var(--shadow-lg);
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
    font-size: var(--text-md);
    font-weight: 650;
  }
  .sheet header small {
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .sheet header .cerrar {
    flex-shrink: 0;
    margin-left: auto;
  }

  dl {
    display: flex;
    gap: 1.5rem;
    margin: 0.8rem 0;
  }
  dd {
    margin: 0.1rem 0 0;
    font-size: var(--text-md);
  }

  .note {
    margin: 0 0 0.85rem;
    border-left: 2px solid var(--rule);
    padding-left: 0.6rem;
    font-size: var(--text-xs);
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
    font-size: var(--text-sm);
    line-height: 1.45;
    color: var(--ink-2);
  }

  .check {
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    font-size: var(--text-sm);
    cursor: pointer;
  }
  .check input {
    margin-top: 0.15rem;
    accent-color: var(--accent);
  }
  .check small {
    display: block;
    font-size: var(--text-xs);
    color: var(--muted);
  }

  .actions {
    display: flex;
    gap: 0.45rem;
  }
</style>
