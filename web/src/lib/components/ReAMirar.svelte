<script lang="ts">
  import { corregirRe, hojaDelReUrl } from '$lib/api';
  import { enlaceAlDocumento } from '$lib/navegacion.svelte';
  import type { CandidatoDelRe } from '$lib/types';

  /**
   * Un documento cuyo RE la máquina no aseguró (2026-11-18): la hoja donde está
   * su sello, el motivo y los candidatos con su porqué. El operador confirma un
   * candidato o escribe el RE que ve en el papel; el PDF, el índice y la
   * entrega se mueven juntos, y el documento sale de la lista.
   *
   * «NUNCA INVENTAR INFORMACIÓN»: la máquina sólo propone; el RE que entra al
   * nombre lo pone quien tiene el papel delante.
   */
  interface Props {
    jobId: string;
    documento: string;
    pagina: number;
    motivo: string;
    candidatos: CandidatoDelRe[];
    /** El PDF donde quedó el documento, si se escribió. */
    archivo: string | null;
  }

  let { jobId, documento, pagina, motivo, candidatos, archivo }: Props = $props();

  let valor = $state('');
  $effect(() => {
    if (!valor && candidatos.length === 1) valor = candidatos[0].valor;
  });

  let ocupado = $state(false);
  let hecho = $state<string | null>(null);
  let error = $state<string | null>(null);
  let avisos = $state<string[]>([]);
  let sinImagen = $state(false);

  /** Como lo guarda el servidor: «RE» y trece cifras, sin blancos. */
  const limpio = $derived(valor.replace(/[\s.-]/g, '').toUpperCase());
  const valido = $derived(/^RE\d{13}$/.test(limpio));

  async function guardar() {
    if (ocupado || !valido) return;
    ocupado = true;
    error = null;
    try {
      const respuesta = await corregirRe(jobId, pagina, limpio);
      avisos = respuesta.avisos;
      hecho = respuesta.archivo;
    } catch (problema) {
      error = (problema as Error).message;
    } finally {
      ocupado = false;
    }
  }
</script>

<article class="panel re" aria-label={`RE por confirmar de ${documento}, página ${pagina}`}>
  {#if !sinImagen}
    <img
      class="hoja"
      src={hojaDelReUrl(jobId, pagina)}
      alt={`La hoja ${pagina}, donde está el sello`}
      loading="lazy"
      onerror={() => (sinImagen = true)}
    />
  {:else}
    <p class="sin-imagen">El PDF de esta hoja ya no está en el servicio: mírelo en el destino.</p>
  {/if}

  <div class="cabeza">
    <span class="pill pill-warn">RE por confirmar</span>
    <a class="documento" href={enlaceAlDocumento(jobId, 'revision')} title={documento}>{documento}</a>
    <span class="paginas tabular">pág. {pagina}</span>
  </div>
  {#if archivo}
    <p class="leido">Quedó en {archivo}.</p>
  {/if}
  <p class="leido">{motivo}</p>

  {#if candidatos.length}
    <div class="opciones" aria-label="Candidatos con su porqué">
      <span class="caps">Candidatos</span>
      {#each candidatos as candidato (candidato.valor)}
        <button
          class="btn btn-ghost btn-sm"
          title={candidato.motivo}
          onclick={() => (valor = candidato.valor)}
          disabled={ocupado}>{candidato.valor}</button
        >
      {/each}
    </div>
  {/if}

  <label class="campo">
    <span class="caps">El RE que dice el sello</span>
    <input
      class="input input-sm tabular"
      bind:value={valor}
      spellcheck="false"
      placeholder="RE2310202402908"
      aria-invalid={!!valor && !valido}
      onkeydown={(evento) => evento.key === 'Enter' && guardar()}
    />
  </label>

  <div class="acciones">
    <button class="btn btn-primary btn-sm" onclick={guardar} disabled={ocupado || !valido || !!hecho}>
      {ocupado ? 'Guardando…' : hecho ? 'Guardado' : 'Confirmar'}
    </button>
    {#if valor && !valido}
      <span class="falta">Un RE es «RE» y trece cifras.</span>
    {/if}
  </div>

  {#if hecho}
    <p class="leido">Ahora se llama {hecho}.</p>
  {/if}
  {#if error}
    <p class="error" role="alert">{error}</p>
  {/if}
  {#each avisos as aviso (aviso)}
    <p class="aviso">{aviso}</p>
  {/each}
</article>

<style>
  .re {
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
  }
  .hoja {
    display: block;
    width: 100%;
    max-height: 26rem;
    object-fit: contain;
    object-position: top;
    border: 1px solid var(--rule);
    border-radius: var(--radius-sm);
    background: #fff;
  }
  .sin-imagen,
  .leido {
    margin: 0;
    font-size: var(--text-xs);
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
  .opciones {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.3rem;
  }
  .acciones {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.6rem;
  }
  .falta,
  .aviso {
    margin: 0;
    font-size: var(--text-xs);
    color: var(--warning-ink);
  }
  .error {
    margin: 0;
    font-size: var(--text-sm);
    color: var(--critical);
  }
</style>
