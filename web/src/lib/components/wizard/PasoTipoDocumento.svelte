<script lang="ts">
  import { fly } from 'svelte/transition';
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

  /** Agrupa las dos variantes de correspondencia bajo una sola tarjeta expandible. */
  const correspondenciaIds = ['correspondencia', 'kingspan'] as const;
  const esCorrespondencia = (id: string) => correspondenciaIds.includes(id as any);

  /** Habilidades que no son correspondencia (se muestran normal). */
  const otrasHabilidades = $derived(HABILIDADES.filter((h) => !esCorrespondencia(h.id)));

  /** Las dos variantes de correspondencia. */
  const variantesCorrespondencia = $derived(HABILIDADES.filter((h) => esCorrespondencia(h.id)));

  /** Si alguna variante de correspondencia está seleccionada. */
  const correspondenciaSeleccionada = $derived(
    variantesCorrespondencia.some((v) => habilidadId === v.id)
  );

  /** Estado de expansión del grupo de correspondencia. */
  let expandida = $state(false);

  /** Maneja clic en una variante de correspondencia. */
  function elegirVariante(id: string) {
    onElegir(id);
    expandida = false;
  }
</script>

<StepFrame
  number={numero}
  title="Qué vas a procesar"
  description="Elige el tipo de papel que tienes en la caja. De esto depende todo lo demás: cómo se corta, cómo se lee y cómo se nombra cada archivo."
  note="Puedes volver a este paso en cualquier momento; el resto de opciones se ajusta solo."
>
  <div class="grid" role="radiogroup" aria-label="Tipo de documento">
    {#each otrasHabilidades as option (option.id)}
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

    <!-- Grupo Caja de correspondencia (expandible) -->
    <div class="correspondencia-group">
      <button
        type="button"
        class="correspondencia-trigger"
        aria-expanded={expandida}
        aria-controls="correspondencia-opciones"
        onclick={() => (expandida = !expandida)}
        disabled={disabled}
      >
        <div class="trigger-icon">
          <SkillIcon id="correspondencia" />
        </div>
        <div class="trigger-content">
          <span class="trigger-title">Caja de correspondencia</span>
          <span class="trigger-subtitle">
            {correspondenciaSeleccionada
              ? variantesCorrespondencia.find((v) => v.id === habilidadId)?.titulo ?? 'Seleccionada'
              : 'Afinia · Kingspan'}
          </span>
        </div>
        <svg class="chevron" viewBox="0 0 16 16" aria-hidden="true" class:rotated={expandida}>
          <path d="M4.5 5.5 8 9 11.5 5.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>

      {#if expandida}
        <div id="correspondencia-opciones" class="correspondencia-opciones" in:fly={{ y: -8, duration: 150 }}>
          {#each variantesCorrespondencia as option (option.id)}
            {@const motivo = motivoNoDisponible(option, health)}
            <ChoiceCard
              title={option.titulo}
              description={option.papel}
              selected={habilidadId === option.id}
              disabled={motivo !== null || disabled}
              disabledReason={motivo}
              badge={motivo ? 'No disponible' : option.pideLectura ? 'Recomienda IA' : null}
              badgeTone={motivo ? 'warning' : 'accent'}
              onselect={() => elegirVariante(option.id)}
            >
              {#snippet icon()}
                <SkillIcon id={option.id} />
              {/snippet}
            </ChoiceCard>
          {/each}
        </div>
      {/if}
    </div>
  </div>

  {#if noDisponible}
    <Callout tone="warning">{noDisponible}</Callout>
  {/if}
</StepFrame>

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 16rem), 1fr));
    gap: var(--space-3);
  }

  /* Grupo expandible de correspondencia */
  .correspondencia-group {
    grid-column: 1 / -1;
  }

  .correspondencia-trigger {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    width: 100%;
    padding: var(--space-4);
    border: 1px solid var(--hairline);
    border-radius: var(--radius-lg);
    background: var(--surface-2);
    color: var(--ink);
    font: inherit;
    text-align: left;
    cursor: pointer;
    transition: border-color 0.2s, background-color 0.2s, box-shadow 0.2s;
  }

  .correspondencia-trigger:hover:not(:disabled) {
    border-color: var(--accent);
    background: var(--accent-soft);
  }

  .correspondencia-trigger:focus-visible {
    outline: none;
    box-shadow: 0 0 0 3px var(--ring);
    border-color: var(--accent);
  }

  .correspondencia-trigger:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .trigger-icon {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .trigger-content {
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
    min-width: 0;
  }

  .trigger-title {
    font-weight: 600;
    font-size: var(--text-base);
    color: var(--ink);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .trigger-subtitle {
    font-size: var(--text-sm);
    color: var(--muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .chevron {
    flex-shrink: 0;
    width: 20px;
    height: 20px;
    color: var(--muted);
    transition: transform 0.2s ease;
  }

  .chevron.rotated {
    transform: rotate(180deg);
  }

  .correspondencia-opciones {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 16rem), 1fr));
    gap: var(--space-3);
    margin-top: var(--space-3);
    padding: var(--space-3);
    border: 1px dashed var(--rule);
    border-radius: var(--radius-lg);
    background: var(--surface-1);
  }
</style>
