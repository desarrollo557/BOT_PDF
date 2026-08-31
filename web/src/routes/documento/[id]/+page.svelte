<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { renameJob } from '$lib/api';
  import JobCard from '$lib/components/JobCard.svelte';
  import { jobStore } from '$lib/jobs.svelte';

  const job = $derived(jobStore.get(page.params.id ?? ''));
  let confirmingDelete = $state(false);
  let renaming = $state(false);
  let draft = $state('');
  let error = $state<string | null>(null);

  async function rename() {
    const name = draft.trim();
    if (!name) return;
    try {
      await renameJob(page.params.id ?? '', name);
      renaming = false;
    } catch (problem) {
      error = (problem as Error).message;
    }
  }

  async function remove(purge: boolean) {
    confirmingDelete = false;
    try {
      await jobStore.remove(page.params.id ?? '', purge);
      await goto('/');
    } catch (problem) {
      error = (problem as Error).message;
    }
  }
</script>

<nav class="mb-5 flex flex-wrap items-center justify-between gap-3">
  <a class="font-mono text-sm text-accent hover:underline" href="/">← todos los documentos</a>

  {#if job}
    {#if renaming}
      <span class="flex flex-wrap items-center gap-2">
        <input
          class="min-w-64 rounded border border-hairline bg-raised px-2 py-1 text-sm outline-none focus:border-accent"
          bind:value={draft}
        />
        <button class="rounded border border-accent px-2.5 py-1 text-xs text-accent" onclick={rename}>
          Guardar
        </button>
        <button
          class="rounded border border-hairline px-2.5 py-1 text-xs text-muted"
          onclick={() => (renaming = false)}
        >
          Cancelar
        </button>
      </span>
    {:else if confirmingDelete}
      <span class="flex flex-wrap items-center gap-2 text-sm">
        <button
          class="rounded border border-hairline px-2.5 py-1 text-xs"
          onclick={() => remove(false)}
        >
          Quitar de la pantalla
        </button>
        <button
          class="rounded border border-critical px-2.5 py-1 text-xs text-critical hover:bg-critical hover:text-white"
          onclick={() => remove(true)}
        >
          Eliminar también los PDF
        </button>
        <button
          class="rounded border border-hairline px-2.5 py-1 text-xs text-muted"
          onclick={() => (confirmingDelete = false)}
        >
          Cancelar
        </button>
      </span>
    {:else}
      <span class="flex gap-2">
        <button
          class="rounded border border-hairline px-2.5 py-1 font-mono text-xs text-muted transition-colors hover:border-accent hover:text-accent"
          onclick={() => {
            draft = job?.filename ?? '';
            renaming = true;
          }}
        >
          renombrar
        </button>
        <button
          class="rounded border border-hairline px-2.5 py-1 font-mono text-xs text-muted transition-colors hover:border-critical hover:text-critical"
          onclick={() => (confirmingDelete = true)}
        >
          eliminar
        </button>
      </span>
    {/if}
  {/if}
</nav>

{#if error}
  <p class="mb-4 text-sm text-critical">{error}</p>
{/if}

{#if job}
  <JobCard {job} />
{:else}
  <div class="rounded-xl border border-hairline bg-raised shadow-[var(--shadow)] p-6">
    <h2 class="text-base font-semibold">Este documento ya no está en la pantalla</h2>
    <p class="mt-1.5 text-sm text-ink-2">
      Puede haber sido limpiado del área de trabajo. Sus resoluciones siguen registradas en el
      <a class="text-accent hover:underline" href="/archivo">inventario</a>.
    </p>
  </div>
{/if}
