<script lang="ts">
  import type { Issue, Validation } from '$lib/types';

  interface Props {
    validation: Validation | undefined;
    issues: Issue[] | undefined;
  }

  let { validation, issues = [] }: Props = $props();

  /**
   * Cuántos hallazgos se muestran antes de plegar el resto.
   *
   * Un libro con cuatrocientas páginas puede dejar decenas, y una lista de
   * cincuenta líneas no se lee: se cierra. Los errores van primero porque son
   * los que impiden firmar.
   */
  const VISIBLE = 12;

  let expanded = $state(false);

  const sorted = $derived(
    [...(issues ?? [])].sort((a, b) => {
      if (a.severity !== b.severity) return a.severity === 'error' ? -1 : 1;
      return (a.page ?? 0) - (b.page ?? 0);
    })
  );

  const shown = $derived(expanded ? sorted : sorted.slice(0, VISIBLE));
  const hidden = $derived(sorted.length - shown.length);
</script>

{#if validation}
  <section class="panel">
    <header class="flex flex-wrap items-center justify-between gap-2">
      <h2 class="titulo">Comprobación de la lectura</h2>
      {#if validation.total === 0}
        <span class="pill pill-good">Nada que revisar</span>
      {:else}
        <!-- Los errores y los avisos como píldoras: son banderas, y se leen
             igual que las de estado del resto de la aplicación. -->
        <span class="flex flex-wrap gap-1.5">
          <span class="pill pill-bad tabular">
            {validation.errores}
            {validation.errores === 1 ? 'error' : 'errores'}
          </span>
          <span class="pill pill-warn tabular">
            {validation.avisos}
            {validation.avisos === 1 ? 'aviso' : 'avisos'}
          </span>
        </span>
      {/if}
    </header>

    {#if validation.total === 0}
      <p class="texto">
        Ninguna página se contradice a sí misma: los folios avanzan, los campos están completos y
        cada dato que el documento imprime dos veces coincide consigo mismo.
      </p>
    {:else}
      <ul class="hallazgos">
        {#each shown as issue (issue.field + issue.page + issue.reason)}
          <li>
            <span
              class="status-dot status-dot-sm punto {issue.severity === 'error' ? 'bad' : 'warn'}"
            ></span>
            <span>
              {#if issue.page}<b class="tabular">Pág. {issue.page}</b> · {/if}{issue.reason}
            </span>
          </li>
        {/each}
      </ul>

      {#if hidden > 0}
        <button class="btn btn-ghost btn-sm mt-2" onclick={() => (expanded = true)}>
          Ver los {hidden} restantes
        </button>
      {:else if expanded && sorted.length > VISIBLE}
        <button class="btn btn-ghost btn-sm mt-2" onclick={() => (expanded = false)}>
          Plegar
        </button>
      {/if}

      <p class="pie">
        Nada de esto se corrige solo. El sistema señala dónde la lectura no se sostiene; la
        decisión es de quien firma.
      </p>
    {/if}
  </section>
{/if}

<style>
  .titulo {
    margin: 0;
    font-size: var(--text-md);
    font-weight: 600;
  }
  .texto {
    margin: 0.4rem 0 0;
    font-size: var(--text-md);
    line-height: 1.5;
    color: var(--ink-2);
  }

  .hallazgos {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    margin: 0.6rem 0 0;
    padding: 0;
    list-style: none;
  }
  .hallazgos li {
    display: flex;
    gap: var(--space-2);
    font-size: var(--text-sm);
    color: var(--ink-2);
  }
  .hallazgos b {
    font-weight: 600;
    color: var(--ink);
  }
  /* El punto de estado común: el color dice la gravedad, y la píldora de
     arriba lo dice en palabras. Aquí sólo se alinea con la primera línea. */
  .punto {
    margin-top: 0.4rem;
  }

  .pie {
    margin: 0.6rem 0 0;
    font-size: var(--text-xs);
    color: var(--muted);
  }
</style>
