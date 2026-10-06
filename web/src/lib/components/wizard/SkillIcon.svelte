<script lang="ts">
  /**
   * A line icon per skill, drawn in the current text colour.
   *
   * Replaces the emoji the cards used to carry: an emoji renders differently on
   * every system and sets a tone this console does not have. Unknown ids get
   * the generic document outline rather than nothing, so the grid stays even.
   */
  interface Props {
    id: string;
  }

  let { id }: Props = $props();
</script>

<svg
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="1.6"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
>
  {#if id === 'diplomas'}
    <path d="M2 4.5h6a4 4 0 0 1 4 4V20a3 3 0 0 0-3-3H2z" />
    <path d="M22 4.5h-6a4 4 0 0 0-4 4V20a3 3 0 0 1 3-3h7z" />
  {:else if id === 'correspondencia'}
    <path d="M22 12h-6l-2 3h-4l-2-3H2" />
    <path
      d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"
    />
  {:else if id === 'actas'}
    <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
    <rect x="8" y="2" width="8" height="4" rx="1" />
    <path d="M9 12h6M9 16h4" />
  {:else if id === 'actas-grado'}
    <path d="M22 10 12 5 2 10l10 5z" />
    <path d="M6 12v5c3 2 9 2 12 0v-5" />
  {:else if id === 'archivo'}
    <path
      d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2z"
    />
  {:else if id === 'auto'}
    <circle cx="11" cy="11" r="7" />
    <path d="m21 21-4.3-4.3" />
  {:else}
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" />
  {/if}
</svg>
