<script lang="ts">
  import {
    fechasDelDocumento,
    fraseDeFechas,
    fraseDeNombres,
    lineaDeUnNombre,
    nombresDelDocumento,
    notaDeFechas,
    notaDeNombres
  } from '$lib/agente';
  import type { RevisionDeFechas, RevisionDeNombres } from '$lib/types';

  /**
   * Lo que dijeron de este documento los dos revisores comunes a todas las
   * habilidades: el de fechas (2026-11-10) y el de nombres (2026-11-17). Las
   * mismas frases que el agente de la corrida, y debajo cada fecha o nombre
   * corregido y cada uno que va a Revisión, con su página.
   */
  interface Props {
    fechas?: RevisionDeFechas | null;
    nombres?: RevisionDeNombres | null;
  }

  let { fechas = null, nombres = null }: Props = $props();

  /** Lo que se enseña de cada lista: el resto se cuenta, no se esconde. */
  const VISIBLES = 8;

  const deFechas = $derived(fechasDelDocumento(fechas));
  const deNombres = $derived(nombresDelDocumento(nombres));
  const bloques = $derived(
    [
      deFechas && fechas
        ? {
            clave: 'fechas',
            frase: fraseDeFechas(deFechas),
            nota: notaDeFechas(deFechas),
            tono: deFechas.a_revision ? 'warn' : deFechas.corregidas ? 'accent' : 'good',
            lineas: fechas.detalle.map((d) => ({
              corregido: d.estado === 'corregida',
              texto: `${d.documento}: ${d.nota}`,
              pagina: d.pagina
            }))
          }
        : null,
      deNombres && nombres
        ? {
            clave: 'nombres',
            frase: fraseDeNombres(deNombres),
            nota: notaDeNombres(deNombres),
            tono: deNombres.a_revision ? 'warn' : deNombres.corregidos ? 'accent' : 'good',
            lineas: nombres.detalle.map((d) => ({
              corregido: d.estado === 'corregido',
              texto: lineaDeUnNombre(d),
              pagina: d.pagina
            }))
          }
        : null
    ].filter((bloque) => bloque !== null)
  );
</script>

{#if bloques.length}
  <section class="panel revisores" aria-label="Fechas y nombres revisados">
    <span class="caps">Fechas y nombres</span>
    {#each bloques as bloque (bloque.clave)}
      <div class="bloque">
        <p class="linea" data-tono={bloque.tono}>
          <span class="status-dot" aria-hidden="true"></span>
          <strong class="tabular">{bloque.frase}</strong>
          <span class="nota tabular">{bloque.nota}</span>
        </p>
        {#if bloque.lineas.length}
          <ul class="detalle">
            {#each bloque.lineas.slice(0, VISIBLES) as linea, indice (indice)}
              <li>
                <span class="pill {linea.corregido ? 'pill-neutral' : 'pill-warn'}">
                  {linea.corregido ? 'Corregido' : 'A revisión'}
                </span>
                <span class="texto">{linea.texto}</span>
                {#if linea.pagina}<span class="pagina tabular">pág. {linea.pagina}</span>{/if}
              </li>
            {/each}
          </ul>
          {#if bloque.lineas.length > VISIBLES}
            <p class="mas">y {bloque.lineas.length - VISIBLES} más en la pantalla de Revisión.</p>
          {/if}
        {/if}
      </div>
    {/each}
  </section>
{/if}

<style>
  .revisores {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .bloque {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  /* La misma línea que el agente de la corrida, con el tono de lo peor que haya. */
  .linea {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-3);
    margin: 0;
    padding: 6px var(--space-3);
    border-left: 2px solid var(--tono);
    border-radius: 0 var(--radius) var(--radius) 0;
    background: color-mix(in srgb, var(--tono) 6%, var(--surface-2));
    font-size: var(--text-sm);
  }
  .linea[data-tono='good'] {
    --tono: var(--good);
  }
  .linea[data-tono='accent'] {
    --tono: var(--accent);
  }
  .linea[data-tono='warn'] {
    --tono: var(--warning);
  }
  .linea .status-dot {
    background: var(--tono);
  }
  .linea strong {
    font-weight: 600;
    color: var(--ink);
  }
  .nota,
  .pagina,
  .mas {
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .detalle {
    display: grid;
    gap: 4px;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .detalle li {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-1) var(--space-2);
    font-size: var(--text-sm);
  }
  .texto {
    min-width: 0;
    flex: 1;
    overflow-wrap: anywhere;
  }
  .mas {
    margin: 0;
  }
</style>
