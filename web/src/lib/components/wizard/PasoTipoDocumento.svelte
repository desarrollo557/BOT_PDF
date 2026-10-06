<script lang="ts">
  import type { Health } from '$lib/api';
  import { HABILIDADES, motivoNoDisponible } from '$lib/habilidades';
  import Callout from './Callout.svelte';
  import ChoiceCard from './ChoiceCard.svelte';
  import SkillIcon from './SkillIcon.svelte';
  import StepFrame from './StepFrame.svelte';

  interface Props {
    habilidadId: string;
    onElegir: (id: string) => void;
    disabled?: boolean;
    health: Health | null;
    /** Position of this step in the current path. Always 1 today. */
    numero?: number;
  }

  let { habilidadId, onElegir, disabled = false, health, numero = 1 }: Props = $props();

  const noDisponible = $derived(
    habilidadId !== 'auto'
      ? motivoNoDisponible(
          HABILIDADES.find((h) => h.id === habilidadId) ?? HABILIDADES[HABILIDADES.length - 1],
          health
        )
      : null
  );
</script>

<StepFrame
  number={numero}
  title="Qué vas a procesar"
  description="Elige el tipo de papel que tienes en la caja. De esto depende todo lo demás: cómo se corta, cómo se lee y cómo se nombra cada archivo."
  note="Puedes volver a este paso en cualquier momento; el resto de opciones se ajusta solo."
>
  <div class="grid" role="radiogroup" aria-label="Tipo de documento">
    {#each HABILIDADES as option (option.id)}
      {@const motivo = motivoNoDisponible(option, health)}
      <ChoiceCard
        title={option.titulo}
        description={option.papel}
        selected={habilidadId === option.id}
        disabled={motivo !== null || disabled}
        disabledReason={motivo}
        badge={motivo ? 'No disponible' : option.pideLectura ? 'Recomienda IA' : null}
        badgeTone={motivo ? 'warning' : 'accent'}
        onselect={() => onElegir(option.id)}
      >
        {#snippet icon()}
          <SkillIcon id={option.id} />
        {/snippet}
      </ChoiceCard>
    {/each}
  </div>

  {#if noDisponible}
    <Callout tone="warning">{noDisponible}</Callout>
  {/if}
</StepFrame>

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 16rem), 1fr));
    gap: var(--wz-space-3, 12px);
  }
</style>
