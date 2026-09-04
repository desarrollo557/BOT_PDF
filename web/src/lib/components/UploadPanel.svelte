<script lang="ts">
  import Dropzone from '$lib/components/Dropzone.svelte';
  import FolderPanel from '$lib/components/FolderPanel.svelte';
  import type { TaskKind } from '$lib/types';

  interface Props {
    /** Called with the chosen files, whether they travel as a batch, and what to do with them. */
    onfiles: (files: File[], asBatch: boolean, task: TaskKind) => void;
    disabled?: boolean;
  }

  let { onfiles, disabled = false }: Props = $props();

  /**
   * The ceiling on a single upload. Not a technical limit -- the batch mode has
   * none -- but the line between "I am splitting these five documents" and "I am
   * running a job", which want different screens and different pacing.
   */
  const SINGLE_LIMIT = 5;

  type Mode = 'single' | 'batch' | 'folder';
  let mode = $state<Mode>('single');

  /**
   * Qué hacer con el documento. Es la primera decisión y no la última: un libro
   * empastado de diplomas no se parte, se inventaría, y preguntarlo después de
   * elegir los archivos obligaría a volver atrás.
   */
  let task = $state<TaskKind>('split');
  let notice = $state<string | null>(null);

  const MODES: { id: Mode; label: string; hint: string }[] = [
    { id: 'single', label: 'Carga individual', hint: `hasta ${SINGLE_LIMIT} documentos` },
    { id: 'batch', label: 'Carga por lotes', hint: 'sin límite de cantidad' },
    { id: 'folder', label: 'Carpeta local', hint: 'sin subir nada' }
  ];

  const TASKS: { id: TaskKind; label: string; hint: string }[] = [
    {
      id: 'split',
      label: 'Dividir en documentos',
      hint: 'un PDF por cada unidad documental'
    },
    {
      id: 'inventory',
      label: 'Solo inventariar',
      hint: 'el original queda entero; se produce el FUID'
    },
    {
      id: 'both',
      label: 'Dividir e inventariar',
      hint: 'las dos cosas, sobre una sola lectura'
    }
  ];

  function receive(files: File[]) {
    notice = null;
    if (mode === 'batch') {
      onfiles(files, true, task);
      return;
    }
    if (files.length > SINGLE_LIMIT) {
      // Never silently drop the rest: the operator would believe they were
      // queued. Say what happened and point at the mode that takes them.
      notice = `La carga individual admite ${SINGLE_LIMIT} documentos. Cambie a carga por lotes para subir los ${files.length}.`;
      return;
    }
    onfiles(files, false, task);
  }
</script>

<section class="panel" data-mode={mode} data-task={task}>
  <div class="task" role="radiogroup" aria-label="Qué hacer con el documento">
    {#each TASKS as option (option.id)}
      <button
        type="button"
        role="radio"
        aria-checked={task === option.id}
        class:current={task === option.id}
        onclick={() => {
          task = option.id;
          notice = null;
        }}
      >
        <b>{option.label}</b>
        <small>{option.hint}</small>
      </button>
    {/each}
  </div>

  {#if task !== 'split'}
    <p class="explains">
      El sistema reconoce por sí mismo qué tipo de documento es —resolución o registro de
      diplomas— por lo que está impreso en sus páginas, y levanta el inventario con la plantilla y
      las columnas que a ese tipo le corresponden.
      {#if task === 'inventory'}
        No se escribe ningún PDF: el original queda entero.
      {:else}
        Se leen las páginas una sola vez, y de esa lectura salen tanto los PDF como el FUID.
      {/if}
    </p>
  {/if}

  <div class="switch" role="tablist" aria-label="Modo de carga">
    {#each MODES as option (option.id)}
      <button
        type="button"
        role="tab"
        aria-selected={mode === option.id}
        class:current={mode === option.id}
        onclick={() => {
          mode = option.id;
          notice = null;
        }}
      >
        <b>{option.label}</b>
        <small>{option.hint}</small>
      </button>
    {/each}
  </div>

  {#if mode === 'folder'}
    <FolderPanel {task} />
  {:else}
    <Dropzone onfiles={receive} {disabled} variant={mode} limit={SINGLE_LIMIT} />
  {/if}

  {#if notice}
    <p class="notice">{notice}</p>
  {/if}
</section>

<style>
  .panel {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  /* La acción se elige primero y se ve como una decisión distinta del modo de
     carga: dos botones anchos, no tres pestañas. */
  .task {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 4px;
    border: 1px solid var(--hairline);
    border-radius: 12px;
    background: var(--plane);
    padding: 4px;
  }

  .task button,
  .switch button {
    display: flex;
    flex-direction: column;
    gap: 1px;
    border: 1px solid transparent;
    border-radius: 9px;
    background: transparent;
    padding: 0.5rem 0.85rem;
    font: inherit;
    text-align: left;
    color: var(--muted);
    cursor: pointer;
    transition:
      background 0.16s,
      color 0.16s,
      border-color 0.16s;
  }
  .task button:hover,
  .switch button:hover {
    color: var(--ink-2);
  }
  .task button.current,
  .switch button.current {
    border-color: var(--hairline);
    background: var(--surface-2);
    box-shadow: var(--shadow);
    color: var(--ink);
  }

  .task b,
  .switch b {
    font-size: 0.8rem;
    font-weight: 600;
  }
  .task small,
  .switch small {
    font-family: var(--font-mono);
    font-size: 0.68rem;
    color: var(--muted);
  }

  .switch {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 4px;
    border: 1px solid var(--hairline);
    border-radius: 12px;
    background: var(--plane);
    padding: 4px;
  }

  /* Inventariar no produce archivos, así que la acción activa se marca con un
     acento distinto: se ve de reojo que esta carga no va a partir nada. */
  [data-task='inventory'] .task button.current {
    border-color: color-mix(in oklab, var(--s2) 45%, var(--hairline));
  }
  [data-task='both'] .task button.current {
    border-color: color-mix(in oklab, var(--s3) 45%, var(--hairline));
  }

  /* Batch mode is a different job, so it gets a different accent on the rail
     that marks the active tab -- the styling says which mode you are in even
     when the labels are out of the corner of your eye. */
  [data-mode='batch'] .switch button.current {
    border-color: color-mix(in oklab, var(--s3) 40%, var(--hairline));
  }
  [data-mode='folder'] .switch button.current {
    border-color: color-mix(in oklab, var(--s4) 40%, var(--hairline));
  }

  .explains {
    margin: 0;
    border-left: 2px solid color-mix(in oklab, var(--s2) 45%, var(--hairline));
    padding-left: 0.65rem;
    font-size: 0.82rem;
    color: var(--ink-2);
  }

  .notice {
    margin: 0;
    border-left: 2px solid var(--warning);
    padding-left: 0.65rem;
    font-size: 0.82rem;
    color: var(--ink-2);
  }
</style>
