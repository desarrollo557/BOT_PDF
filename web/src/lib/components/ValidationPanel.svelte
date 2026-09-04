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
  <section class="rounded-xl border border-hairline bg-raised p-4 shadow-[var(--shadow)]">
    <header class="flex flex-wrap items-baseline justify-between gap-2">
      <h3 class="text-sm font-semibold">Comprobación de la lectura</h3>
      {#if validation.total === 0}
        <span class="font-mono text-xs text-good">nada que revisar</span>
      {:else}
        <span class="font-mono text-xs text-muted">
          {validation.errores}
          {validation.errores === 1 ? 'error' : 'errores'} · {validation.avisos}
          {validation.avisos === 1 ? 'aviso' : 'avisos'}
        </span>
      {/if}
    </header>

    {#if validation.total === 0}
      <p class="mt-1.5 text-sm text-ink-2">
        Ninguna página se contradice a sí misma: los folios avanzan, los campos están completos y
        cada dato que el documento imprime dos veces coincide consigo mismo.
      </p>
    {:else}
      <ul class="mt-2.5 space-y-1">
        {#each shown as issue (issue.field + issue.page + issue.reason)}
          <li class="flex gap-2 text-sm">
            <span
              class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
              class:bg-critical={issue.severity === 'error'}
              class:bg-warning={issue.severity !== 'error'}
            ></span>
            <span class="text-ink-2">
              {#if issue.page}<b class="font-mono text-xs">pág. {issue.page}</b> · {/if}{issue.reason}
            </span>
          </li>
        {/each}
      </ul>

      {#if hidden > 0}
        <button
          class="mt-2 font-mono text-xs text-accent hover:underline"
          onclick={() => (expanded = true)}
        >
          ver los {hidden} restantes
        </button>
      {:else if expanded && sorted.length > VISIBLE}
        <button
          class="mt-2 font-mono text-xs text-muted hover:underline"
          onclick={() => (expanded = false)}
        >
          plegar
        </button>
      {/if}

      <p class="mt-2.5 text-xs text-muted">
        Nada de esto se corrige solo. El sistema señala dónde la lectura no se sostiene; la
        decisión es de quien firma.
      </p>
    {/if}
  </section>
{/if}
