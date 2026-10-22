<script lang="ts">
  import type { Health } from '$lib/api';
  import { motivoSinAgrupar, type Agrupar, type AgruparChoice } from '$lib/habilidades';
  import Callout from './Callout.svelte';
  import ChoiceCard from './ChoiceCard.svelte';
  import StepFrame from './StepFrame.svelte';

  interface Props {
    agrupar: AgruparChoice;
    onElegir: (a: AgruparChoice) => void;
    agruparElegido: AgruparChoice;
    agrupaciones: Agrupar[];
    health: Health | null;
    pregunta?: string;
    numero?: number;
  }

  let { onElegir, agruparElegido, agrupaciones, health, pregunta, numero = 5 }: Props = $props();

  const elegida = $derived(agrupaciones.find((opcion) => opcion.id === agruparElegido));
</script>

<StepFrame
  number={numero}
  title={pregunta?.replace(/^¿|\?$/g, '') ?? 'Qué va en cada archivo'}
  description="Elige cómo se agrupan las páginas en los archivos de salida."
  note="Esto no cambia el corte: sólo qué páginas van juntas en cada PDF entregado."
>
  <div class="grid" role="radiogroup" aria-label="Agrupación">
    {#each agrupaciones as opcion (opcion.id)}
      {@const motivo = opcion.proximamente
        ? 'Todavía no está disponible.'
        : motivoSinAgrupar(opcion, health)}
      <ChoiceCard
        title={opcion.label}
        description={opcion.agrupa}
        selected={agruparElegido === opcion.id}
        disabled={motivo !== null}
        disabledReason={motivo}
        onselect={() => onElegir(opcion.id)}
      />
    {/each}
  </div>

  {#if elegida?.cuesta}
    <Callout tone="info">{elegida.cuesta}</Callout>
  {/if}
</StepFrame>

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 15rem), 1fr));
    gap: var(--space-3);
  }
</style>
