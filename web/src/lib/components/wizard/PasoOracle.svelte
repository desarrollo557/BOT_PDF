<script lang="ts">
  import type { OracleChoice } from '$lib/oracles';
  import Callout from './Callout.svelte';
  import ChoiceCard from './ChoiceCard.svelte';
  import StepFrame from './StepFrame.svelte';

  interface Props {
    oracle: OracleChoice;
    onElegir: (o: OracleChoice) => void;
    oracles: Array<{
      id: OracleChoice;
      label: string;
      hint: string;
      available: boolean;
      reason: string | null;
    }>;
    blocked: string | null;
    numero?: number;
  }

  let { oracle, onElegir, oracles, blocked, numero = 5 }: Props = $props();
</script>

<StepFrame
  number={numero}
  title="Modelo para las costuras dudosas"
  description="La caja de correspondencia se corta por continuidad. Las costuras que la estructura no logra decidir se le preguntan a un modelo de IA."
  note="Sin modelo, las costuras dudosas van a revisión. El modelo no cambia el corte: sólo decide si una hoja continúa el documento o abre uno nuevo."
>
  <div class="grid" role="radiogroup" aria-label="Modelo de IA">
    {#each oracles as option (option.id)}
      <ChoiceCard
        title={option.label}
        description={option.hint}
        selected={oracle === option.id}
        disabled={!option.available}
        disabledReason={option.reason ?? 'Falta la llave en el servicio.'}
        onselect={() => onElegir(option.id)}
      />
    {/each}
  </div>

  {#if blocked}
    <Callout tone="warning">{blocked}</Callout>
  {/if}
</StepFrame>

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 15rem), 1fr));
    gap: var(--space-3);
  }
</style>
