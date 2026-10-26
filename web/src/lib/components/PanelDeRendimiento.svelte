<script lang="ts">
  import { onMount } from 'svelte';
  import { formatDuration } from '$lib/format';
  import {
    acumularEtapas,
    horaDeFin,
    procedencia,
    reducirMuestras,
    restante,
    techo,
    velocidadMedia,
    type Muestra
  } from '$lib/rendimiento';
  import { STAGE_LABELS } from '$lib/rungs';
  import Icono from '$lib/components/Icono.svelte';
  import type { Consumo } from '$lib/types';

  interface Documentos {
    hechos: number;
    fallidos: number;
    enCola: number;
    /** Cuántos hay en total, si se sabe. Una carpeta vigilada no lo sabe. */
    total: number | null;
  }

  interface Props {
    paginasHechas: number;
    /** Cero si todavía no se sabe. */
    paginasTotal: number;
    /** Páginas por segundo ahora mismo. */
    velocidad: number;
    segundos: number;
    /** La etapa de cada documento abierto ahora. */
    etapas?: (string | null | undefined)[];
    /** El reparto por peldaño de cada documento. */
    procedencias?: Record<string, number>[];
    revision?: number;
    fallidas?: number;
    documentos?: Documentos | null;
    consumo?: Consumo | null;
    vivo: boolean;
  }

  let {
    paginasHechas,
    paginasTotal,
    velocidad,
    segundos,
    etapas = [],
    procedencias = [],
    revision = 0,
    fallidas = 0,
    documentos = null,
    consumo = null,
    vivo
  }: Props = $props();

  /** Una muestra por segundo; al llenarse se juntan de a dos (ver `reducirMuestras`). */
  const INTERVALO_MS = 1000;
  const CAPACIDAD = 600;

  let muestras = $state<Muestra[]>([]);
  let tiempoPorEtapa = $state<Record<string, number>>({});
  let abierto = $state(true);

  onMount(() => {
    try {
      abierto = localStorage.getItem('rendimiento.abierto') !== 'no';
    } catch {
      // Sin almacenamiento se queda abierto.
    }
    let anterior = Date.now();
    const reloj = setInterval(() => {
      const ahora = Date.now();
      const paso = (ahora - anterior) / 1000;
      anterior = ahora;
      if (!vivo) return;
      tiempoPorEtapa = acumularEtapas(tiempoPorEtapa, etapas, paso);
      const nueva: Muestra = {
        t: ahora,
        paginas: paginasHechas,
        documentos: documentos?.hechos ?? 0,
        velocidad: Math.max(0, velocidad)
      };
      // La pantalla se abre a mitad de corrida: el origen se pone a mano para
      // que la curva de avance arranque donde arrancó el trabajo y no aquí.
      const previas =
        muestras.length === 0 && segundos > 2 && paginasHechas > 0
          ? [{ t: ahora - segundos * 1000, paginas: 0, documentos: 0, velocidad: 0 }]
          : muestras;
      muestras = reducirMuestras([...previas, nueva], CAPACIDAD);
    }, INTERVALO_MS);
    return () => clearInterval(reloj);
  });

  function alternar(evento: Event) {
    abierto = (evento.currentTarget as HTMLDetailsElement).open;
    try {
      localStorage.setItem('rendimiento.abierto', abierto ? 'si' : 'no');
    } catch {
      // Se recuerda sólo mientras dure la pantalla.
    }
  }

  // -- cifras -----------------------------------------------------------------

  const media = $derived(velocidadMedia(paginasHechas, segundos));
  const pico = $derived(muestras.reduce((tope, m) => Math.max(tope, m.velocidad), velocidad));
  const faltan = $derived(restante(paginasHechas, paginasTotal, velocidad, media));
  const fin = $derived(horaDeFin(faltan));
  const avance = $derived(paginasTotal ? Math.min(100, (100 * paginasHechas) / paginasTotal) : null);

  const documentosPorMinuto = $derived(
    documentos && segundos >= 1 ? (documentos.hechos * 60) / segundos : 0
  );
  const faltanPorDocumentos = $derived.by(() => {
    if (!documentos || documentosPorMinuto <= 0) return null;
    const pendientes = documentos.total !== null ? documentos.total - documentos.hechos - documentos.fallidos : documentos.enCola;
    return pendientes > 0 ? (pendientes * 60) / documentosPorMinuto : null;
  });

  function cifra(valor: number, decimales = 1): string {
    return valor.toLocaleString('es', {
      minimumFractionDigits: decimales,
      maximumFractionDigits: decimales
    });
  }
  function entero(valor: number): string {
    return Math.round(valor).toLocaleString('es');
  }

  // -- gráfica de avance y velocidad ------------------------------------------

  const ANCHO = 640;
  const ALTO = 170;
  const MARGEN = { arriba: 12, derecha: 40, abajo: 22, izquierda: 44 };
  const anchoUtil = ANCHO - MARGEN.izquierda - MARGEN.derecha;
  const altoUtil = ALTO - MARGEN.arriba - MARGEN.abajo;

  /** Lo que se dibuja: las muestras, o -- cerrada la corrida sin muestras -- su media. */
  const serie = $derived.by<Muestra[]>(() => {
    if (muestras.length > 1) return muestras;
    if (!vivo && paginasHechas > 0 && segundos > 0) {
      const ahora = Date.now();
      return [
        { t: ahora - segundos * 1000, paginas: 0, documentos: 0, velocidad: media },
        { t: ahora, paginas: paginasHechas, documentos: documentos?.hechos ?? 0, velocidad: media }
      ];
    }
    return [];
  });

  const desde = $derived(serie[0]?.t ?? 0);
  const hasta = $derived(serie.at(-1)?.t ?? 1);
  const techoPaginas = $derived(techo(Math.max(paginasTotal, ...serie.map((m) => m.paginas))));
  const techoVelocidad = $derived(techo(Math.max(...serie.map((m) => m.velocidad), 0.5)));

  function x(t: number): number {
    return MARGEN.izquierda + ((t - desde) / Math.max(hasta - desde, 1)) * anchoUtil;
  }
  function yPaginas(valor: number): number {
    return MARGEN.arriba + altoUtil - (valor / techoPaginas) * altoUtil;
  }
  function yVelocidad(valor: number): number {
    return MARGEN.arriba + altoUtil - (valor / techoVelocidad) * altoUtil;
  }

  const lineaPaginas = $derived(serie.map((m) => `${x(m.t)},${yPaginas(m.paginas)}`).join(' '));
  const areaPaginas = $derived(
    serie.length
      ? `${x(desde)},${MARGEN.arriba + altoUtil} ${lineaPaginas} ${x(hasta)},${MARGEN.arriba + altoUtil}`
      : ''
  );
  const lineaVelocidad = $derived(
    serie.map((m) => `${x(m.t)},${yVelocidad(m.velocidad)}`).join(' ')
  );
  const lineaMedia = $derived(media > 0 ? yVelocidad(media) : null);

  /** Marcas del eje del tiempo: cinco, en minutos desde el arranque. */
  const marcasDeTiempo = $derived.by(() => {
    if (serie.length < 2) return [];
    const duracion = (hasta - desde) / 1000;
    return [0, 0.25, 0.5, 0.75, 1].map((f) => ({
      x: MARGEN.izquierda + f * anchoUtil,
      texto: formatDuration(duracion * f).replace(' s', 's').replace(' min ', 'm ')
    }));
  });

  let senalada = $state<number | null>(null);
  const punto = $derived(senalada === null ? null : serie[senalada]);

  function seguir(evento: PointerEvent) {
    if (serie.length < 2) return;
    const caja = (evento.currentTarget as SVGSVGElement).getBoundingClientRect();
    const local = ((evento.clientX - caja.left) / caja.width) * ANCHO;
    const t = desde + ((local - MARGEN.izquierda) / anchoUtil) * (hasta - desde);
    let mejor = 0;
    for (let i = 1; i < serie.length; i++) {
      if (Math.abs(serie[i].t - t) < Math.abs(serie[mejor].t - t)) mejor = i;
    }
    senalada = mejor;
  }

  function reloj(t: number): string {
    return new Date(t).toLocaleTimeString('es', { hour12: false });
  }

  // -- reparto ----------------------------------------------------------------

  const porciones = $derived(procedencia(procedencias));
  const totalPorciones = $derived(porciones.reduce((s, p) => s + p.valor, 0) || 1);

  /** Las etapas en el orden en que corren, no en el de cuánto tardaron. */
  const ORDEN_DE_ETAPAS = [
    'queued',
    'analysing',
    'identifying',
    'verifying',
    'grouping',
    'assembling',
    'inventorying',
    'delivering'
  ];
  const etapasMedidas = $derived(
    Object.entries(tiempoPorEtapa)
      .sort(([a], [b]) => {
        const ia = ORDEN_DE_ETAPAS.indexOf(a);
        const ib = ORDEN_DE_ETAPAS.indexOf(b);
        return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
      })
      .map(([clave, valor]) => ({ clave, etiqueta: STAGE_LABELS[clave] ?? clave, valor }))
  );
  const etapaMasLarga = $derived(Math.max(...etapasMedidas.map((e) => e.valor), 1));
  const tiempoDeEtapas = $derived(etapasMedidas.reduce((s, e) => s + e.valor, 0) || 1);
  const etapaActual = $derived(new Set(etapas.filter(Boolean)));

  const totalDocumentos = $derived(
    documentos
      ? Math.max(
          documentos.total ?? 0,
          documentos.hechos + documentos.fallidos + documentos.enCola,
          1
        )
      : 1
  );

  const conIA = $derived(Boolean(consumo && consumo.peticiones));
</script>

<details class="rendimiento" open={abierto} ontoggle={alternar}>
  <summary>
    <span class="flecha"><Icono nombre="chevron" /></span>
    <span class="titulo">Rendimiento detallado</span>
    <span class="resumen tabular">
      {cifra(velocidad)} p/s ahora · {cifra(media)} p/s de media
      {#if faltan !== null}· faltan {formatDuration(faltan)}{/if}
    </span>
  </summary>

  <!-- Las cifras van también en texto: la gráfica no es la única forma de leerlas. -->
  <div class="cifras">
    <div class="stat">
      <span class="stat-label">Velocidad ahora</span>
      <b class="stat-value">{cifra(velocidad)} <small>p/s</small></b>
      <span class="stat-note tabular">{entero(velocidad * 60)} páginas por minuto</span>
    </div>
    <div class="stat">
      <span class="stat-label">Velocidad media</span>
      <b class="stat-value">{cifra(media)} <small>p/s</small></b>
      <span class="stat-note tabular">{entero(media * 60)} p/min · {entero(media * 3600)} p/hora</span>
    </div>
    <div class="stat">
      <span class="stat-label">Pico</span>
      <b class="stat-value">{cifra(pico)} <small>p/s</small></b>
      <span class="stat-note">la más alta medida en esta pantalla</span>
    </div>
    <div class="stat">
      <span class="stat-label">Tiempo transcurrido</span>
      <b class="stat-value">{segundos >= 1 ? formatDuration(segundos) : '—'}</b>
      <span class="stat-note tabular">
        {paginasHechas && segundos ? `${cifra(segundos / paginasHechas, 2)} s por página` : 'midiendo…'}
      </span>
    </div>
    <div class="stat">
      <span class="stat-label">Tiempo restante</span>
      <b class="stat-value">{faltan !== null ? formatDuration(faltan) : vivo ? 'calculando…' : '—'}</b>
      <span class="stat-note">{fin ? `termina hacia las ${fin}` : vivo ? 'falta saber el total' : 'terminado'}</span>
    </div>
    <div class="stat">
      <span class="stat-label">Páginas</span>
      <b class="stat-value">
        {entero(paginasHechas)}{#if paginasTotal}<small> / {entero(paginasTotal)}</small>{/if}
      </b>
      <span class="stat-note tabular">
        {avance !== null ? `${cifra(avance)} % hecho` : 'total por contar'}
      </span>
    </div>
    <div class="stat" class:warn={revision > 0}>
      <span class="stat-label">Por revisar</span>
      <b class="stat-value">{entero(revision)}</b>
      <span class="stat-note">páginas marcadas para mirar</span>
    </div>
    <div class="stat" class:bad={fallidas > 0}>
      <span class="stat-label">Páginas con fallo</span>
      <b class="stat-value">{entero(fallidas)}</b>
      <span class="stat-note">{fallidas ? 'no se pudieron leer' : 'ninguna'}</span>
    </div>
    {#if documentos}
      <div class="stat">
        <span class="stat-label">Documentos por minuto</span>
        <b class="stat-value">{cifra(documentosPorMinuto, 2)}</b>
        <span class="stat-note tabular">
          {faltanPorDocumentos !== null
            ? `al ritmo de documentos, faltan ${formatDuration(faltanPorDocumentos)}`
            : `${entero(documentos.hechos)} hechos`}
        </span>
      </div>
    {/if}
  </div>

  <figure class="grafica">
    <figcaption>
      <span class="caps">Avance y velocidad en el tiempo</span>
      <span class="leyenda">
        <span><i style:background="var(--s1)"></i>páginas hechas</span>
        <span><i class="linea" style:background="var(--s2)"></i>páginas por segundo</span>
        {#if lineaMedia !== null}<span><i class="trazos"></i>media</span>{/if}
      </span>
    </figcaption>

    {#if serie.length > 1}
      <svg
        viewBox="0 0 {ANCHO} {ALTO}"
        preserveAspectRatio="none"
        role="img"
        aria-label={`Avance: ${paginasHechas} páginas en ${formatDuration(segundos)}; velocidad ahora ${cifra(velocidad)}, media ${cifra(media)}, pico ${cifra(pico)} páginas por segundo`}
        onpointermove={seguir}
        onpointerleave={() => (senalada = null)}
      >
        {#each [0, 0.25, 0.5, 0.75, 1] as f (f)}
          <line
            class="rejilla"
            x1={MARGEN.izquierda}
            x2={ANCHO - MARGEN.derecha}
            y1={MARGEN.arriba + altoUtil * f}
            y2={MARGEN.arriba + altoUtil * f}
          />
        {/each}
        <!-- Eje izquierdo: páginas. Derecho: páginas por segundo. -->
        <text class="eje" x={MARGEN.izquierda - 6} y={MARGEN.arriba + 4} text-anchor="end">
          {entero(techoPaginas)}
        </text>
        <text class="eje" x={MARGEN.izquierda - 6} y={MARGEN.arriba + altoUtil / 2 + 3} text-anchor="end">
          {entero(techoPaginas / 2)}
        </text>
        <text class="eje" x={MARGEN.izquierda - 6} y={MARGEN.arriba + altoUtil} text-anchor="end">0</text>
        <text class="eje" x={ANCHO - MARGEN.derecha + 6} y={MARGEN.arriba + 4}>{cifra(techoVelocidad)}</text>
        <text class="eje" x={ANCHO - MARGEN.derecha + 6} y={MARGEN.arriba + altoUtil / 2 + 3}>
          {cifra(techoVelocidad / 2)}
        </text>
        {#each marcasDeTiempo as marca (marca.x)}
          <text class="eje" x={marca.x} y={ALTO - 6} text-anchor="middle">{marca.texto}</text>
        {/each}

        <polygon class="area" points={areaPaginas} />
        <polyline class="paginas" points={lineaPaginas} />
        <polyline class="velocidad" points={lineaVelocidad} />
        {#if lineaMedia !== null}
          <line class="media" x1={MARGEN.izquierda} x2={ANCHO - MARGEN.derecha} y1={lineaMedia} y2={lineaMedia} />
        {/if}

        {#if punto}
          <line class="cruz" x1={x(punto.t)} x2={x(punto.t)} y1={MARGEN.arriba} y2={MARGEN.arriba + altoUtil} />
          <circle cx={x(punto.t)} cy={yPaginas(punto.paginas)} r="4" class="punto-paginas" />
          <circle cx={x(punto.t)} cy={yVelocidad(punto.velocidad)} r="4" class="punto-velocidad" />
        {/if}
      </svg>
      {#if punto}
        <p class="detalle tabular">
          {reloj(punto.t)} · <b>{entero(punto.paginas)}</b> páginas · <b>{cifra(punto.velocidad)}</b> p/s
          {#if documentos}· {entero(punto.documentos)} documentos{/if}
        </p>
      {:else}
        <p class="detalle">Pase el puntero por la gráfica para ver cada momento.</p>
      {/if}
    {:else}
      <p class="esperando">Midiendo… la gráfica aparece en un par de segundos.</p>
    {/if}
  </figure>

  <div class="dos">
    <figure class="grafica">
      <figcaption><span class="caps">Dónde se resolvió cada página</span></figcaption>
      {#if porciones.length}
        <div class="progress composicion" role="img" aria-label={porciones.map((p) => `${p.etiqueta}: ${p.valor}`).join(', ')}>
          {#each porciones as p (p.clave)}
            <div class="progress-fill" style:width={`${(100 * p.valor) / totalPorciones}%`} style:background={p.color}></div>
          {/each}
        </div>
        <ul class="lista">
          {#each porciones as p (p.clave)}
            <li>
              <i style:background={p.color}></i>
              <span>{p.etiqueta}</span>
              <b class="tabular">{entero(p.valor)}</b>
              <small class="tabular">{cifra((100 * p.valor) / totalPorciones)} %</small>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="esperando">Todavía no hay páginas leídas.</p>
      {/if}
    </figure>

    <figure class="grafica">
      <figcaption><span class="caps">Tiempo por etapa</span></figcaption>
      {#if etapasMedidas.length}
        <ul class="etapas">
          {#each etapasMedidas as e (e.clave)}
            <li class:viva={etapaActual.has(e.clave)}>
              <span class="nombre">{e.etiqueta}</span>
              <span class="pista"><span style:width={`${(100 * e.valor) / etapaMasLarga}%`}></span></span>
              <b class="tabular">{formatDuration(e.valor)}</b>
              <small class="tabular">{cifra((100 * e.valor) / tiempoDeEtapas, 0)} %</small>
            </li>
          {/each}
        </ul>
        <p class="pie">Medido desde que se abrió esta pantalla. Con varios documentos a la vez, cada uno suma su tiempo.</p>
      {:else}
        <p class="esperando">{vivo ? 'Midiendo…' : 'Se mide mientras el trabajo corre con esta pantalla abierta.'}</p>
      {/if}
    </figure>
  </div>

  {#if documentos || conIA}
    <div class="dos">
      {#if documentos}
        <figure class="grafica">
          <figcaption><span class="caps">Documentos</span></figcaption>
          <div class="progress composicion" role="img" aria-label={`${documentos.hechos} hechos, ${documentos.fallidos} con fallo, ${documentos.enCola} en cola`}>
            <div class="progress-fill good" style:width={`${(100 * documentos.hechos) / totalDocumentos}%`}></div>
            <div class="progress-fill bad" style:width={`${(100 * documentos.fallidos) / totalDocumentos}%`}></div>
            <div class="progress-fill idle" style:width={`${(100 * documentos.enCola) / totalDocumentos}%`}></div>
          </div>
          <ul class="lista">
            <li><i style:background="var(--good)"></i><span>Hechos</span><b class="tabular">{entero(documentos.hechos)}</b></li>
            <li><i style:background="var(--critical)"></i><span>Con fallo</span><b class="tabular">{entero(documentos.fallidos)}</b></li>
            <li><i style:background="var(--axis)"></i><span>En cola</span><b class="tabular">{entero(documentos.enCola)}</b></li>
            {#if documentos.total !== null}
              <li><i></i><span>Total</span><b class="tabular">{entero(documentos.total)}</b></li>
            {/if}
          </ul>
        </figure>
      {/if}

      {#if consumo && conIA}
        <figure class="grafica">
          <figcaption><span class="caps">Consumo de IA</span></figcaption>
          <dl class="consumo">
            <dt>Peticiones</dt><dd class="tabular">{entero(consumo.peticiones)}</dd>
            <dt>Páginas facturadas</dt><dd class="tabular">{entero(consumo.paginas_facturadas)}</dd>
            <dt>Tokens de entrada</dt><dd class="tabular">{entero(consumo.tokens_entrada)}</dd>
            <dt>Tokens de salida</dt><dd class="tabular">{entero(consumo.tokens_salida)}</dd>
            {#if consumo.rechazos || consumo.fallos}
              <dt>Rechazos / fallos</dt>
              <dd class="tabular">{entero(consumo.rechazos)} / {entero(consumo.fallos)}</dd>
            {/if}
            {#if consumo.coste_estimado !== null}
              <dt>Coste estimado</dt>
              <dd class="tabular">{cifra(consumo.coste_estimado, 4)} {consumo.moneda}</dd>
            {/if}
            {#if paginasHechas}
              <dt>Páginas que fueron a la IA</dt>
              <dd class="tabular">{cifra((100 * consumo.paginas_facturadas) / paginasHechas)} %</dd>
            {/if}
          </dl>
        </figure>
      {/if}
    </div>
  {/if}
</details>

<style>
  /* Una sección plegable dentro del monitor, que ya es un `.panel`: no es otra
     tarjeta con sombra, es el plano del monitor un tono más abajo. Se llamaba
     `.panel` y pisaba la tarjeta común. */
  .rendimiento {
    border: 1px solid var(--hairline);
    border-radius: var(--radius-lg);
    background: var(--surface-1);
    padding: 2px var(--space-4);
  }
  .rendimiento[open] {
    padding-bottom: var(--space-4);
  }

  summary {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-1) var(--space-4);
    padding: var(--space-2) 0;
    cursor: pointer;
    list-style: none;
  }
  summary::-webkit-details-marker {
    display: none;
  }
  .flecha {
    display: inline-flex;
    color: var(--muted);
    transition: transform var(--duration-fast) var(--ease-out);
  }
  .rendimiento[open] .flecha {
    transform: rotate(90deg);
  }
  .titulo {
    flex: 1;
    font-size: var(--text-sm);
    font-weight: 650;
  }
  .resumen {
    font-family: var(--font-mono);
    font-size: var(--text-2xs);
    color: var(--muted);
  }

  /* Las cifras son la `.stat` común; aquí sólo la rejilla y la unidad pequeña
     al lado del valor. */
  .cifras {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(10.5rem, 1fr));
    gap: var(--space-3) var(--space-4);
    margin: var(--space-1) 0 var(--space-4);
  }
  .stat-value small {
    font-size: var(--text-xs);
    font-weight: 500;
    color: var(--muted);
  }

  .grafica {
    margin: 0;
    min-width: 0;
  }
  figcaption {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-1) var(--space-4);
    margin-bottom: var(--space-2);
  }
  .leyenda {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
    font-size: var(--text-2xs);
    color: var(--ink-2);
  }
  .leyenda span {
    display: flex;
    align-items: center;
    gap: var(--space-1);
  }
  .leyenda i {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 2px;
  }
  .leyenda i.linea {
    height: 2px;
  }
  .leyenda i.trazos {
    height: 0;
    border-top: 2px dashed var(--muted);
  }

  svg {
    display: block;
    width: 100%;
    height: 170px;
    overflow: visible;
    touch-action: none;
  }
  .rejilla {
    stroke: var(--grid);
    stroke-width: 1;
    vector-effect: non-scaling-stroke;
  }
  /* En unidades de la gráfica, que mide 170 de alto como el SVG: 11 px. */
  .eje {
    fill: var(--muted);
    font-family: var(--font-mono);
    font-size: var(--text-2xs);
  }
  .area {
    fill: var(--s1);
    opacity: 0.13;
  }
  .paginas {
    fill: none;
    stroke: var(--s1);
    stroke-width: 2;
    vector-effect: non-scaling-stroke;
  }
  .velocidad {
    fill: none;
    stroke: var(--s2);
    stroke-width: 1.5;
    vector-effect: non-scaling-stroke;
  }
  .media {
    stroke: var(--muted);
    stroke-width: 1;
    stroke-dasharray: 4 4;
    vector-effect: non-scaling-stroke;
  }
  .cruz {
    stroke: var(--axis);
    stroke-width: 1;
    vector-effect: non-scaling-stroke;
  }
  .punto-paginas {
    fill: var(--s1);
  }
  .punto-velocidad {
    fill: var(--s2);
  }

  .detalle,
  .esperando,
  .pie {
    margin: var(--space-1) 0 0;
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .detalle b {
    color: var(--ink);
  }
  .esperando {
    padding: var(--space-5) 0;
    text-align: center;
  }

  .dos {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(17rem, 1fr));
    gap: var(--space-5) var(--space-6);
    margin-top: var(--space-4);
  }

  /* Una composición, no un avance: la pista común más gruesa, con 2 px de
     plano entre porción y porción. */
  .composicion {
    gap: 2px;
    height: 12px;
    border-radius: var(--radius-xs);
    background: var(--plane);
  }

  .lista {
    display: grid;
    gap: var(--space-1);
    margin: var(--space-2) 0 0;
    padding: 0;
    list-style: none;
    font-size: var(--text-xs);
  }
  .lista li {
    display: grid;
    grid-template-columns: 10px 1fr auto 3.6rem;
    align-items: center;
    gap: var(--space-2);
  }
  .lista i {
    width: 10px;
    height: 10px;
    border-radius: 2px;
  }
  .lista small,
  .etapas small {
    font-size: var(--text-2xs);
    color: var(--muted);
    text-align: right;
  }

  .etapas {
    display: grid;
    gap: var(--space-1);
    margin: 0;
    padding: 0;
    list-style: none;
    font-size: var(--text-xs);
  }
  .etapas li {
    display: grid;
    grid-template-columns: minmax(7rem, 11rem) 1fr auto 2.6rem;
    align-items: center;
    gap: var(--space-2);
  }
  .etapas .nombre {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--ink-2);
  }
  .etapas li.viva .nombre {
    color: var(--ink);
    font-weight: 600;
  }
  /* Un gráfico de barras (tiempo por etapa): la serie es dato; la etapa que
     corre ahora se marca con el acento. */
  .pista {
    height: 8px;
    border-radius: var(--radius-sm);
    background: var(--plane);
  }
  .pista span {
    display: block;
    height: 100%;
    border-radius: var(--radius-sm);
    background: var(--s3);
  }
  .etapas li.viva .pista span {
    background: var(--accent);
  }

  .consumo {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: var(--space-1) var(--space-4);
    margin: 0;
    font-size: var(--text-xs);
  }
  .consumo dt {
    color: var(--ink-2);
  }
  .consumo dd {
    margin: 0;
    font-weight: 600;
    text-align: right;
  }
</style>
