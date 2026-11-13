<script lang="ts">
  /**
   * La auditoría de cierre de una corrida de carpeta (lo pidió el operador el
   * 2026-11-05: «así como vigila durante el procesamiento, que también lo haga
   * al finalizar», que lo de la fuente esté en el destino y que revise 100 PDF
   * al azar, «todo manejando un margen de errores»).
   *
   * Mientras se hace, la fase y su avance. Al terminar: cómo terminó la corrida;
   * el cuadre, origen contra destino, con «=» o «≠» en cada cuenta; la muestra,
   * un cuadro por PDF revisado; el error de la corrida en una escala con su
   * intervalo y la raya del margen aceptable; y lo que hay que mirar, con su
   * evidencia. Todo sale de `run.comparacion` y `run.auditoria`.
   *
   * Desde el 2026-11-09 la muestra puede ser de filas del inventario (una
   * corrida de «Solo inventario» no entrega PDF cortados): se dice «filas», se
   * dice qué hizo la IA con lo dudoso y cuánto costó, y una muestra vacía se
   * explica en palabras en vez de dibujar una reja vacía y un «< 0 %».
   */
  import Icono from '$lib/components/Icono.svelte';
  import {
    DICTAMENES,
    ESTADOS_DE_LA_MUESTRA,
    esDeFilas,
    faseEnCurso,
    filasDelCuadre,
    habilidadesDeLaMuestra,
    iaDeLaMuestra,
    muestraVacia,
    paraMirar,
    porCiento,
    rotuloDeLaMuestra,
    textoSinMuestra,
    tonoDeLaEtapa,
    topeDeLaEscala,
    topeDelMargen
  } from '$lib/auditoria';
  import type { AuditoriaDeCierre, ComparacionDeLaEntrega, HallazgoDelCuadre } from '$lib/types';

  interface Props {
    auditoria: AuditoriaDeCierre;
    comparacion?: ComparacionDeLaEntrega | null;
    etapa?: string | null;
    detalle?: string;
  }

  let { auditoria, comparacion = null, etapa = null, detalle = '' }: Props = $props();

  const muestra = $derived(auditoria.muestra ?? null);
  const vacia = $derived(muestra ? muestraVacia(muestra) : false);
  const deFilas = $derived(esDeFilas(muestra));
  const ia = $derived(muestra ? iaDeLaMuestra(muestra) : null);
  const filas = $derived(comparacion ? filasDelCuadre(comparacion) : []);
  // Sin nada revisado no hay error que medir: ni escala ni dictamen.
  const margen = $derived(muestra && !vacia ? muestra.margen : null);
  const dictamen = $derived(margen ? DICTAMENES[margen.dictamen] : null);
  const tope = $derived(muestra ? topeDeLaEscala(muestra) : 0.1);
  const mirar = $derived(muestra ? paraMirar(muestra) : []);
  const habilidades = $derived(muestra && !vacia ? habilidadesDeLaMuestra(muestra) : []);
  const avance = $derived(
    auditoria.total ? Math.min(100, Math.round(((auditoria.hechos ?? 0) / auditoria.total) * 100)) : 0
  );

  /** Lo que no cuadra del cuadre, agrupado, para la lista de hallazgos. */
  const hallazgos = $derived.by((): { titulo: string; tono: string; items: HallazgoDelCuadre[] }[] => {
    if (!comparacion) return [];
    return [
      { titulo: 'Faltan en el destino', tono: 'bad', items: comparacion.faltan },
      {
        titulo: 'Índices que no cuadran',
        tono: 'bad',
        items: comparacion.registros_que_no_cuadran.map((r): HallazgoDelCuadre => ({ carpeta: r.pdf, motivo: r.motivo }))
      },
      { titulo: 'Carpetas del origen sin PDF', tono: 'warn', items: comparacion.sin_pdf },
      { titulo: 'Archivos sueltos en la raíz', tono: 'warn', items: comparacion.archivos_en_la_raiz },
      { titulo: 'De más en el destino', tono: 'warn', items: comparacion.sobran },
      {
        titulo: 'PDF con 2 o más sellos',
        tono: 'warn',
        items: (comparacion.varios_sellos ?? []).map(
          (v): HallazgoDelCuadre => ({ carpeta: `${v.pdf} → ${v.archivo}`, motivo: v.estado, evidencia: v.sellos })
        )
      }
    ].filter((grupo) => grupo.items.length);
  });

  /** Dónde cae un valor en la escala del error, en por ciento del ancho. */
  function en(valor: number, escala: number = tope): number {
    return Math.min(100, Math.max(0, (valor / escala) * 100));
  }
</script>

<section class="auditoria" data-tono={auditoria.estado === 'auditando' ? 'accent' : tonoDeLaEtapa(etapa)}>
  <header class="cabeza">
    <span class="marca" aria-hidden="true"><Icono nombre="escudo" /></span>
    <div class="min-w-0">
      <span class="caps">Auditoría de cierre</span>
      <p class="titulo">
        {#if auditoria.estado === 'auditando'}
          {faseEnCurso(auditoria)}
          <span class="status-dot live" aria-hidden="true"></span>
        {:else if auditoria.estado === 'no se pudo'}
          No se pudo hacer: {auditoria.error}
        {:else}
          {etapa ?? 'Terminada'}
        {/if}
      </p>
      {#if auditoria.estado === 'hecha' && detalle}
        <p class="detalle">{detalle}</p>
      {/if}
    </div>
  </header>

  {#if auditoria.estado === 'auditando'}
    <div
      class="progress mt-3"
      role="progressbar"
      aria-valuenow={avance}
      aria-valuemin="0"
      aria-valuemax="100"
    >
      <div class="progress-fill" style:width={`${avance}%`}></div>
    </div>
    {#if auditoria.ultimo}
      <p class="ultimo">
        <span class="pdf">{auditoria.ultimo.pdf}</span>
        <span class="pill pill-sm etiqueta" data-tono={ESTADOS_DE_LA_MUESTRA[auditoria.ultimo.estado].tono}>
          {ESTADOS_DE_LA_MUESTRA[auditoria.ultimo.estado].etiqueta}
        </span>
      </p>
    {/if}
  {/if}

  {#if filas.length}
    <div class="caps rotulo">Origen y destino</div>
    <ul class="cuadre">
      {#each filas as fila (fila.etiqueta)}
        <li class="fila" data-cuadra={fila.cuadra ? 'si' : 'no'}>
          <span class="lado">
            <strong class="tabular">{fila.origen.toLocaleString('es-CO')}</strong>
            <span>{fila.etiqueta} {fila.dichoOrigen}</span>
          </span>
          <span class="signo" title={fila.cuadra ? 'Cuadra' : 'No cuadra'}>
            {fila.cuadra ? '=' : '≠'}
          </span>
          <span class="lado derecha">
            <strong class="tabular">{fila.destino.toLocaleString('es-CO')}</strong>
            <span>{fila.dichoDestino}</span>
          </span>
        </li>
      {/each}
    </ul>
  {/if}

  {#if muestra && vacia}
    <div class="caps rotulo">Muestra al azar</div>
    <p class="sin-muestra">{textoSinMuestra(muestra)}.</p>
  {:else if muestra}
    <div class="caps rotulo">{rotuloDeLaMuestra(muestra)}</div>
    <div class="muestra">
      <div
        class="reja"
        role="list"
        aria-label={deFilas ? 'Las filas de la muestra y cómo salió cada una' : 'Los PDF de la muestra y cómo salió cada uno'}
      >
        {#each muestra.pdfs as pdf, i (pdf.pdf)}
          <span
            class="cuadro"
            role="listitem"
            data-tono={ESTADOS_DE_LA_MUESTRA[pdf.estado].tono}
            style:--i={Math.min(i, 120)}
            title={`${pdf.pdf}: ${ESTADOS_DE_LA_MUESTRA[pdf.estado].etiqueta}${pdf.hallazgos.length ? ' · ' + pdf.hallazgos.join(' · ') : ''}`}
          ></span>
        {/each}
      </div>
      <ul class="leyenda">
        {#each Object.entries(ESTADOS_DE_LA_MUESTRA) as [clave, estado] (clave)}
          {@const cuantos = muestra.pdfs.filter((pdf) => pdf.estado === clave).length}
          {#if cuantos}
            <li><span class="muestra-color" data-tono={estado.tono}></span>{estado.etiqueta} <b class="tabular">{cuantos}</b></li>
          {/if}
        {/each}
      </ul>
      {#if ia}
        <!-- En filas no hay costuras: lo que se dice es qué hizo la IA con los datos dudosos. -->
        <p class="ia" data-con-ia={muestra.con_ia ? 'si' : 'no'}>{ia}</p>
      {/if}
    </div>

    {#if margen && dictamen}
      <div class="margen" data-tono={dictamen.tono}>
        <div class="margen-cabeza">
          <span class="caps">Margen de error de la corrida</span>
          <span class="pill pill-sm etiqueta" data-tono={dictamen.tono}>{dictamen.etiqueta}</span>
        </div>
        <p class="margen-cifra">
          {#if margen.errores}
            <strong class="tabular">{porCiento(margen.tasa)}</strong> medido · entre {porCiento(margen.desde)} y {porCiento(
              margen.hasta
            )}
          {:else}
            <strong class="tabular">&lt; {porCiento(margen.hasta)}</strong> de error, con {Math.round(margen.confianza * 100)} % de
            confianza
          {/if}
        </p>
        <!-- La escala: el intervalo del error de la corrida y la raya del margen aceptable. -->
        <div class="escala" aria-hidden="true">
          <span class="banda" style:left={`${en(margen.desde)}%`} style:width={`${Math.max(en(margen.hasta) - en(margen.desde), 1)}%`}></span>
          {#if margen.errores}
            <span class="punto" style:left={`${en(margen.tasa)}%`}></span>
          {/if}
          <span class="raya" style:left={`${en(margen.aceptable)}%`}>
            <span class="raya-rotulo">aceptable {porCiento(margen.aceptable)}</span>
          </span>
        </div>
        <div class="eje" aria-hidden="true"><span>0 %</span><span>{porCiento(tope)}</span></div>
        <p class="dictamen">{margen.texto_del_dictamen}. {margen.texto}.</p>
      </div>
    {/if}

    {#if habilidades.length}
      <!-- Cada habilidad contra el margen de su perfil: el error de una no se diluye en los aciertos de otra. -->
      <div class="caps rotulo">Por habilidad, cada una contra su margen</div>
      <ul class="habilidades">
        {#each habilidades as h (h.clave)}
          {@const suyo = DICTAMENES[h.margen.dictamen]}
          {@const escala = topeDelMargen(h.margen)}
          <li class="habilidad" data-tono={suyo.tono}>
            <div class="habilidad-cabeza">
              <span class="nombre">{h.habilidad}</span>
              <span class="pill pill-sm etiqueta" data-tono={suyo.tono}>{suyo.etiqueta}</span>
            </div>
            <p class="habilidad-cifras">
              <b class="tabular">{h.bien}</b> de {h.revisados} bien{#if h.errores}
                · <b class="tabular">{h.errores}</b> con error{/if} ·
              {h.margen.errores ? `${porCiento(h.margen.tasa)} medido` : `menos del ${porCiento(h.margen.hasta)}`} · aceptable
              {porCiento(h.margen.aceptable)}
            </p>
            <div class="escala mini" aria-hidden="true">
              <span
                class="banda"
                style:left={`${en(h.margen.desde, escala)}%`}
                style:width={`${Math.max(en(h.margen.hasta, escala) - en(h.margen.desde, escala), 1)}%`}
              ></span>
              <span class="raya" style:left={`${en(h.margen.aceptable, escala)}%`}></span>
            </div>
          </li>
        {/each}
      </ul>
    {/if}

    {#if mirar.length}
      <ol class="lista">
        {#each mirar as pdf (pdf.pdf)}
          <li class="item" data-tono={ESTADOS_DE_LA_MUESTRA[pdf.estado].tono}>
            <span class="icono-fila" aria-hidden="true"><Icono nombre="aviso" /></span>
            <div class="min-w-0">
              <p class="que">
                <span class="pdf">{pdf.pdf}</span>
                <span class="pill pill-sm etiqueta" data-tono={ESTADOS_DE_LA_MUESTRA[pdf.estado].tono}>
                  {ESTADOS_DE_LA_MUESTRA[pdf.estado].etiqueta}
                </span>
              </p>
              {#each pdf.hallazgos as hallazgo, j (j)}
                <p class="porque">{hallazgo}</p>
              {/each}
            </div>
          </li>
        {/each}
      </ol>
    {/if}
    <p class="semilla">Muestra al azar con la semilla {muestra.semilla}: se puede repetir igual.</p>
  {/if}

  {#if hallazgos.length}
    {#each hallazgos as grupo (grupo.titulo)}
      <details class="grupo" data-tono={grupo.tono}>
        <summary>
          <span class="status-dot" aria-hidden="true"></span>
          {grupo.titulo} <b class="tabular">{grupo.items.length}</b>
        </summary>
        <ul>
          {#each grupo.items.slice(0, 50) as item, k (k)}
            <li>
              <span class="pdf">{item.carpeta}</span>
              {#if item.motivo}· {item.motivo}{/if}
              {#if item.evidencia}<span class="evidencia">({item.evidencia})</span>{/if}
            </li>
          {/each}
          {#if grupo.items.length > 50}
            <li class="evidencia">… y {grupo.items.length - 50} más, en «00.ANALISIS DE LA ENTREGA.xlsx».</li>
          {/if}
        </ul>
      </details>
    {/each}
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
  [data-tono='neutral'] {
    --tono: var(--axis);
  }

  .auditoria {
    margin: var(--space-4) 0;
    padding: var(--space-4);
    border: 1px solid color-mix(in srgb, var(--tono) 30%, var(--hairline));
    border-top: 3px solid var(--tono);
    border-radius: var(--radius-lg);
    background:
      radial-gradient(90% 120% at 0% 0%, color-mix(in srgb, var(--tono) 6%, transparent), transparent 60%),
      var(--surface-1);
  }
  .cabeza {
    display: flex;
    align-items: flex-start;
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
    background: color-mix(in srgb, var(--tono) 14%, var(--surface-2));
    color: var(--tono);
  }
  .titulo {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    margin: 0;
    font-size: var(--text-md);
    font-weight: 600;
    color: var(--ink);
  }
  .detalle {
    margin: 2px 0 0;
    font-size: var(--text-sm);
    color: var(--ink-2);
  }
  .ultimo {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    margin: var(--space-2) 0 0;
    font-size: var(--text-sm);
  }
  .pdf {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--ink);
    overflow-wrap: anywhere;
  }
  .etiqueta {
    background: color-mix(in srgb, var(--tono) 14%, transparent);
    color: color-mix(in srgb, var(--tono) 75%, var(--ink));
  }
  .rotulo {
    margin: var(--space-5) 0 var(--space-2);
  }

  /* El cuadre: origen a la izquierda, destino a la derecha, «=» o «≠» en medio. */
  .cuadre {
    display: grid;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .fila {
    --tono: var(--good);
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: color-mix(in srgb, var(--tono) 6%, var(--surface-2));
    animation: entrada var(--duration-slow) var(--ease-out) both;
  }
  .fila[data-cuadra='no'] {
    --tono: var(--critical);
  }
  .lado {
    display: flex;
    flex-direction: column;
    min-width: 0;
    font-size: var(--text-xs);
    color: var(--ink-2);
  }
  .lado strong {
    font-size: var(--text-xl);
    line-height: 1.1;
    color: var(--ink);
  }
  .derecha {
    text-align: right;
  }
  .signo {
    display: grid;
    width: 32px;
    height: 32px;
    place-items: center;
    border-radius: 50%;
    background: color-mix(in srgb, var(--tono) 16%, transparent);
    font-size: var(--text-lg);
    font-weight: 700;
    color: var(--tono);
  }

  /* La muestra: un cuadro por PDF revisado. */
  .reja {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(14px, 1fr));
    gap: 4px;
    max-width: 420px;
  }
  .cuadro {
    aspect-ratio: 1;
    border-radius: 3px;
    background: var(--tono);
    animation: entrada var(--duration-slow) var(--ease-out) both;
    animation-delay: calc(var(--i) * 8ms);
    cursor: default;
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
  .muestra-color {
    width: 10px;
    height: 10px;
    border-radius: 3px;
    background: var(--tono);
  }

  /* El margen de error: el intervalo en una escala, y la raya de lo aceptable. */
  .margen {
    margin-top: var(--space-4);
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius-md);
    border: 1px solid color-mix(in srgb, var(--tono) 30%, var(--hairline));
    background: var(--surface-2);
  }
  .margen-cabeza {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }
  .margen-cifra {
    margin: var(--space-2) 0 var(--space-3);
    font-size: var(--text-sm);
    color: var(--ink-2);
  }
  .margen-cifra strong {
    font-size: var(--text-stat);
    letter-spacing: -0.02em;
    color: var(--tono);
  }
  .escala {
    position: relative;
    height: 12px;
    margin-top: var(--space-5);
    border-radius: var(--radius-pill);
    background: var(--grid);
  }
  .banda {
    position: absolute;
    top: 0;
    bottom: 0;
    border-radius: var(--radius-pill);
    background: color-mix(in srgb, var(--tono) 55%, transparent);
    transition:
      left var(--duration-slow) var(--ease-out),
      width var(--duration-slow) var(--ease-out);
  }
  .punto {
    position: absolute;
    top: 50%;
    width: 12px;
    height: 12px;
    border: 2px solid var(--surface-2);
    border-radius: 50%;
    background: var(--tono);
    transform: translate(-50%, -50%);
  }
  .raya {
    position: absolute;
    top: -6px;
    bottom: -6px;
    width: 2px;
    background: var(--ink);
  }
  .raya-rotulo {
    position: absolute;
    bottom: calc(100% + 2px);
    left: 50%;
    transform: translateX(-50%);
    font-size: var(--text-2xs);
    white-space: nowrap;
    color: var(--ink-2);
  }
  .eje {
    display: flex;
    justify-content: space-between;
    margin-top: 4px;
    font-size: var(--text-2xs);
    color: var(--muted);
  }
  .dictamen {
    margin: var(--space-2) 0 0;
    font-size: var(--text-sm);
    line-height: 1.45;
    color: var(--ink-2);
  }

  /* Cada habilidad de la muestra, con su escala corta y la raya de su aceptable. */
  .habilidades {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 15rem), 1fr));
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .habilidad {
    padding: var(--space-2) var(--space-3);
    border: 1px solid color-mix(in srgb, var(--tono) 25%, var(--hairline));
    border-radius: var(--radius-md);
    background: var(--surface-2);
    animation: entrada var(--duration-slow) var(--ease-out) both;
  }
  .habilidad-cabeza {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }
  .nombre {
    min-width: 0;
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--ink);
  }
  .habilidad-cifras {
    margin: 4px 0 0;
    font-size: var(--text-xs);
    color: var(--ink-2);
  }
  .escala.mini {
    height: 6px;
    margin-top: var(--space-2);
  }

  .lista {
    display: grid;
    gap: var(--space-2);
    margin: var(--space-4) 0 0;
    padding: 0;
    list-style: none;
  }
  .item {
    display: flex;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-3);
    border-left: 2px solid var(--tono);
    border-radius: 0 var(--radius) var(--radius) 0;
    background: color-mix(in srgb, var(--tono) 6%, var(--surface-2));
  }
  .icono-fila {
    color: var(--tono);
  }
  .que {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    margin: 0;
  }
  .porque {
    margin: 2px 0 0;
    font-size: var(--text-sm);
    color: var(--ink-2);
    overflow-wrap: anywhere;
  }
  .ia {
    margin: var(--space-2) 0 0;
    font-size: var(--text-sm);
    color: var(--ink-2);
  }
  .ia[data-con-ia='no'] {
    color: var(--muted);
  }
  .sin-muestra {
    margin: 0;
    font-size: var(--text-sm);
    color: var(--ink-2);
  }
  .semilla {
    margin: var(--space-3) 0 0;
    font-size: var(--text-xs);
    color: var(--muted);
  }

  .grupo {
    margin-top: var(--space-2);
    font-size: var(--text-sm);
  }
  .grupo summary {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    cursor: pointer;
    color: var(--ink);
  }
  .grupo .status-dot {
    background: var(--tono);
  }
  .grupo ul {
    margin: var(--space-2) 0 0;
    padding-left: var(--space-6);
    color: var(--ink-2);
  }
  .evidencia {
    color: var(--muted);
  }
</style>
