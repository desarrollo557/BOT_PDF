<script lang="ts">
  import { RESULTADOS, type Resultado } from '$lib/habilidades';
  import type { TaskKind } from '$lib/types';
  import ChoiceCard from './ChoiceCard.svelte';
  import StepFrame from './StepFrame.svelte';

  interface Props {
    resultado: TaskKind;
    onElegir: (r: TaskKind) => void;
    disabled?: boolean;
    numero?: number;
    /** Las acciones de la habilidad, si no son las tres de siempre. */
    opciones?: Resultado[];
  }

  let {
    resultado,
    onElegir,
    disabled = false,
    numero = 3,
    opciones = RESULTADOS
  }: Props = $props();
</script>

<StepFrame
  number={numero}
  title="Qué necesitas de vuelta"
  description="Elige qué produce el sistema con este documento."
  note="Con «Solo el inventario» el PDF original queda intacto y sólo se genera el Excel."
>
  <div class="grid" role="radiogroup" aria-label="Resultado">
    {#each opciones as option (option.id)}
      <ChoiceCard
        title={option.label}
        description={option.hint}
        selected={resultado === option.id}
        {disabled}
        onselect={() => onElegir(option.id)}
      />
    {/each}
  </div>
</StepFrame>

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 15rem), 1fr));
    gap: var(--wz-space-3, 12px);
  }
</style>
