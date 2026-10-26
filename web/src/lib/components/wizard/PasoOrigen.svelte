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
    /** El tipo de documento de la caja (Afinia / Kingspan / mixto). */
    tipoDocumento?: string;
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
    /** La habilidad elegida, para que la carpeta diga si lo que trae coincide. */
    habilidadId?: string;
    /** Cambiar a la habilidad que sugiere lo reconocido en la carpeta. */
    onusarHabilidad?: (id: string) => void;
    blockedLectura: string | null;
    numero?: number;
    /** Cuántos archivos a la vez; cero es el automático. */
    paralelo?: number;
    onParalelo?: (valor: number) => void;
    /** El tope: los procesos del servicio. Cero si aún no se sabe. */
    maximoEnParalelo?: number;
    /** Cuántos van a la vez en automático. */
    automaticoEnParalelo?: number;
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
    tipoDocumento,
    disabled = false,
    onfiles,
    blocked,
    blockedLectura,
    numero = 2,
    habilidadId = 'auto',
    onusarHabilidad,
    paralelo = 0,
    onParalelo,
    maximoEnParalelo = 0,
    automaticoEnParalelo = 0
  }: Props = $props();

  const SINGLE_LIMIT = 5;

  /**
   * Las cifras que se ofrecen: de uno al tope del servicio, y en la carga
   * individual no más que los documentos que admite.
   */
  const tope = $derived(mode === 'single' ? Math.min(maximoEnParalelo, SINGLE_LIMIT) : maximoEnParalelo);
  const cifras = $derived(Array.from({ length: Math.max(0, tope) }, (_, i) => i + 1));
  /** Una cifra que deja de caber al cambiar de modo vuelve al automático. */
  $effect(() => {
    if (paralelo > tope && tope > 0) onParalelo?.(0);
  });
  const ayudaParalelo = $derived(
    paralelo > 0
      ? `${paralelo} ${paralelo === 1 ? 'archivo' : 'archivos'} a la vez. Más a la vez termina antes, pero carga más el equipo y la IA.`
      : `Lo decide el servicio${automaticoEnParalelo ? ` (${automaticoEnParalelo} a la vez en una carpeta)` : ''}.`
  );


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

  {#if cifras.length > 1}
    <!-- Cuántos archivos a la vez: lo elige el operador antes de procesar, para
         cualquier habilidad. El tope son los procesos del servicio: más no lee
         más rápido, sólo deja archivos esperando. -->
    <div class="panel panel-sm paralelo">
      <div class="paralelo-texto">
        <span class="paralelo-titulo" id="paralelo-titulo">Archivos en paralelo</span>
        <small>{ayudaParalelo}</small>
      </div>
      <div class="segmented" role="radiogroup" aria-labelledby="paralelo-titulo">
        <button
          type="button"
          role="radio"
          aria-checked={paralelo === 0}
          class:current={paralelo === 0}
          onclick={() => onParalelo?.(0)}
        >
          Auto
        </button>
        {#each cifras as cifra (cifra)}
          <button
            type="button"
            role="radio"
            class="cifra tabular"
            aria-checked={paralelo === cifra}
            aria-label={`${cifra} a la vez`}
            class:current={paralelo === cifra}
            onclick={() => onParalelo?.(cifra)}
          >
            {cifra}
          </button>
        {/each}
      </div>
    </div>
  {/if}

  <div class="origen" role="tabpanel">
    {#if mode === 'folder'}
      <FolderPanel
        {task}
        {oracle}
        {lectura}
        {tipo}
        {corte}
        {agrupar}
        {tipoDocumento}
        {habilidadId}
        {onusarHabilidad}
        paralelo={paralelo > 0 ? paralelo : undefined}
      />
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
    gap: var(--space-2);
  }

  /* No se llama `.panel`: ésa es ya la superficie común de app.css, y el
     contenido de la pestaña quedaba metido en una caja con sombra. */
  .origen {
    min-width: 0;
  }

  /* Una franja que es el `.panel` común, como las tarjetas de arriba: a la
     izquierda qué es, a la derecha la cifra. Botones y no un desplegable: el
     menú nativo se pinta claro sobre el tema oscuro y esconde las opciones. */
  .paralelo {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2) var(--space-3);
  }

  .paralelo-texto {
    display: grid;
    gap: 0.15rem;
    min-width: 12rem;
    flex: 1 1 14rem;
  }

  .paralelo-titulo {
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--ink);
  }

  .paralelo-texto small {
    font-size: var(--text-xs);
    color: var(--muted);
  }

  /* Las cifras, cuadradas y del mismo ancho: «1» y «11» no bailan. La elegida
     es la del `.segmented` común, como en cualquier otro control segmentado. */
  .paralelo .segmented > .cifra {
    min-width: 2rem;
    padding-inline: 0.45rem;
    text-align: center;
  }
</style>
