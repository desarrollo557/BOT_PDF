<script lang="ts">
  /**
   * El agente revisor en una corrida de carpeta, en vivo (lo pidió el operador
   * el 2026-11-05: «que se muestre el trabajo del agente revisando todo»).
   *
   * La barra reparte los PDF que ya revisó por cómo quedaron; las cifras dicen
   * cuántas costuras validó sin gastar, cuántas decidió la IA y cuántas hojas
   * comprobó en el disco; y el registro cuenta lo último que corrigió, mandó a
   * revisión o no cuadró. Lo cuenta el servicio PDF a PDF (`run.agente`).
   */
  import DatosDelAgente from '$lib/components/DatosDelAgente.svelte';
  import Icono from '$lib/components/Icono.svelte';
  import { ESTADOS, fraseDeFechas, notaDeFechas, porcentaje, repartoDePdf } from '$lib/agente';
  import type { AgenteDeLaCorrida } from '$lib/types';

  interface Props {
    agente: AgenteDeLaCorrida;
    /** Si la corrida sigue: el agente está revisando. */
    activo: boolean;
  }

  let { agente, activo }: Props = $props();

  const tramos = $derived(repartoDePdf(agente));
  /** El revisor de fechas (2026-11-10): «Fechas: N confirmadas · N corregidas · N a revisión». */
  const fechas = $derived(fraseDeFechas(agente.fechas));
  const tonoDeFechas = $derived(
    agente.fechas?.a_revision ? 'warn' : agente.fechas?.corregidas ? 'accent' : 'good'
  );
  /** El registro, sin repetir: el mismo PDF relanzado contaría dos veces lo mismo. */
  const sucesos = $derived.by(() => {
    const vistos = new Set<string>();
    return agente.sucesos.filter((suceso) => {
      const clave = `${suceso.pdf}|${suceso.texto}`;
      if (vistos.has(clave)) return false;
      vistos.add(clave);
      return true;
    });
  });
</script>

<section class="agente-corrida" data-activo={activo ? 'si' : 'no'} aria-label="Agente revisor de la corrida">
  <header class="cabeza">
    <span class="marca" aria-hidden="true"><Icono nombre="escudo" /></span>
    <div class="min-w-0">
      <span class="caps">Agente revisor</span>
      <p class="titulo">
        {activo ? 'Revisando cada PDF que sale' : 'Revisó cada PDF de la corrida'}
        {#if activo}<span class="status-dot live" aria-hidden="true"></span>{/if}
      </p>
    </div>
    <span class="cuenta tabular">
      <strong>{agente.pdf}</strong>
      {agente.pdf === 1 ? 'PDF revisado' : 'PDF revisados'}
    </span>
  </header>

  <div
    class="barra"
    role="img"
    aria-label={tramos.map((tramo) => `${tramo.etiqueta}: ${tramo.valor}`).join(', ')}
  >
    {#each tramos as tramo (tramo.clave)}
      <span class="tramo" data-tono={tramo.tono} style:flex-grow={tramo.valor} title={`${tramo.etiqueta}: ${tramo.valor}`}></span>
    {/each}
  </div>
  <ul class="leyenda">
    {#each tramos as tramo (tramo.clave)}
      <li><span class="muestra" data-tono={tramo.tono}></span>{tramo.etiqueta} <b class="tabular">{tramo.valor}</b></li>
    {/each}
  </ul>

  <dl class="cifras">
    <div class="stat good">
      <dt class="stat-label">Dentro del margen</dt>
      <dd class="stat-value">{porcentaje(agente.dentro_del_margen, agente.costuras) ?? '—'}</dd>
      <dd class="stat-note">{agente.dentro_del_margen} de {agente.costuras} costuras, sin gastar</dd>
    </div>
    <div class="stat" data-tono="ia">
      <dt class="stat-label">Decididas por la IA</dt>
      <dd class="stat-value">{agente.preguntadas_a_la_ia}</dd>
      <dd class="stat-note">
        {agente.preguntadas_a_la_ia ? `${agente.confirmadas_por_la_ia} le dieron la razón al bot` : 'No hizo falta'}
      </dd>
    </div>
    <div class="stat" data-tono={agente.correcciones ? 'accent' : undefined}>
      <dt class="stat-label">Correcciones</dt>
      <dd class="stat-value">{agente.correcciones}</dd>
      <dd class="stat-note">Hojas devueltas a su PDF</dd>
    </div>
    <div class="stat" class:good={!agente.problemas_de_entrega} class:bad={agente.problemas_de_entrega}>
      <dt class="stat-label">En el disco</dt>
      <dd class="stat-value">{agente.hojas_comprobadas.toLocaleString('es-CO')}</dd>
      <dd class="stat-note">
        {agente.problemas_de_entrega
          ? `${agente.problemas_de_entrega} no cuadran`
          : 'Hojas comprobadas, todas en su sitio'}
      </dd>
    </div>
  </dl>

  {#if fechas && agente.fechas}
    <!-- La fecha inicial y la final de cada documento contra su papel
         (2026-11-10): confirmadas, corregidas con prueba o a revisión. -->
    <p class="fechas" data-tono={tonoDeFechas} aria-live="polite">
      <span class="status-dot" aria-hidden="true"></span>
      <strong class="tabular">{fechas}</strong>
      <span class="nota tabular">{notaDeFechas(agente.fechas)}</span>
    </p>
  {/if}

  {#if agente.datos?.documentos}
    <!-- Los datos de cada documento de la corrida -- nombre, identificación,
         código, fechas extremas -- (2026-11-06). -->
    <DatosDelAgente datos={agente.datos} />
  {/if}

  {#if sucesos.length}
    <ol class="registro" aria-live="polite">
      {#each sucesos as suceso (`${suceso.pdf}|${suceso.texto}`)}
        <li class="suceso" data-tono={ESTADOS[suceso.estado].tono}>
          <span class="status-dot" aria-hidden="true"></span>
          <span class="pdf">{suceso.pdf}</span>
          <span class="pill pill-sm etiqueta">{ESTADOS[suceso.estado].etiqueta}</span>
          <span class="texto">{suceso.texto}</span>
        </li>
      {/each}
    </ol>
  {:else}
    <p class="tranquilo">
      <Icono nombre="hecho" />
      Nada que corregir hasta ahora: cada PDF salió con sus hojas en su sitio.
    </p>
  {/if}
</section>

<style>
  [data-tono='good'] {
    --tono: var(--good);
  }
  [data-tono='accent'] {
    --tono: var(--accent);
  }
  [data-tono='warn'] {
    --tono: var(--warning);
  }
  [data-tono='bad'] {
    --tono: var(--critical);
  }
  [data-tono='ia'] {
    --tono: var(--s4);
  }

  .agente-corrida {
    margin: var(--space-4) 0;
    padding: var(--space-4);
    border: 1px solid var(--hairline);
    border-radius: var(--radius-lg);
    background:
      radial-gradient(90% 120% at 0% 0%, color-mix(in srgb, var(--accent) 6%, transparent), transparent 60%),
      var(--surface-1);
  }
  .agente-corrida[data-activo='si'] {
    border-color: color-mix(in srgb, var(--accent) 30%, var(--hairline));
  }

  .cabeza {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }
  .marca {
    --icono: 1.15rem;
    display: grid;
    width: 36px;
    height: 36px;
    flex: none;
    place-items: center;
    border-radius: var(--radius-md);
    background: var(--accent-soft);
    color: var(--accent);
  }
  .titulo {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin: 0;
    font-size: var(--text-md);
    font-weight: 600;
    color: var(--ink);
  }
  .cuenta {
    margin-left: auto;
    flex: none;
    font-size: var(--text-xs);
    color: var(--muted);
    text-align: right;
  }
  .cuenta strong {
    display: block;
    font-size: var(--text-xl);
    line-height: 1.1;
    color: var(--ink);
  }

  /* La barra: un tramo por estado, del ancho de cuántos PDF quedaron así. */
  .barra {
    display: flex;
    gap: 2px;
    height: 10px;
    margin-top: var(--space-4);
    overflow: hidden;
    border-radius: var(--radius-pill);
    background: var(--grid);
  }
  .tramo {
    min-width: 6px;
    flex-basis: 0;
    background: var(--tono);
    transition: flex-grow var(--duration-slow) var(--ease-out);
  }

  .leyenda {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-4);
    margin: var(--space-2) 0 0;
    padding: 0;
    list-style: none;
    font-size: var(--text-xs);
    color: var(--ink-2);
  }
  .leyenda li {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .muestra {
    width: 10px;
    height: 10px;
    border-radius: 3px;
    background: var(--tono);
  }

  .cifras {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3) var(--space-6);
    margin: var(--space-4) 0 0;
  }
  .cifras dd {
    margin: 0;
  }
  .stat[data-tono] {
    border-left-color: color-mix(in srgb, var(--tono) 55%, transparent);
  }
  .stat[data-tono='accent'] .stat-value {
    color: var(--accent);
  }

  /* Las fechas de los documentos: una línea, con el tono de lo peor que haya. */
  .fechas {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-3);
    margin: var(--space-4) 0 0;
    padding: 6px var(--space-3);
    border-left: 2px solid var(--tono);
    border-radius: 0 var(--radius) var(--radius) 0;
    background: color-mix(in srgb, var(--tono) 6%, var(--surface-2));
    font-size: var(--text-sm);
  }
  .fechas .status-dot {
    background: var(--tono);
  }
  .fechas strong {
    font-weight: 600;
    color: var(--ink);
  }
  .fechas .nota {
    font-size: var(--text-xs);
    color: var(--muted);
  }

  /* El registro en vivo: lo último arriba, y cada suceso entra al llegar. */
  .registro {
    display: grid;
    gap: 4px;
    margin: var(--space-4) 0 0;
    padding: 0;
    list-style: none;
  }
  .suceso {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    padding: 6px var(--space-3);
    border-left: 2px solid var(--tono);
    border-radius: 0 var(--radius) var(--radius) 0;
    background: color-mix(in srgb, var(--tono) 6%, var(--surface-2));
    font-size: var(--text-sm);
    animation: entrada var(--duration-slow) var(--ease-out) both;
  }
  .suceso .status-dot {
    background: var(--tono);
  }
  .pdf {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--ink);
  }
  .etiqueta {
    background: color-mix(in srgb, var(--tono) 14%, transparent);
    color: color-mix(in srgb, var(--tono) 75%, var(--ink));
  }
  .texto {
    min-width: 0;
    flex: 1 1 14rem;
    color: var(--ink-2);
    overflow-wrap: anywhere;
  }

  .tranquilo {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin: var(--space-4) 0 0;
    font-size: var(--text-sm);
    color: color-mix(in srgb, var(--good) 70%, var(--ink));
  }
</style>
