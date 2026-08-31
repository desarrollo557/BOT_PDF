<script lang="ts">
  import FolderPicker from '$lib/components/FolderPicker.svelte';
  import { jobStore } from '$lib/jobs.svelte';
  import type { SourceDisposition } from '$lib/types';

  /**
   * Clean a pasted path in the field itself.
   *
   * Windows Explorer's "Copiar como ruta" wraps the path in double quotes, and
   * that is how most people get a path onto the clipboard. The service strips
   * them too, but doing it here as well means the operator sees the path that
   * is actually going to be used instead of wondering why it worked anyway.
   */
  const QUOTES = `"'“”‘’«»`;

  function cleanPath(raw: string): string {
    let value = raw.trim();
    while (value.length >= 2 && QUOTES.includes(value[0]) && QUOTES.includes(value.at(-1)!)) {
      value = value.slice(1, -1).trim();
    }
    return value;
  }

  let source = $state('');
  let destination = $state('');
  let disposition = $state<SourceDisposition>('leave');
  let watch = $state(false);
  let starting = $state(false);
  let error = $state<string | null>(null);

  /** Which field the folder browser is filling, or null when it is closed. */
  let picking = $state<'origen' | 'destino' | null>(null);

  /**
   * Abre el explorador de la aplicación, no el de Windows.
   *
   * El de Windows no se puede vestir: es una ventana del sistema, dibujada por
   * Windows con la apariencia de Windows, y aparecía como un cuerpo extraño en
   * medio de la pantalla. Éste recorre el mismo disco -- las carpetas las lista
   * el servicio, que corre en esta máquina -- y devuelve la misma ruta
   * absoluta, con los estilos de la página. El de Windows sigue a un clic,
   * dentro, para quien lo prefiera.
   */
  function choose(which: 'origen' | 'destino') {
    error = null;
    picking = which;
  }

  const DISPOSITIONS: { id: SourceDisposition; label: string; hint: string }[] = [
    { id: 'leave', label: 'Dejarlo', hint: 'el original no se toca' },
    { id: 'move', label: 'Apartarlo', hint: 'se mueve a _procesados' },
    { id: 'delete', label: 'Borrarlo', hint: 'se elimina del origen' }
  ];

  const ready = $derived(cleanPath(source).length > 0 && cleanPath(destination).length > 0);

  async function start() {
    error = null;
    starting = true;
    try {
      await jobStore.startFolder({
        source: cleanPath(source),
        destination: cleanPath(destination),
        disposition,
        watch
      });
    } catch (problem) {
      error = (problem as Error).message;
    } finally {
      starting = false;
    }
  }
</script>

<div class="panel">
  <p class="lead">
    El servicio lee y escribe carpetas de <b>esta máquina</b>. No se sube nada: toma un PDF por
    vez, lo separa y deja las resoluciones en el destino.
  </p>

  <div class="field">
    <span class="label">Carpeta de origen</span>
    <div class="control">
      <input
        type="text"
        spellcheck="false"
        placeholder={String.raw`C:\Users\usuario\Desktop\ENTRADA`}
        bind:value={source}
        onpaste={(event) => {
          event.preventDefault();
          source = cleanPath(event.clipboardData?.getData('text') ?? '');
        }}
        onblur={() => (source = cleanPath(source))}
      />
      <button
        type="button"
        class="pick"
        onclick={() => choose('origen')}
        title="Elegir la carpeta de origen"
        aria-label="Elegir la carpeta de origen"
      >
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path
            d="M2 4.2A1.2 1.2 0 0 1 3.2 3h3l1.4 1.6h5.2A1.2 1.2 0 0 1 14 5.8v6A1.2 1.2 0 0 1 12.8 13H3.2A1.2 1.2 0 0 1 2 11.8V4.2Z"
          />
        </svg>
      </button>
    </div>
    <small>Elíjala con el icono, o pegue la ruta. Si trae comillas, se quitan solas.</small>
  </div>

  <div class="field">
    <span class="label">Carpeta de destino</span>
    <div class="control">
      <input
        type="text"
        spellcheck="false"
        placeholder={String.raw`C:\Users\usuario\Desktop\SALIDA`}
        bind:value={destination}
        onpaste={(event) => {
          event.preventDefault();
          destination = cleanPath(event.clipboardData?.getData('text') ?? '');
        }}
        onblur={() => (destination = cleanPath(destination))}
      />
      <button
        type="button"
        class="pick"
        onclick={() => choose('destino')}
        title="Elegir la carpeta de destino"
        aria-label="Elegir la carpeta de destino"
      >
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path
            d="M2 4.2A1.2 1.2 0 0 1 3.2 3h3l1.4 1.6h5.2A1.2 1.2 0 0 1 14 5.8v6A1.2 1.2 0 0 1 12.8 13H3.2A1.2 1.2 0 0 1 2 11.8V4.2Z"
          />
        </svg>
      </button>
    </div>
    <small>Se crea si no existe. No puede estar dentro del origen.</small>
  </div>

  <fieldset>
    <legend class="label">Al terminar cada original</legend>
    <div class="choices">
      {#each DISPOSITIONS as option (option.id)}
        <button
          type="button"
          class:current={disposition === option.id}
          onclick={() => (disposition = option.id)}
        >
          <b>{option.label}</b>
          <small>{option.hint}</small>
        </button>
      {/each}
    </div>
  </fieldset>

  <label class="toggle">
    <input type="checkbox" bind:checked={watch} />
    <span>
      <b>Vigilar la carpeta</b>
      <small>seguir esperando archivos nuevos en vez de terminar al vaciarla</small>
    </span>
  </label>

  {#if error}
    <p class="error">{error}</p>
  {/if}

  <button class="start" onclick={start} disabled={!ready || starting}>
    {starting ? 'iniciando…' : watch ? 'vigilar carpeta' : 'procesar carpeta'}
  </button>
</div>

{#if picking}
  <FolderPicker
    title={picking === 'origen' ? 'Elegir la carpeta de origen' : 'Elegir la carpeta de destino'}
    start={picking === 'origen' ? cleanPath(source) : cleanPath(destination)}
    onpick={(path) => {
      if (picking === 'origen') source = path;
      else destination = path;
      picking = null;
    }}
    onclose={() => (picking = null)}
  />
{/if}

<style>
  .panel {
    display: flex;
    flex-direction: column;
    gap: 0.85rem;
    border: 1px solid color-mix(in oklab, var(--s4) 30%, var(--hairline));
    border-radius: 14px;
    background: var(--plane);
    padding: 1.1rem;
  }

  .lead {
    margin: 0;
    font-size: 0.8rem;
    line-height: 1.5;
    color: var(--muted);
  }
  .lead b {
    color: var(--ink-2);
  }

  label,
  .field {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }

  /* El icono va dentro del recuadro, no al lado: la ruta y el botón que la
     elige son un solo control, y así se lee como uno. */
  .control {
    display: flex;
    align-items: stretch;
    border: 1px solid var(--hairline);
    border-radius: 8px;
    background: var(--surface-2);
    overflow: hidden;
    transition: border-color 0.15s;
  }
  .control:focus-within {
    border-color: var(--s4);
  }
  .control input[type='text'] {
    flex: 1;
    min-width: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
  }
  .pick {
    display: grid;
    flex-shrink: 0;
    place-items: center;
    width: 34px;
    border: 0;
    border-left: 1px solid var(--hairline);
    background: var(--plane);
    cursor: pointer;
    transition: background 0.15s;
  }
  .pick:hover:not(:disabled) {
    background: color-mix(in oklab, var(--s4) 16%, var(--plane));
  }
  .pick:disabled {
    cursor: progress;
    opacity: 0.5;
  }
  .pick svg {
    width: 16px;
    height: 16px;
    fill: var(--s4);
  }

  .label {
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.055em;
    text-transform: uppercase;
    color: var(--muted);
  }

  input[type='text'] {
    border: 1px solid var(--hairline);
    border-radius: 8px;
    background: var(--surface-2);
    padding: 0.45rem 0.65rem;
    font-family: var(--font-mono);
    font-size: 0.78rem;
    color: inherit;
    outline: none;
  }
  input[type='text']:focus {
    border-color: var(--s4);
  }

  small {
    font-size: 0.7rem;
    color: var(--muted);
  }

  fieldset {
    margin: 0;
    border: 0;
    padding: 0;
  }
  legend {
    margin-bottom: 0.3rem;
    padding: 0;
  }

  .choices {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 4px;
  }
  .choices button {
    display: flex;
    flex-direction: column;
    gap: 1px;
    border: 1px solid var(--hairline);
    border-radius: 8px;
    background: var(--surface-2);
    padding: 0.4rem 0.5rem;
    font: inherit;
    text-align: left;
    color: var(--muted);
    cursor: pointer;
    transition:
      border-color 0.15s,
      color 0.15s;
  }
  .choices button b {
    font-size: 0.78rem;
    font-weight: 600;
  }
  .choices button.current {
    border-color: var(--s4);
    color: var(--ink);
  }

  .toggle {
    flex-direction: row;
    align-items: flex-start;
    gap: 0.55rem;
    cursor: pointer;
  }
  .toggle input {
    margin-top: 0.2rem;
    accent-color: var(--s4);
  }
  .toggle span {
    display: flex;
    flex-direction: column;
  }
  .toggle b {
    font-size: 0.8rem;
    font-weight: 600;
  }

  .error {
    margin: 0;
    border-left: 2px solid var(--critical);
    padding-left: 0.6rem;
    font-size: 0.8rem;
    color: var(--critical);
  }

  .start {
    border: 1px solid var(--s4);
    border-radius: 9px;
    background: color-mix(in oklab, var(--s4) 12%, transparent);
    padding: 0.55rem;
    font-family: var(--font-mono);
    font-size: 0.78rem;
    color: var(--ink);
    cursor: pointer;
    transition:
      background 0.15s,
      opacity 0.15s;
  }
  .start:hover:not(:disabled) {
    background: color-mix(in oklab, var(--s4) 22%, transparent);
  }
  .start:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
</style>
