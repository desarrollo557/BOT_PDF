<script lang="ts">
  import { corregirNombre, renglonDelNombreUrl } from '$lib/api';
  import { enlaceAlDocumento } from '$lib/navegacion.svelte';
  import type { FilaConPersona, Job } from '$lib/types';

  /**
   * Una persona -- de cualquier habilidad -- cuyo nombre la máquina no aseguró:
   * donde está escrito en su papel, lo que leyó cada lectura y el nombre que quedó.
   *
   * El operador (2026-11-17): «la idea es tener los nombres de manera correcta».
   * Lo confirma con «Está bien» o lo corrige escribiéndolo, o pulsando una de
   * las lecturas; el PDF, el FUID, la entrega y el padrón se mueven juntos. Al
   * guardarse, el trabajo vuelve por el canal en vivo con el estado nuevo y el
   * estudiante sale de la lista.
   */
  interface Props {
    job: Job;
    fila: FilaConPersona;
    /** Su número en las filas del informe: con él se pide su renglón y se corrige. */
    numero: number;
  }

  let { job, fila, numero }: Props = $props();

  const revision = $derived(fila.revision_del_nombre);
  const pagina = $derived(revision?.pagina_de_la_ficha ?? fila.pagina_inicial ?? 0);
  const dudoso = $derived(revision?.estado === 'duda');

  // Se siembra con el nombre que quedó, y se vuelve a sembrar si el servidor lo cambia.
  let valor = $state('');
  let sembrado = $state('');
  $effect(() => {
    const actual = fila.nombre ?? '';
    if (actual !== sembrado) {
      sembrado = actual;
      valor = actual;
    }
  });

  let ocupado = $state(false);
  let error = $state<string | null>(null);
  let avisos = $state<string[]>([]);
  let sinImagen = $state(false);

  /** Mayúsculas y sin tildes, como lo escribe el FUID: así se compara con el que había. */
  function plano(texto: string): string {
    return texto
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .toUpperCase()
      .replace(/[^A-Z\s]/g, ' ')
      .split(/\s+/)
      .filter(Boolean)
      .join(' ');
  }

  const cambia = $derived(plano(valor) !== plano(fila.nombre ?? ''));
  const valido = $derived(plano(valor).split(' ').filter((palabra) => palabra.length >= 3).length >= 2);

  /** Las otras formas que se leyeron, sin repetir la que quedó. */
  const opciones = $derived(
    [...new Set([...(revision?.lecturas ?? []), ...(revision?.de_la_ia ? [plano(revision.de_la_ia)] : [])])].filter(
      (lectura) => lectura && lectura !== fila.nombre
    )
  );

  async function guardar() {
    if (ocupado || !valido) return;
    ocupado = true;
    error = null;
    try {
      const hecho = await corregirNombre(job.id, numero, plano(valor));
      avisos = hecho.avisos;
    } catch (problema) {
      error = (problema as Error).message;
    } finally {
      ocupado = false;
    }
  }
</script>

<article class="panel nombre" aria-label={`Nombre de ${fila.nombre ?? 'una persona'}`}>
  {#if !sinImagen}
    <img
      class="renglon"
      src={renglonDelNombreUrl(job.id, numero)}
      alt={`Donde está escrito el nombre, página ${pagina}`}
      loading="lazy"
      onerror={() => (sinImagen = true)}
    />
  {:else}
    <p class="sin-imagen">El PDF de esta persona ya no está en el servicio: mírelo en el destino.</p>
  {/if}

  <div class="cabeza">
    <span class="pill {dudoso ? 'pill-warn' : 'pill-neutral'}">
      {dudoso ? 'Sin confirmar' : 'Corregido por la IA'}
    </span>
    <a class="documento" href={enlaceAlDocumento(job.id, 'revision')} title={job.filename}>{job.filename}</a>
    <span class="paginas tabular">
      pág. {pagina}{fila.pagina_final && fila.pagina_final !== pagina ? `–${fila.pagina_final}` : ''}
    </span>
  </div>

  <label class="campo">
    <span class="caps">Nombre, con los apellidos primero</span>
    <input
      class="input input-sm"
      bind:value={valor}
      spellcheck="false"
      aria-invalid={!valido}
      onkeydown={(evento) => evento.key === 'Enter' && guardar()}
    />
  </label>

  {#if revision?.leido && revision.leido !== fila.nombre}
    <p class="leido">Se leyó «{revision.leido}».</p>
  {/if}

  {#if opciones.length}
    <div class="opciones" aria-label="Lo que leyó cada lectura">
      <span class="caps">Lecturas</span>
      {#each opciones as opcion (opcion)}
        <button class="btn btn-ghost btn-sm" onclick={() => (valor = opcion)} disabled={ocupado}>{opcion}</button>
      {/each}
    </div>
  {/if}

  {#if revision?.padron?.length}
    <div class="opciones" aria-label="Personas parecidas del padrón de la Universidad">
      <span class="caps">Padrón</span>
      {#each revision.padron as persona (persona)}
        <button class="btn btn-ghost btn-sm" onclick={() => (valor = persona)} disabled={ocupado}>{persona}</button>
      {/each}
    </div>
  {/if}

  <div class="acciones">
    <button class="btn btn-primary btn-sm" onclick={guardar} disabled={ocupado || !valido}>
      {ocupado ? 'Guardando…' : cambia ? 'Corregir' : 'Está bien'}
    </button>
    {#if !valido}
      <span class="falta">Escriba el nombre completo: al menos dos palabras.</span>
    {/if}
  </div>

  {#if error}
    <p class="error" role="alert">{error}</p>
  {/if}
  {#each avisos as aviso (aviso)}
    <p class="aviso">{aviso}</p>
  {/each}
</article>

<style>
  .nombre {
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
  }
  .renglon {
    display: block;
    width: 100%;
    max-height: 22rem;
    object-fit: contain;
    object-position: top left;
    border: 1px solid var(--rule);
    border-radius: var(--radius-sm);
    background: #fff;
  }
  .sin-imagen {
    margin: 0;
    font-size: var(--text-sm);
    color: var(--muted);
  }
  .cabeza {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem 0.6rem;
  }
  .documento {
    overflow: hidden;
    flex: 1;
    min-width: 8rem;
    font-size: var(--text-sm);
    font-weight: 600;
    color: inherit;
    text-decoration: none;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .documento:hover {
    color: var(--accent);
  }
  .paginas {
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .campo {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  .leido {
    margin: 0;
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .opciones {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.3rem;
  }
  .opciones .btn {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .acciones {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.6rem;
  }
  .falta,
  .aviso {
    font-size: var(--text-xs);
    color: var(--warning-ink);
  }
  .aviso {
    margin: 0;
  }
  .error {
    margin: 0;
    font-size: var(--text-sm);
    color: var(--critical);
  }
</style>
