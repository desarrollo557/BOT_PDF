<script lang="ts">
  import type { CorteChoice } from '$lib/habilidades';
  import Callout from './Callout.svelte';
  import ChoiceCard from './ChoiceCard.svelte';
  import StepFrame from './StepFrame.svelte';

  interface Props {
    cortes: Array<{ id: CorteChoice; label: string; agrupa: string; cuesta: string }>;
    corte: CorteChoice;
    onElegir: (c: CorteChoice) => void;
    corteElegido: CorteChoice;
    pregunta?: string;
    numero?: number;
  }

  let { cortes, onElegir, corteElegido, pregunta, numero = 3 }: Props = $props();

  const elegido = $derived(cortes.find((opcion) => opcion.id === corteElegido));
</script>

<StepFrame
  number={numero}
  title={pregunta?.replace(/^¿|\?$/g, '') ?? 'Por dónde se corta'}
  description="Elige el criterio con que se separa cada documento del libro."
  note="El corte es el mismo con IA o sin ella: la IA sólo ayuda a nombrar los archivos."
>
  {#if cortes.length}
    <div class="grid" role="radiogroup" aria-label="Criterio de corte">
      {#each cortes as opcion (opcion.id)}
        <ChoiceCard
          title={opcion.label}
          description={opcion.agrupa}
          selected={corteElegido === opcion.id}
          onselect={() => onElegir(opcion.id)}
        />
      {/each}
    </div>

    {#if elegido?.cuesta}
      <Callout tone="info">{elegido.cuesta}</Callout>
    {/if}
  {:else}
    <Callout tone="info">Este tipo de documento no tiene criterios de corte que elegir.</Callout>
  {/if}
</StepFrame>

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 15rem), 1fr));
    gap: var(--space-3);
  }
</style>
