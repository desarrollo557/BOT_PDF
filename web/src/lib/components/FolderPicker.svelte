<script lang="ts">
  import { browseFolders, PickerUnavailable, pickFolderNatively } from '$lib/api';
  import Icono from '$lib/components/Icono.svelte';
  import type { FolderEntry } from '$lib/types';

  interface Props {
    title: string;
    /** Where to start. The current field value, if it is a real folder. */
    start?: string;
    onpick: (path: string) => void;
    onclose: () => void;
  }

  let { title, start = '', onpick, onclose }: Props = $props();

  /**
   * The listing comes from the service, not the browser.
   *
   * A browser cannot hand over an absolute path -- neither the directory picker
   * nor `webkitdirectory` expose one, by design. The service runs on the same
   * machine as the folders, so it is the one that can answer "what is inside
   * here", and the path it returns is the real one.
   *
   * Windows' own folder dialog is still one click away, but it cannot be
   * themed: it is an operating-system window, drawn by Windows with Windows'
   * chrome. This one is the program's own, so it looks like the program.
   */
  let path = $state<string | null>(null);
  let parent = $state<string | null>(null);
  let drives = $state<FolderEntry[]>([]);
  let folders = $state<FolderEntry[]>([]);
  /** Las que no vinieron: una carpeta con miles se enseña por sus primeras 500. */
  let omitidas = $state(0);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let manual = $state('');
  /** Set while Windows' own dialog is open, so the button can say so. */
  let native = $state(false);

  async function go(target: string | null) {
    loading = true;
    error = null;
    try {
      const listing = await browseFolders(target);
      path = listing.path;
      parent = listing.parent;
      // Las unidades vienen en cada respuesta; sólo se refrescan si traen algo,
      // para que la columna de accesos no parpadee al entrar a una carpeta.
      if (listing.drives.length) drives = listing.drives;
      folders = listing.folders;
      omitidas = listing.omitidas ?? 0;
      manual = listing.path ?? '';
    } catch (problem) {
      error = (problem as Error).message;
    } finally {
      loading = false;
    }
  }

  async function windows() {
    error = null;
    native = true;
    try {
      const chosen = await pickFolderNatively(title, manual.trim() || path || '');
      if (chosen.path) onpick(chosen.path);
    } catch (problem) {
      error =
        problem instanceof PickerUnavailable
          ? 'El explorador de Windows no está disponible; use el de aquí.'
          : (problem as Error).message;
    } finally {
      native = false;
    }
  }

  $effect(() => {
    void go(start || null);
  });

  /** The path split into clickable steps, so going back up is one click. */
  const crumbs = $derived.by(() => {
    if (!path) return [];
    const separator = path.includes('\\') ? '\\' : '/';
    const parts = path.split(separator).filter(Boolean);
    const out: { label: string; path: string }[] = [];
    let walked = '';
    for (const part of parts) {
      walked = walked ? `${walked}${separator}${part}` : `${part}${separator}`;
      out.push({ label: part, path: walked });
    }
    return out;
  });

  const chosen = $derived(manual.trim());
</script>

<svelte:window
  onkeydown={(event) => {
    if (event.key === 'Escape') onclose();
  }}
/>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<div
  class="scrim"
  role="presentation"
  onclick={(event) => {
    if (event.target === event.currentTarget) onclose();
  }}
>
  <div class="panel panel-flush sheet" role="dialog" aria-modal="true" aria-label={title}>
    <header>
      <div class="who">
        <span class="pill pill-neutral tipo">Carpeta</span>
        <h2>{title}</h2>
      </div>
      <button class="btn btn-icon" onclick={onclose} aria-label="Cerrar">
        <Icono nombre="cerrar" />
      </button>
    </header>

    <nav class="crumbs" aria-label="Ruta actual">
      <button
        class="btn btn-ghost btn-sm crumb root"
        onclick={() => go(null)}
        title="Equipos y unidades"
        aria-label="Equipos y unidades"
      >
        <Icono nombre="carpeta" />
      </button>
      {#each crumbs as crumb (crumb.path)}
        <span class="sep" aria-hidden="true"><Icono nombre="chevron" /></span>
        <button class="btn btn-ghost btn-sm crumb" onclick={() => go(crumb.path)}>{crumb.label}</button>
      {/each}
    </nav>

    <div class="panes">
      <!-- Los sitios a los que siempre se quiere volver, fijos a la izquierda. -->
      <aside>
        <span class="caps rail-label">Accesos</span>
        {#each drives as drive (drive.path)}
          <button
            class="shortcut"
            class:current={path === drive.path}
            onclick={() => go(drive.path)}
            title={drive.path}
          >
            <span class="icon"><Icono nombre="carpeta" /></span>
            <span class="name">{drive.name}</span>
          </button>
        {/each}
      </aside>

      <div class="list">
        {#if error}
          <p class="inline-error">{error}</p>
        {:else if loading}
          <p class="muted">Leyendo…</p>
        {:else if !path}
          <p class="empty-state">Elija una unidad o un acceso de la izquierda.</p>
        {:else}
          {#if parent}
            <button class="row up" onclick={() => go(parent)}>
              <span class="icon up-arrow"><Icono nombre="subir" /></span>
              <span class="name">Subir un nivel</span>
            </button>
          {/if}
          {#each folders as folder (folder.path)}
            <button class="row" onclick={() => go(folder.path)}>
              <span class="icon"><Icono nombre="carpeta" /></span>
              <span class="name">{folder.name}</span>
              <span class="enter" aria-hidden="true"><Icono nombre="chevron" /></span>
            </button>
          {/each}
          {#if !folders.length}
            <p class="empty-state">Esta carpeta no tiene subcarpetas. Puede usarla tal cual.</p>
          {/if}
          {#if omitidas > 0}
            <p class="muted">
              Y {omitidas.toLocaleString('es-CO')} carpetas más. Para entrar a una, escriba su ruta
              abajo; para procesarlas todas, use esta carpeta.
            </p>
          {/if}
        {/if}
      </div>
    </div>

    <div class="chosen">
      <span class="caps rail-label">Se usará</span>
      <!-- Escribir la ruta sigue estando: es más rápido cuando ya se sabe. -->
      <input
        class="input input-sm mono"
        bind:value={manual}
        placeholder="…o escriba la ruta completa"
        spellcheck="false"
        aria-label="Ruta elegida"
        onkeydown={(event) => {
          if (event.key === 'Enter' && chosen) onpick(chosen);
        }}
      />
    </div>

    <footer>
      <button class="btn btn-ghost windows" onclick={windows} disabled={native}>
        {native ? 'Ventana de Windows abierta…' : 'Usar el explorador de Windows'}
      </button>
      <button class="btn" onclick={onclose}>Cancelar</button>
      <button class="btn btn-primary" disabled={!chosen} onclick={() => onpick(chosen)}>
        Usar esta carpeta
      </button>
    </footer>
  </div>
</div>

<style>
  /* Un velo plano, sin desenfoque: lo de detrás se apaga, no se vuelve
     vidrio. */
  .scrim {
    position: fixed;
    inset: 0;
    z-index: 90;
    display: grid;
    place-items: center;
    background: var(--scrim);
    padding: 1.5rem;
  }

  /* El `.panel` común sin relleno (cada franja trae el suyo), con el radio y la
     sombra de lo que flota sobre la página. Aparece con la `entrada` común. */
  .sheet {
    display: flex;
    width: min(52rem, 100%);
    max-height: min(82dvh, 44rem);
    flex-direction: column;
    overflow: hidden;
    border-radius: var(--radius-xl);
    box-shadow: var(--shadow-lg);
    animation: entrada var(--duration) var(--ease-out);
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 1rem 1.25rem 0.85rem;
  }
  .who {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 0.25rem;
  }
  .tipo {
    align-self: flex-start;
  }
  header h2 {
    overflow: hidden;
    margin: 0;
    font-size: var(--text-lg);
    font-weight: 650;
    letter-spacing: -0.015em;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .crumbs {
    --icono: 12px;
    display: flex;
    align-items: center;
    gap: 0.15rem;
    overflow-x: auto;
    border-block: 1px solid var(--hairline);
    background: var(--plane);
    padding: 0.45rem 1.25rem;
    white-space: nowrap;
  }
  /* Cada tramo de la ruta es un `.btn-ghost` pequeño; la ruta se lee en la
     letra de los códigos. */
  .crumb {
    padding-inline: 0.4rem;
    font-family: var(--font-mono);
    font-weight: 500;
    color: var(--ink-2);
  }
  .crumb.root {
    --icono: 15px;
  }
  .sep {
    display: grid;
    place-items: center;
    color: var(--muted);
  }

  .panes {
    display: grid;
    min-height: 0;
    flex: 1;
    grid-template-columns: 12rem 1fr;
  }

  aside {
    display: flex;
    overflow-y: auto;
    flex-direction: column;
    gap: 1px;
    border-right: 1px solid var(--hairline);
    padding: 0.6rem 0.5rem;
  }
  .rail-label {
    padding: 0 0.4rem 0.3rem;
  }
  /* Los accesos y las carpetas son filas de un explorador: la fila entera es
     el control, así que no llevan la caja de `.btn`, sólo el fondo al pasar. */
  .shortcut {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    border: 0;
    border-radius: var(--radius-sm);
    background: none;
    padding: 0.35rem 0.45rem;
    font: inherit;
    font-size: var(--text-sm);
    color: var(--ink-2);
    text-align: left;
    cursor: pointer;
  }
  .shortcut:hover {
    background: var(--plane);
    color: var(--ink);
  }
  .shortcut.current {
    background: var(--accent-soft);
    color: var(--accent);
  }

  .list {
    overflow-y: auto;
    padding: 0.5rem;
  }
  .row {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 0.6rem;
    border: 0;
    border-radius: var(--radius-sm);
    background: none;
    padding: 0.4rem 0.6rem;
    font: inherit;
    font-size: var(--text-md);
    color: inherit;
    text-align: left;
    cursor: pointer;
  }
  .row:hover {
    background: var(--plane);
  }
  .row:hover .enter {
    color: var(--accent);
  }
  /* La carpeta en la tinta de la fila (o el acento, si es el acceso elegido),
     no en el amarillo de una serie: las series son sólo para datos. */
  .icon {
    --icono: 17px;
    display: grid;
    flex-shrink: 0;
    place-items: center;
  }
  .up-arrow {
    color: var(--muted);
  }
  .up .name {
    color: var(--muted);
  }
  .name {
    overflow: hidden;
    flex: 1;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .enter {
    --icono: 14px;
    display: grid;
    flex-shrink: 0;
    place-items: center;
    color: transparent;
  }

  .muted {
    margin: 0.75rem 0.6rem;
    font-size: var(--text-sm);
    color: var(--muted);
  }
  .list .inline-error,
  .list .empty-state {
    margin: 0.75rem 0.6rem;
  }

  .chosen {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    border-top: 1px solid var(--hairline);
    background: var(--plane);
    padding: 0.6rem 1.25rem;
  }
  .chosen .rail-label {
    padding: 0;
  }
  .chosen input {
    flex: 1;
    min-width: 8rem;
  }

  footer {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    border-top: 1px solid var(--hairline);
    padding: 0.75rem 1.25rem;
  }
  /* Los botones son los globales; el de Windows se aparta a la izquierda,
     lejos de la acción principal. */
  footer .btn {
    flex-shrink: 0;
  }
  .windows {
    margin-right: auto;
  }

  /* En una pantalla estrecha la columna de accesos estorba más de lo que ayuda. */
  @media (max-width: 44rem) {
    .panes {
      grid-template-columns: 1fr;
    }
    aside {
      flex-direction: row;
      overflow-x: auto;
      border-right: 0;
      border-bottom: 1px solid var(--hairline);
    }
    .rail-label {
      display: none;
    }
  }
</style>
