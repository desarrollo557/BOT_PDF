<script lang="ts">
  import { browseFolders, PickerUnavailable, pickFolderNatively } from '$lib/api';
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
  <div class="sheet" role="dialog" aria-modal="true" aria-label={title}>
    <header>
      <div class="who">
        <span class="badge">Carpeta</span>
        <h2>{title}</h2>
      </div>
      <button class="close" onclick={onclose} aria-label="Cerrar">✕</button>
    </header>

    <nav class="crumbs" aria-label="Ruta actual">
      <button class="crumb root" onclick={() => go(null)} title="Equipos y unidades">
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path
            d="M2 4.2A1.2 1.2 0 0 1 3.2 3h3l1.4 1.6h5.2A1.2 1.2 0 0 1 14 5.8v6A1.2 1.2 0 0 1 12.8 13H3.2A1.2 1.2 0 0 1 2 11.8V4.2Z"
          />
        </svg>
      </button>
      {#each crumbs as crumb (crumb.path)}
        <span class="sep" aria-hidden="true">›</span>
        <button class="crumb" onclick={() => go(crumb.path)}>{crumb.label}</button>
      {/each}
    </nav>

    <div class="panes">
      <!-- Los sitios a los que siempre se quiere volver, fijos a la izquierda. -->
      <aside>
        <span class="rail-label">Accesos</span>
        {#each drives as drive (drive.path)}
          <button
            class="shortcut"
            class:current={path === drive.path}
            onclick={() => go(drive.path)}
            title={drive.path}
          >
            <svg class="icon" viewBox="0 0 16 16" aria-hidden="true">
              <path
                d="M2 4.2A1.2 1.2 0 0 1 3.2 3h3l1.4 1.6h5.2A1.2 1.2 0 0 1 14 5.8v6A1.2 1.2 0 0 1 12.8 13H3.2A1.2 1.2 0 0 1 2 11.8V4.2Z"
              />
            </svg>
            <span class="name">{drive.name}</span>
          </button>
        {/each}
      </aside>

      <div class="list">
        {#if error}
          <p class="error">{error}</p>
        {:else if loading}
          <p class="muted">Leyendo…</p>
        {:else if !path}
          <p class="muted">Elija una unidad o un acceso de la izquierda.</p>
        {:else}
          {#if parent}
            <button class="row up" onclick={() => go(parent)}>
              <span class="icon up-arrow" aria-hidden="true">↰</span>
              <span class="name">Subir un nivel</span>
            </button>
          {/if}
          {#each folders as folder (folder.path)}
            <button class="row" onclick={() => go(folder.path)}>
              <svg class="icon" viewBox="0 0 16 16" aria-hidden="true">
                <path
                  d="M2 4.2A1.2 1.2 0 0 1 3.2 3h3l1.4 1.6h5.2A1.2 1.2 0 0 1 14 5.8v6A1.2 1.2 0 0 1 12.8 13H3.2A1.2 1.2 0 0 1 2 11.8V4.2Z"
                />
              </svg>
              <span class="name">{folder.name}</span>
              <span class="enter" aria-hidden="true">›</span>
            </button>
          {/each}
          {#if !folders.length}
            <p class="muted">Esta carpeta no tiene subcarpetas. Puede usarla tal cual.</p>
          {/if}
        {/if}
      </div>
    </div>

    <div class="chosen">
      <span class="rail-label">Se usará</span>
      <!-- Escribir la ruta sigue estando: es más rápido cuando ya se sabe. -->
      <input
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
      <button class="ghost" onclick={windows} disabled={native}>
        {native ? 'Ventana de Windows abierta…' : 'Usar el explorador de Windows'}
      </button>
      <button class="ghost" onclick={onclose}>Cancelar</button>
      <button class="primary" disabled={!chosen} onclick={() => onpick(chosen)}>
        Usar esta carpeta
      </button>
    </footer>
  </div>
</div>

<style>
  .scrim {
    position: fixed;
    inset: 0;
    z-index: 90;
    display: grid;
    place-items: center;
    background: rgb(0 0 0 / 0.45);
    padding: 1.5rem;
    backdrop-filter: blur(3px);
    animation: fade 0.16s ease-out;
  }

  .sheet {
    display: flex;
    width: min(52rem, 100%);
    max-height: min(82dvh, 44rem);
    flex-direction: column;
    overflow: hidden;
    border: 1px solid var(--hairline);
    border-radius: 16px;
    background: var(--surface-2);
    box-shadow: 0 24px 70px rgb(0 0 0 / 0.35);
    animation: rise 0.18s ease-out;
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
  .badge {
    align-self: flex-start;
    border: 1px solid color-mix(in oklab, var(--s4) 45%, var(--hairline));
    border-radius: 999px;
    padding: 0.1rem 0.6rem;
    font-family: var(--font-mono);
    font-size: 0.64rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--s4);
  }
  header h2 {
    overflow: hidden;
    margin: 0;
    font-size: 1.05rem;
    font-weight: 650;
    letter-spacing: -0.015em;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .close {
    border: 0;
    background: none;
    font-size: 0.9rem;
    color: var(--muted);
    cursor: pointer;
  }
  .close:hover {
    color: var(--ink);
  }

  .crumbs {
    display: flex;
    align-items: center;
    gap: 0.15rem;
    overflow-x: auto;
    border-block: 1px solid var(--hairline);
    background: var(--plane);
    padding: 0.45rem 1.25rem;
    white-space: nowrap;
  }
  .crumb {
    border: 0;
    border-radius: 5px;
    background: none;
    padding: 0.15rem 0.4rem;
    font: inherit;
    font-family: var(--font-mono);
    font-size: 0.76rem;
    color: var(--ink-2);
    cursor: pointer;
  }
  .crumb:hover {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .crumb.root svg {
    display: block;
    width: 15px;
    height: 15px;
    fill: var(--s4);
  }
  .sep {
    font-size: 0.75rem;
    color: var(--axis);
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
    font-size: 0.6rem;
    font-weight: 600;
    letter-spacing: 0.055em;
    text-transform: uppercase;
    color: var(--muted);
  }
  .shortcut {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    border: 0;
    border-radius: 7px;
    background: none;
    padding: 0.35rem 0.45rem;
    font: inherit;
    font-size: 0.8rem;
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
    border-radius: 7px;
    background: none;
    padding: 0.4rem 0.6rem;
    font: inherit;
    font-size: 0.85rem;
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
  .icon {
    width: 17px;
    height: 17px;
    flex-shrink: 0;
    fill: var(--s4);
  }
  .up-arrow {
    display: grid;
    width: 17px;
    place-items: center;
    font-size: 0.9rem;
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
    flex-shrink: 0;
    font-size: 0.85rem;
    color: transparent;
  }

  .muted,
  .error {
    margin: 0.75rem 0.6rem;
    font-size: 0.82rem;
    color: var(--muted);
  }
  .error {
    border-left: 2px solid var(--critical);
    padding-left: 0.6rem;
    color: var(--critical);
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
    border: 1px solid var(--hairline);
    border-radius: 8px;
    background: var(--surface-2);
    padding: 0.4rem 0.6rem;
    font-family: var(--font-mono);
    font-size: 0.76rem;
    color: inherit;
    outline: none;
  }
  .chosen input:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--ring);
  }

  footer {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    border-top: 1px solid var(--hairline);
    padding: 0.75rem 1.25rem;
  }
  .ghost,
  .primary {
    flex-shrink: 0;
    border: 1px solid var(--hairline);
    border-radius: 8px;
    background: transparent;
    padding: 0.4rem 0.8rem;
    font: inherit;
    font-size: 0.82rem;
    color: var(--muted);
    cursor: pointer;
    transition:
      border-color 0.15s,
      color 0.15s;
  }
  .ghost:first-child {
    margin-right: auto;
  }
  .ghost:hover:not(:disabled) {
    border-color: var(--axis);
    color: var(--ink-2);
  }
  .ghost:disabled {
    cursor: progress;
    opacity: 0.6;
  }
  .primary {
    border-color: var(--accent);
    color: var(--accent);
  }
  .primary:hover:not(:disabled) {
    background: var(--accent-soft);
  }
  .primary:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  @keyframes fade {
    from {
      opacity: 0;
    }
  }
  @keyframes rise {
    from {
      opacity: 0;
      transform: translateY(8px);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .scrim,
    .sheet {
      animation: none;
    }
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
