<script lang="ts">
  import Dropzone from '$lib/components/Dropzone.svelte';
  import FolderPanel from '$lib/components/FolderPanel.svelte';

  interface Props {
    /** Called with the chosen files and whether they should travel as a batch. */
    onfiles: (files: File[], asBatch: boolean) => void;
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
  let notice = $state<string | null>(null);

  const MODES: { id: Mode; label: string; hint: string }[] = [
    { id: 'single', label: 'Carga individual', hint: `hasta ${SINGLE_LIMIT} documentos` },
    { id: 'batch', label: 'Carga por lotes', hint: 'sin límite de cantidad' },
    { id: 'folder', label: 'Carpeta local', hint: 'sin subir nada' }
  ];

  function receive(files: File[]) {
    notice = null;
    if (mode === 'batch') {
      onfiles(files, true);
      return;
    }
    if (files.length > SINGLE_LIMIT) {
      // Never silently drop the rest: the operator would believe they were
      // queued. Say what happened and point at the mode that takes them.
      notice = `La carga individual admite ${SINGLE_LIMIT} documentos. Cambie a carga por lotes para subir los ${files.length}.`;
      return;
    }
    onfiles(files, false);
  }
</script>

<section class="panel" data-mode={mode}>
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
    <FolderPanel />
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

  .switch {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 4px;
    border: 1px solid var(--hairline);
    border-radius: 12px;
    background: var(--plane);
    padding: 4px;
  }

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
  .switch button:hover {
    color: var(--ink-2);
  }
  .switch button.current {
    border-color: var(--hairline);
    background: var(--surface-2);
    box-shadow: var(--shadow);
    color: var(--ink);
  }

  .switch b {
    font-size: 0.8rem;
    font-weight: 600;
  }
  .switch small {
    font-family: var(--font-mono);
    font-size: 0.68rem;
    color: var(--muted);
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

  .notice {
    margin: 0;
    border-left: 2px solid var(--warning);
    padding-left: 0.65rem;
    font-size: 0.82rem;
    color: var(--ink-2);
  }
</style>
