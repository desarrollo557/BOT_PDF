<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icono from '../Icono.svelte';

  /**
   * One selectable option of a wizard step.
   *
   * A disabled card says why in its own body, with a dashed border and a lock,
   * so "unavailable" never relies on a lighter shade of gray alone: an option
   * that looks faded but gives no reason reads as a broken screen.
   */
  interface Props {
    title: string;
    description?: string | null;
    selected?: boolean;
    disabled?: boolean;
    /** Shown inside the card, and as its tooltip, when it is disabled. */
    disabledReason?: string | null;
    badge?: string | null;
    badgeTone?: 'neutral' | 'accent' | 'warning' | 'good';
    /** `radio` inside a radiogroup, `tab` inside a tablist. */
    role?: 'radio' | 'tab';
    compact?: boolean;
    onselect?: () => void;
    icon?: Snippet;
  }

  let {
    title,
    description = null,
    selected = false,
    disabled = false,
    disabledReason = null,
    badge = null,
    badgeTone = 'neutral',
    role = 'radio',
    compact = false,
    onselect,
    icon
  }: Props = $props();
</script>

<button
  type="button"
  class="panel panel-interactive choice"
  class:selected
  class:compact
  class:with-icon={!!icon}
  {role}
  aria-checked={role === 'radio' ? selected : undefined}
  aria-selected={role === 'tab' ? selected : undefined}
  {disabled}
  title={disabled ? (disabledReason ?? undefined) : undefined}
  onclick={() => onselect?.()}
>
  {#if icon}
    <span class="icon" aria-hidden="true">{@render icon()}</span>
  {/if}

  <span class="content">
    <span class="head">
      <span class="title">{title}</span>
      {#if badge}
        <span
          class="pill insignia"
          class:pill-neutral={badgeTone === 'neutral'}
          class:pill-warn={badgeTone === 'warning'}
          class:pill-good={badgeTone === 'good'}>{badge}</span
        >
      {/if}
    </span>
    {#if description}
      <span class="description">{description}</span>
    {/if}
    {#if disabled && disabledReason}
      <span class="reason">
        <Icono nombre="candado" />
        {disabledReason}
      </span>
    {/if}
  </span>

  <span class="indicator" aria-hidden="true"></span>
</button>

<style>
  /* La tarjeta es el `.panel` común como control (`.panel-interactive`): el
     borde, el fondo, el paso del ratón, la elegida (`.selected`, que cubre
     tanto `aria-checked` como `aria-selected`) y la apagada -- borde punteado
     sobre el plano -- son los de todas las tarjetas. Aquí sólo la maquetación
     y el hueco a la derecha para el círculo del radio. */
  .choice {
    position: relative;
    display: flex;
    min-width: 0;
    align-items: flex-start;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    padding-right: calc(var(--space-4) + 20px);
    color: var(--ink-2);
  }

  .choice.compact {
    padding: var(--space-2) var(--space-3);
    padding-right: calc(var(--space-4) + 20px);
  }

  .choice:disabled .title,
  .choice:disabled .description,
  .choice:disabled .icon {
    opacity: 0.55;
  }

  /* El ícono de la opción, del juego común: el tamaño se lo da `--icono`. */
  .icon {
    --icono: 20px;
    display: grid;
    width: 32px;
    height: 32px;
    flex-shrink: 0;
    place-items: center;
    border-radius: var(--radius);
    background: var(--plane);
    color: var(--ink-2);
  }

  .choice.selected .icon {
    background: var(--surface-2);
    color: var(--accent);
  }

  .content {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: var(--space-1);
  }

  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .title {
    font-size: var(--text-lg);
    font-weight: 600;
    line-height: 1.35;
    color: var(--ink);
  }

  .description {
    display: block;
    font-size: var(--text-sm);
    line-height: 1.5;
    color: var(--ink-2);
  }

  .description::first-letter {
    text-transform: uppercase;
  }

  /* La etiqueta es la `.pill` común; el tono neutro (`.pill-neutral`), que no
     es estado sino dato («Gratis», «Por página»), va en el gris del plano. */
  .insignia {
    line-height: 1.5;
    white-space: nowrap;
  }

  .reason {
    display: flex;
    align-items: flex-start;
    gap: var(--space-1);
    margin-top: var(--space-1);
    font-size: var(--text-xs);
    line-height: 1.45;
    color: var(--ink-2);
  }

  .reason {
    --icono: 14px;
  }

  .reason :global(.icono) {
    margin-top: 1px;
  }

  /* The radio dot: empty ring, filled when chosen. It is what tells a
     selected card from a hovered one at a glance. */
  .indicator {
    position: absolute;
    top: var(--space-3);
    right: var(--space-4);
    width: 16px;
    height: 16px;
    border: 1.5px solid var(--control);
    border-radius: 50%;
    background: var(--surface-2);
    transition:
      border-color var(--duration-fast) var(--ease-out),
      box-shadow var(--duration-fast) var(--ease-out);
  }

  .choice.compact .indicator {
    top: var(--space-2);
  }

  .choice.selected .indicator {
    border-color: var(--accent);
    box-shadow: inset 0 0 0 4px var(--accent);
  }

  .choice:disabled .indicator {
    opacity: 0.4;
  }
</style>
