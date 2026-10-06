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
        <span class="badge" data-tone={badgeTone}>{badge}</span>
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
    gap: var(--wz-space-3, 12px);
    border: 1px solid var(--hairline);
    border-radius: var(--wz-radius-lg, 12px);
    background: var(--surface-2);
    padding: var(--wz-space-3, 12px) var(--wz-space-4, 16px);
    padding-right: calc(var(--wz-space-4, 16px) + 20px);
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
    padding: var(--wz-space-2, 8px) var(--wz-space-3, 12px);
    padding-right: calc(var(--wz-space-4, 16px) + 20px);
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
    border-radius: var(--wz-radius, 8px);
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
    gap: var(--wz-space-1, 4px);
  }

  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--wz-space-2, 8px);
  }

  .title {
    font-size: var(--wz-text-base, 0.9375rem);
    font-weight: 600;
    line-height: 1.35;
    color: var(--ink);
  }

  .description {
    display: block;
    font-size: var(--wz-text-sm, 0.8125rem);
    line-height: 1.5;
    color: var(--ink-2);
  }

  .description::first-letter {
    text-transform: uppercase;
  }

  .badge {
    border-radius: 999px;
    padding: 2px var(--wz-space-2, 8px);
    font-size: 0.6875rem;
    font-weight: 600;
    line-height: 1.5;
    white-space: nowrap;
    background: var(--plane);
    color: var(--ink-2);
  }

  .badge[data-tone='accent'] {
    background: var(--accent-soft);
    color: var(--accent);
  }

  .badge[data-tone='warning'] {
    background: color-mix(in oklab, var(--warning) 16%, transparent);
    color: color-mix(in oklab, var(--warning) 55%, var(--ink));
  }

  .badge[data-tone='good'] {
    background: color-mix(in oklab, var(--good) 13%, transparent);
    color: color-mix(in oklab, var(--good) 70%, var(--ink));
  }

  .reason {
    display: flex;
    align-items: flex-start;
    gap: var(--wz-space-1, 4px);
    margin-top: var(--wz-space-1, 4px);
    font-size: var(--wz-text-xs, 0.75rem);
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
    top: var(--wz-space-3, 12px);
    right: var(--wz-space-4, 16px);
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
    top: var(--wz-space-2, 8px);
  }

  .card.selected .indicator {
    border-color: var(--accent);
    box-shadow: inset 0 0 0 4px var(--accent);
  }

  .card:disabled .indicator {
    opacity: 0.4;
  }
</style>
