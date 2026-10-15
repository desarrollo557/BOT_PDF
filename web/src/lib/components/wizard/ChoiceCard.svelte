<script lang="ts">
  import type { Snippet } from 'svelte';

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
  class="card"
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
          class="pill badge"
          class:pill-warn={badgeTone === 'warning'}
          class:pill-good={badgeTone === 'good'}
          data-tone={badgeTone}>{badge}</span
        >
      {/if}
    </span>
    {#if description}
      <span class="description">{description}</span>
    {/if}
    {#if disabled && disabledReason}
      <span class="reason">
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
          <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" />
        </svg>
        {disabledReason}
      </span>
    {/if}
  </span>

  <span class="indicator" aria-hidden="true"></span>
</button>

<style>
  .card {
    position: relative;
    display: flex;
    min-width: 0;
    align-items: flex-start;
    gap: var(--space-3);
    border: 1px solid var(--hairline);
    border-radius: var(--radius-lg);
    background: var(--surface-2);
    padding: var(--space-3) var(--space-4);
    padding-right: calc(var(--space-4) + 20px);
    font: inherit;
    text-align: left;
    color: var(--ink-2);
    cursor: pointer;
    transition:
      border-color 0.15s ease,
      background-color 0.15s ease,
      box-shadow 0.15s ease;
  }

  .card.compact {
    padding: var(--space-2) var(--space-3);
    padding-right: calc(var(--space-4) + 20px);
  }

  .card:hover:not(:disabled) {
    border-color: var(--axis);
    background: var(--surface-1);
  }

  .card:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 2px;
  }

  .card.selected {
    border-color: var(--accent);
    background: var(--accent-soft);
    box-shadow: inset 0 0 0 1px var(--accent);
    color: var(--ink);
  }

  .card:disabled {
    border-style: dashed;
    background: var(--plane);
    cursor: not-allowed;
  }

  .card:disabled .title,
  .card:disabled .description,
  .card:disabled .icon {
    opacity: 0.55;
  }

  .icon {
    display: grid;
    width: 32px;
    height: 32px;
    flex-shrink: 0;
    place-items: center;
    border-radius: var(--radius);
    background: var(--plane);
    color: var(--ink-2);
  }

  .card.selected .icon {
    background: var(--surface-2);
    color: var(--accent);
  }

  .icon :global(svg) {
    width: 20px;
    height: 20px;
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

  /* La etiqueta es la `.pill` común; el tono neutro, que no es estado sino
     dato («Gratis», «Por página»), va en el gris del plano. */
  .badge {
    line-height: 1.5;
    white-space: nowrap;
  }

  .badge[data-tone='neutral'] {
    background: var(--plane);
    color: var(--ink-2);
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

  .reason svg {
    width: 14px;
    height: 14px;
    flex-shrink: 0;
    margin-top: 1px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.4;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  /* The radio dot: empty ring, filled when chosen. It is what tells a
     selected card from a hovered one at a glance. */
  .indicator {
    position: absolute;
    top: var(--space-3);
    right: var(--space-4);
    width: 16px;
    height: 16px;
    border: 1.5px solid var(--axis);
    border-radius: 50%;
    background: var(--surface-2);
    transition:
      border-color 0.15s ease,
      box-shadow 0.15s ease;
  }

  .card.compact .indicator {
    top: var(--space-2);
  }

  .card.selected .indicator {
    border-color: var(--accent);
    box-shadow: inset 0 0 0 4px var(--accent);
  }

  .card:disabled .indicator {
    opacity: 0.4;
  }
</style>
