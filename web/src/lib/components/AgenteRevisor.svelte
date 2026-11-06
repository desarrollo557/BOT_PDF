<script lang="ts">
  /**
   * El trabajo del agente revisor sobre un PDF (lo pidió el operador el
   * 2026-11-05: «que se muestre el trabajo del agente revisando todo en el
   * front, de una manera gráfica muy llamativa pero profesional»).
   *
   * Arriba, qué hizo y en qué quedó; el anillo reparte las costuras -- dentro
   * del margen, confirmadas por la IA, corregidas, a revisión --; la cinta
   * pinta cada hoja del original en el PDF en que salió y cada costura con lo
   * que el agente hizo de ella; debajo, cada corrección con el papel que la
   * prueba, y la comprobación del disco. Todo sale del informe: nada se estima.
   */
  import { onMount } from 'svelte';
  import DatosDelAgente from '$lib/components/DatosDelAgente.svelte';
  import Icono from '$lib/components/Icono.svelte';
  import {
    ESTADOS,
    RESULTADOS,
    cinta,
    frase,
    porQuien,
    porcentaje,
    queMovio,
    repartoDeCosturas,
    type CosturaDeLaCinta,
    type HojaDeLaCinta
  } from '$lib/agente';
  import type { ComprobacionDeLaEntrega, IntegridadDeLosDatos, RevisionDeCortes } from '$lib/types';

  interface Props {
    revision: RevisionDeCortes | null | undefined;
    comprobacion?: ComprobacionDeLaEntrega | null;
    /** Lo que revisó de los datos de cada documento, si su habilidad los espera. */
    integridad?: IntegridadDeLosDatos | null;
    paginas: number;
  }

  let { revision, comprobacion = null, integridad = null, paginas }: Props = $props();

  const estado = $derived(ESTADOS[revision?.estado ?? 'no corrió']);
  const datos = $derived(revision ? cinta(revision, paginas) : null);
  const tramos = $derived(revision ? repartoDeCosturas(revision) : []);
  const total = $derived(revision?.costuras ?? 0);
  const dentro = $derived(revision?.dentro_del_margen ?? 0);
  const movimientos = $derived(revision?.movimientos ?? []);
  const aRevision = $derived(revision?.en_revision ?? []);
  const problemas = $derived(comprobacion?.problemas ?? []);

  /** Los resultados que se marcan en la cinta, en el orden de la leyenda. */
  const MARCADOS = ['confirmada', 'corregida', 'revision'] as const;
  /** Lo que pasó en las costuras, para la leyenda: sólo lo que hay. */
  const resultados = $derived(new Set(datos?.costuras.map((costura) => costura.resultado) ?? []));

  // El anillo: un círculo de radio 42 en una caja de 100, con un arco por tramo.
  const RADIO = 42;
  const VUELTA = 2 * Math.PI * RADIO;
  /** Un respiro entre dos tramos, para que se lean como dos y no como uno. */
  const RESPIRO = 1.6;
  const arcos = $derived.by(() => {
    let recorrido = 0;
    return tramos.map((tramo) => {
      const largo = total ? (tramo.valor / total) * VUELTA : 0;
      const arco = { ...tramo, largo: Math.max(largo - (tramos.length > 1 ? RESPIRO : 0), 0.5), desde: recorrido };
      recorrido += largo;
      return arco;
    });
  });

  // El anillo y la cinta se dibujan al aparecer: primero vacíos, luego llenos.
  // Con «reducir movimiento» la transición dura nada y se ven llenos de una vez.
  let dibujado = $state(false);
  onMount(() => {
    const cuadro = requestAnimationFrame(() => (dibujado = true));
    return () => cancelAnimationFrame(cuadro);
  });

  function dichoDeLaHoja(hoja: HojaDeLaCinta): string {
    const partes = [`Hoja ${hoja.pagina}`];
    if (hoja.documento >= 0) partes.push(`en el PDF ${String(hoja.documento + 1).padStart(2, '0')}`);
    if (hoja.movida) partes.push(`movida por el agente: ${queMovio(hoja.movida)}`);
    if (hoja.revision) partes.push(`a revisión: ${hoja.revision}`);
    return partes.join(' · ');
  }

  function dichoDeLaCostura(costura: CosturaDeLaCinta): string {
    const como = costura.tipo === 'union' ? 'en el mismo PDF' : 'en PDF distintos';
    const que = RESULTADOS[costura.resultado].etiqueta;
    const porque = costura.motivo ? ` · ${costura.motivo}` : '';
    const fe = costura.confianza !== null ? ` · confianza ${Math.round(costura.confianza * 100)} %` : '';
    return `Hojas ${costura.izq} y ${costura.der}, ${como}: ${que}${fe}${porque}`;
  }
</script>

<section class="panel agente" data-tono={revision ? estado.tono : comprobacion?.problemas.length ? 'bad' : 'good'}>
  <header class="cabeza">
    <span class="marca" aria-hidden="true"><Icono nombre="escudo" /></span>
    <div class="min-w-0">
      <h2 class="titulo">Agente revisor</h2>
      <p class="frase">
        {revision ? frase(revision, paginas) : 'Comprobó en el disco cada PDF que se escribió.'}
      </p>
      {#if revision?.perfil}
        <!-- Con qué patrones revisó: los de su habilidad, del mismo registro que usa la auditoría. -->
        <p class="perfil">
          Con los patrones de <b>{revision.perfil.nombre}</b> · {revision.perfil.corrige
            ? 'corrige lo seguro'
            : 'señala sin mover hojas'}{revision.perfil.una_persona_por_pdf ? ' · una persona por PDF' : ''}
        </p>
      {/if}
    </div>
    {#if revision}
      <span class="pill estado" data-tono={estado.tono}>
        <Icono nombre={estado.tono === 'good' ? 'hecho' : estado.tono === 'accent' ? 'editar' : 'aviso'} />
        {estado.etiqueta}
      </span>
    {/if}
  </header>

  {#if revision}
    <div class="resumen">
      {#if total}
        <figure class="anillo" aria-label={`${dentro} de ${total} costuras dentro del margen de error`}>
          <svg viewBox="0 0 100 100" aria-hidden="true">
            <circle class="pista" cx="50" cy="50" r={RADIO} />
            {#each arcos as arco (arco.clave)}
              <circle
                class="arco"
                data-tono={arco.tono}
                cx="50"
                cy="50"
                r={RADIO}
                stroke-dasharray={`${dibujado ? arco.largo : 0} ${VUELTA}`}
                stroke-dashoffset={-arco.desde}
                transform="rotate(-90 50 50)"
              >
                <title>{arco.etiqueta}: {arco.valor}</title>
              </circle>
            {/each}
          </svg>
          <figcaption class="centro">
            <strong class="tabular">{porcentaje(dentro, total)}</strong>
            <span>dentro del margen</span>
          </figcaption>
        </figure>
      {/if}

      <dl class="cifras">
        <div class="stat">
          <dt class="stat-label">Costuras revisadas</dt>
          <dd class="stat-value">{total}</dd>
          <dd class="stat-note">Entre {paginas} hojas</dd>
        </div>
        <div class="stat good">
          <dt class="stat-label">Dentro del margen</dt>
          <dd class="stat-value">{dentro}</dd>
          <dd class="stat-note">Validadas sin gastar</dd>
        </div>
        <div class="stat" data-tono="ia">
          <dt class="stat-label">Decididas por la IA</dt>
          <dd class="stat-value">{revision.preguntadas_a_la_ia ?? 0}</dd>
          <dd class="stat-note">
            {#if revision.ia_no_respondio}
              La IA no respondió
            {:else if revision.preguntadas_a_la_ia}
              {revision.confirmadas_por_la_ia ?? 0} le dieron la razón al bot
            {:else}
              No hizo falta
            {/if}
          </dd>
        </div>
        <div class="stat" data-tono={movimientos.length ? 'accent' : undefined}>
          <dt class="stat-label">Corregidas</dt>
          <dd class="stat-value">{movimientos.length}</dd>
          <dd class="stat-note">{movimientos.length ? 'Detalle abajo' : 'Nada que mover'}</dd>
        </div>
        <div class="stat" class:warn={aRevision.length}>
          <dt class="stat-label">A revisión</dt>
          <dd class="stat-value">{aRevision.length}</dd>
          <dd class="stat-note">{aRevision.length ? 'Para mirar' : 'Sin pendientes'}</dd>
        </div>
        {#if comprobacion?.comprobada}
          <div class="stat" class:good={!problemas.length} class:bad={problemas.length}>
            <dt class="stat-label">En el disco</dt>
            <dd class="stat-value">
              {problemas.length ? problemas.length : `${comprobacion.hojas ?? 0}/${comprobacion.hojas ?? 0}`}
            </dd>
            <dd class="stat-note">
              {problemas.length ? (problemas.length === 1 ? 'Problema' : 'Problemas') : 'Hojas en su sitio'}
            </dd>
          </div>
        {/if}
      </dl>
    </div>

    {#if datos && datos.hojas.length > 1}
      <div class="caps rotulo">Cada hoja y cada costura</div>
      <!-- El barrido pasa una vez sobre la cinta al aparecer: el agente
           revisándola. Es la animación `avance` del sistema, sin repetir. -->
      <div class="cinta" class:dibujado role="list" aria-label="Las hojas del PDF de origen y lo que el agente hizo con cada costura">
        {#each datos.hojas as hoja, i (hoja.pagina)}
          <div class="paso" role="listitem" style:--i={Math.min(i, 48)}>
            <span
              class="hoja"
              data-doc={hoja.documento < 0 ? 'x' : hoja.documento % 4}
              class:abre={hoja.abre}
              class:movida={hoja.movida}
              class:dudosa={hoja.revision}
              title={dichoDeLaHoja(hoja)}
            >
              {#if hoja.abre && hoja.documento >= 0}
                <span class="doc">{String(hoja.documento + 1).padStart(2, '0')}</span>
              {/if}
              <span class="tabular">{hoja.pagina}</span>
            </span>
            {#if datos.costuras[i]}
              <span
                class="costura"
                data-tipo={datos.costuras[i].tipo}
                data-resultado={datos.costuras[i].resultado}
                title={dichoDeLaCostura(datos.costuras[i])}
              ></span>
            {/if}
          </div>
        {/each}
      </div>
      <ul class="leyenda">
        <li><span class="muestra" data-ejemplo="union"></span>Mismo PDF</li>
        <li><span class="muestra" data-ejemplo="corte"></span>Corte entre PDF</li>
        {#each MARCADOS as resultado (resultado)}
          {#if resultados.has(resultado)}
            <li><span class="muestra" data-resultado={resultado}></span>{RESULTADOS[resultado].etiqueta}</li>
          {/if}
        {/each}
        {#if movimientos.length}
          <li><span class="muestra movida"></span>Hoja movida por el agente</li>
        {/if}
        <li class="apagado">{datos.documentos} PDF · el número de arriba es el de cada PDF</li>
      </ul>
    {/if}

    {#if movimientos.length}
      <ol class="lista">
        {#each movimientos as movimiento, i (i)}
          <li class="correccion" style:--i={i}>
            <span class="icono-fila" data-tono="accent" aria-hidden="true"><Icono nombre="hecho" /></span>
            <div class="min-w-0">
              <p class="que">
                <strong>{queMovio(movimiento)}</strong>
                <span class="pill pill-sm">{porQuien(movimiento.por)}</span>
              </p>
              <p class="porque">{movimiento.motivo}</p>
            </div>
          </li>
        {/each}
      </ol>
    {/if}

    {#if aRevision.length}
      <ol class="lista">
        {#each aRevision as item, i (i)}
          <li class="correccion" style:--i={i}>
            <span class="icono-fila" data-tono="warn" aria-hidden="true"><Icono nombre="aviso" /></span>
            <div class="min-w-0">
              <p class="que"><strong>Hoja {item.page}</strong> <span class="pill pill-sm pill-warn">A revisión</span></p>
              <p class="porque">{item.reason}</p>
            </div>
          </li>
        {/each}
      </ol>
    {/if}
  {/if}

  {#if comprobacion}
    <p class="disco" data-ok={comprobacion.comprobada && !problemas.length ? 'si' : 'no'}>
      <Icono nombre={comprobacion.comprobada && !problemas.length ? 'hecho' : 'aviso'} />
      {comprobacion.resumen}
    </p>
    {#if problemas.length > 1}
      <ul class="problemas">
        {#each problemas.slice(1) as problema, i (i)}
          <li>{problema.texto}</li>
        {/each}
      </ul>
    {/if}
  {/if}

  {#if integridad?.documentos}
    <!-- Los datos de cada documento contra lo que espera su habilidad (2026-11-06). -->
    <DatosDelAgente datos={integridad} hallazgos={integridad.hallazgos} />
  {/if}
</section>

<style>
  /* El tono de cada estado y resultado, en un solo sitio. */
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

  /* La tarjeta lleva el tono de su estado en el filete de arriba y un halo
     muy suave detrás del escudo: se distingue de las demás sin gritar. */
  .agente {
    position: relative;
    overflow: hidden;
    border-top: 3px solid var(--tono);
    background:
      radial-gradient(120% 90% at 0% 0%, color-mix(in srgb, var(--tono) 7%, transparent), transparent 55%),
      var(--surface-2);
  }

  .cabeza {
    display: flex;
    align-items: flex-start;
    gap: var(--space-3);
  }
  .marca {
    --icono: 1.35rem;
    display: grid;
    width: 44px;
    height: 44px;
    flex: none;
    place-items: center;
    border-radius: var(--radius-lg);
    background: color-mix(in srgb, var(--tono) 14%, var(--surface-2));
    color: var(--tono);
    box-shadow: 0 0 0 4px color-mix(in srgb, var(--tono) 7%, transparent);
  }
  .titulo {
    margin: 0;
    font-size: var(--text-lg);
    font-weight: 650;
    letter-spacing: -0.01em;
    color: var(--ink);
  }
  .frase {
    margin: 2px 0 0;
    font-size: var(--text-md);
    line-height: 1.45;
    color: var(--ink-2);
  }
  .perfil {
    margin: 2px 0 0;
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .perfil b {
    font-weight: 600;
    color: var(--ink-2);
  }
  .estado {
    margin-left: auto;
    flex: none;
    background: color-mix(in srgb, var(--tono) 13%, transparent);
    color: color-mix(in srgb, var(--tono) 75%, var(--ink));
  }

  .resumen {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-6);
    margin-top: var(--space-5);
  }

  /* El anillo: la pista gris y un arco por tramo, que se dibujan al aparecer. */
  .anillo {
    position: relative;
    width: 132px;
    height: 132px;
    flex: none;
    margin: 0;
  }
  .anillo svg {
    width: 100%;
    height: 100%;
  }
  .pista {
    fill: none;
    stroke: var(--grid);
    stroke-width: 9;
  }
  .arco {
    fill: none;
    stroke: var(--tono);
    stroke-width: 9;
    stroke-linecap: butt;
    transition: stroke-dasharray 900ms var(--ease-out);
  }
  .centro {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
  }
  .centro strong {
    font-size: var(--text-stat);
    font-weight: 650;
    line-height: 1;
    letter-spacing: -0.03em;
    color: var(--ink);
  }
  .centro span {
    max-width: 78px;
    margin-top: 4px;
    font-size: var(--text-2xs);
    line-height: 1.2;
    color: var(--muted);
  }

  .cifras {
    display: flex;
    flex: 1;
    flex-wrap: wrap;
    gap: var(--space-4) var(--space-6);
    min-width: 0;
    margin: 0;
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

  .rotulo {
    margin: var(--space-6) 0 var(--space-2);
  }

  /* La cinta: una casilla por hoja del original, del color del PDF en que
     salió, y entre dos casillas su costura. */
  .cinta {
    position: relative;
    display: flex;
    flex-wrap: wrap;
    row-gap: var(--space-3);
    padding: var(--space-3);
    border-radius: var(--radius-md);
    background: var(--plane);
    overflow: hidden;
  }
  /* El barrido: el agente pasa una vez por encima, al aparecer. */
  .cinta::after {
    content: '';
    position: absolute;
    inset: 0;
    width: 35%;
    background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--accent) 16%, transparent), transparent);
    transform: translateX(-100%);
    pointer-events: none;
  }
  .cinta.dibujado::after {
    animation: avance 1.6s var(--ease-in-out) 1 both;
  }
  .paso {
    display: flex;
    align-items: center;
    animation: entrada var(--duration-slow) var(--ease-out) both;
    animation-delay: calc(var(--i) * 18ms);
  }

  .hoja {
    --doc: var(--axis);
    position: relative;
    display: grid;
    min-width: 30px;
    height: 34px;
    place-items: center;
    padding: 0 6px;
    border-radius: var(--radius-sm);
    border-bottom: 3px solid var(--doc);
    background: color-mix(in srgb, var(--doc) 15%, var(--surface-2));
    font-size: var(--text-xs);
    font-weight: 600;
    color: var(--ink);
    cursor: default;
  }
  .hoja[data-doc='0'] {
    --doc: var(--s1);
  }
  .hoja[data-doc='1'] {
    --doc: var(--s3);
  }
  .hoja[data-doc='2'] {
    --doc: var(--s4);
  }
  .hoja[data-doc='3'] {
    --doc: var(--s2);
  }
  /* El número del PDF, sobre la hoja que lo abre. */
  .doc {
    position: absolute;
    top: -9px;
    left: 3px;
    padding: 0 4px;
    border-radius: var(--radius-xs);
    background: var(--doc);
    font-family: var(--font-mono);
    font-size: 9px;
    line-height: 14px;
    color: var(--surface-2);
  }
  .hoja.movida {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    box-shadow: 0 0 0 6px color-mix(in srgb, var(--accent) 12%, transparent);
  }
  .hoja.dudosa {
    outline: 2px dashed var(--warning);
    outline-offset: 2px;
  }

  /* La costura: un puente si las dos hojas salieron en el mismo PDF, un
     hueco con una raya si salieron en dos. Fuera del margen se marca con el
     tono de lo que se hizo y un punto encima. */
  .costura {
    --res: var(--axis);
    position: relative;
    display: block;
    flex: none;
  }
  .costura[data-tipo='union'] {
    width: 8px;
    height: 3px;
    background: var(--res);
  }
  .costura[data-tipo='corte'] {
    width: 14px;
    height: 22px;
  }
  .costura[data-tipo='corte']::before {
    content: '';
    position: absolute;
    left: 6px;
    top: 0;
    bottom: 0;
    width: 2px;
    border-radius: 1px;
    background: color-mix(in srgb, var(--res) 60%, transparent);
  }
  .costura[data-resultado='corregida'] {
    --res: var(--accent);
  }
  .costura[data-resultado='confirmada'] {
    --res: var(--s4);
  }
  .costura[data-resultado='revision'] {
    --res: var(--warning);
  }
  .costura:not([data-resultado='validada'])::after {
    content: '';
    position: absolute;
    left: 50%;
    top: -12px;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--res);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--res) 22%, transparent);
    transform: translateX(-50%);
  }

  .leyenda {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-4);
    margin: var(--space-3) 0 0;
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
  .leyenda .apagado {
    color: var(--muted);
  }
  .muestra {
    display: inline-block;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--axis);
  }
  .muestra[data-ejemplo='union'] {
    height: 3px;
    border-radius: 2px;
  }
  .muestra[data-ejemplo='corte'] {
    width: 2px;
    height: 12px;
    border-radius: 1px;
  }
  .muestra[data-resultado='corregida'] {
    background: var(--accent);
  }
  .muestra[data-resultado='confirmada'] {
    background: var(--s4);
  }
  .muestra[data-resultado='revision'] {
    background: var(--warning);
  }
  .muestra.movida {
    border-radius: var(--radius-xs);
    background: transparent;
    outline: 2px solid var(--accent);
  }

  .lista {
    display: grid;
    gap: var(--space-2);
    margin: var(--space-5) 0 0;
    padding: 0;
    list-style: none;
  }
  .correccion {
    display: flex;
    gap: var(--space-3);
    padding: var(--space-3);
    border-radius: var(--radius-md);
    background: var(--surface-1);
    border: 1px solid var(--hairline);
    animation: entrada var(--duration-slow) var(--ease-out) both;
    animation-delay: calc(400ms + var(--i) * 60ms);
  }
  .icono-fila {
    display: grid;
    width: 26px;
    height: 26px;
    flex: none;
    place-items: center;
    border-radius: 50%;
    background: color-mix(in srgb, var(--tono) 14%, transparent);
    color: var(--tono);
  }
  .que {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    margin: 0;
    font-size: var(--text-md);
    color: var(--ink);
  }
  .porque {
    margin: 2px 0 0;
    font-size: var(--text-sm);
    line-height: 1.45;
    color: var(--ink-2);
    overflow-wrap: anywhere;
  }

  .disco {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin: var(--space-5) 0 0;
    padding-top: var(--space-3);
    border-top: 1px solid var(--rule);
    font-size: var(--text-sm);
    color: color-mix(in srgb, var(--good) 70%, var(--ink));
  }
  .disco[data-ok='no'] {
    color: var(--critical);
  }
  .problemas {
    margin: var(--space-2) 0 0;
    padding-left: var(--space-6);
    font-size: var(--text-sm);
    color: var(--critical);
  }

  @media (max-width: 520px) {
    .cabeza {
      flex-wrap: wrap;
    }
    .estado {
      margin-left: 56px;
    }
    /* En el teléfono, el anillo arriba y las cifras debajo, de dos en dos. */
    .resumen {
      flex-direction: column;
      align-items: stretch;
      gap: var(--space-5);
    }
    .anillo {
      align-self: center;
    }
    .cifras {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: var(--space-4) var(--space-3);
    }
  }
</style>
