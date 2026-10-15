<script lang="ts">
  /**
   * El encabezado de cada pantalla: título, una explicación corta y, a la
   * derecha, lo que se puede hacer con la pantalla entera.
   *
   * Cada página traía el suyo, con tamaños y anchos distintos -- y la ficha de
   * un documento no tenía ninguno --. Uno solo hace que pasar de Procesar a
   * Archivo o a Revisión se sienta como pasar de una sección a otra de la misma
   * aplicación.
   */
  import type { Snippet } from 'svelte';

  let {
    titulo,
    descripcion,
    acciones,
    children
  }: {
    titulo: string;
    descripcion?: string;
    /** Lo que va a la derecha: pestañas, botones. */
    acciones?: Snippet;
    /** Una descripción con marcado, en lugar de `descripcion`. */
    children?: Snippet;
  } = $props();
</script>

<header class="encabezado">
  <div class="texto">
    <h1>{titulo}</h1>
    {#if children}
      <div class="descripcion">{@render children()}</div>
    {:else if descripcion}
      <p class="descripcion">{descripcion}</p>
    {/if}
  </div>
  {#if acciones}
    <div class="acciones">{@render acciones()}</div>
  {/if}
</header>

<style>
  .encabezado {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1.25rem;
  }
  .texto {
    min-width: 0;
  }
  h1 {
    margin: 0;
    font-size: var(--text-xl);
    font-weight: 650;
    letter-spacing: -0.015em;
    color: var(--ink);
    overflow-wrap: anywhere;
  }
  .descripcion {
    margin: 0.3rem 0 0;
    max-width: 68ch;
    font-size: var(--text-md);
    line-height: 1.5;
    color: var(--ink-2);
  }
  .descripcion :global(p) {
    margin: 0;
  }
  .acciones {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
  }
</style>
