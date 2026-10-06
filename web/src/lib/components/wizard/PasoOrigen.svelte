<script lang="ts">
  import Dropzone from '$lib/components/Dropzone.svelte';
  import FolderPanel from '$lib/components/FolderPanel.svelte';
  import type {
    AgruparChoice,
    CorteChoice,
    LecturaChoice,
    OracleChoice,
    TipoPedido
  } from '$lib/tipos';
  import type { TaskKind } from '$lib/types';
  import Callout from './Callout.svelte';
  import ChoiceCard from './ChoiceCard.svelte';
  import StepFrame from './StepFrame.svelte';

  type Mode = 'single' | 'batch' | 'folder';

  interface Props {
    mode: Mode;
    onCambiar: (m: Mode) => void;
    task: TaskKind;
    oracle: OracleChoice;
    lectura: LecturaChoice;
    tipo: TipoPedido;
    corte: CorteChoice;
    agrupar: AgruparChoice;
    disabled?: boolean;
    onfiles: (
      files: File[],
      asBatch: boolean,
      task: TaskKind,
      oracle: OracleChoice,
      lectura: LecturaChoice,
      tipo: TipoPedido,
      corte: CorteChoice,
      agrupar: AgruparChoice
    ) => void;
    blocked: string | null;
    blockedLectura: string | null;
    numero?: number;
  }

  let {
    mode,
    onCambiar,
    task,
    oracle,
    lectura,
    tipo,
    corte,
    agrupar,
    disabled = false,
    onfiles,
    blocked,
    blockedLectura,
    numero = 2
  }: Props = $props();

  const SINGLE_LIMIT = 5;

  const MODES: { id: Mode; label: string; hint: string }[] = [
    { id: 'single', label: 'Carga individual', hint: `Hasta ${SINGLE_LIMIT} documentos` },
    { id: 'batch', label: 'Carga por lote', hint: 'Sin límite de cantidad' },
    { id: 'folder', label: 'Carpeta local', hint: 'Se procesa en el equipo, sin subir nada' }
  ];

  /**
   * The parent decides what to do with the files -- check blocks, enforce the
   * single-upload limit, stage them for review -- so its notices are shown in
   * one place. Here they are only handed over with the choices of this run.
   */
  function recibirArchivos(files: File[]) {
    onfiles(files, mode === 'batch', task, oracle, lectura, tipo, corte, agrupar);
  }
</script>

<StepFrame
  number={numero}
  title="De dónde salen los archivos"
  description="Sube los PDF desde este equipo o indica una carpeta local para procesarla sin subir nada."
>
  <div class="modes" role="tablist" aria-label="Origen de los archivos">
    {#each MODES as option (option.id)}
      <ChoiceCard
        role="tab"
        compact
        title={option.label}
        description={option.hint}
        selected={mode === option.id}
        onselect={() => onCambiar(option.id)}
      />
    {/each}
  </div>

  <div class="panel" role="tabpanel">
    {#if mode === 'folder'}
      <FolderPanel {task} {oracle} {lectura} {tipo} {corte} {agrupar} />
    {:else}
      <Dropzone
        onfiles={recibirArchivos}
        {disabled}
        variant={mode}
        limit={mode === 'single' ? SINGLE_LIMIT : undefined}
      />
    {/if}
  </div>

  {#if blockedLectura}
    <Callout tone="warning">{blockedLectura}</Callout>
  {/if}
  {#if blocked && task === 'segment'}
    <Callout tone="warning">{blocked}</Callout>
  {/if}
</StepFrame>

<style>
  .modes {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 12rem), 1fr));
    gap: var(--wz-space-2, 8px);
  }

  .panel {
    min-width: 0;
  }
</style>
