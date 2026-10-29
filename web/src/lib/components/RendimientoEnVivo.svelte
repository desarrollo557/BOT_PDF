<script lang="ts">
  import { fetchRendimiento, type Rendimiento } from '$lib/api';
  import { formatBytes } from '$lib/format';

  /**
   * El rendimiento del equipo y del bot, en vivo, debajo de la cola.
   *
   * Lo pidió el operador el 2026-10-29 «para tener todo muy bien controlado»:
   * ese día el otro equipo se ahogó con diez PDF de 200 MB a la vez y sólo se
   * supo por los registros. Se pregunta cada `CADA` ms mientras hay trabajo, y
   * se guardan los últimos minutos para dibujar la tendencia.
   *
   * Si el servicio es anterior a la medición (contesta 404), el panel no se
   * enseña: no hay nada que decir con «—» en todas las casillas.
   */

  const CADA = 2000;
  /** Cuántas muestras se dibujan: tres minutos a una cada dos segundos. */
  const MUESTRAS = 90;
  /** Desde cuánto CPU se avisa de que el equipo no da abasto. */
  const SATURADO = 90;

  let actual = $state<Rendimiento | null>(null);
  let disponible = $state(true);
  let cpu = $state<number[]>([]);
  let paginas = $state<number[]>([]);

  function sumar(serie: number[], valor: number | null): number[] {
    if (valor === null) return serie;
    return [...serie, valor].slice(-MUESTRAS);
  }

  $effect(() => {
    let vivo = true;
    let fallos = 0;
    async function medir() {
      const datos = await fetchRendimiento();
      if (!vivo) return;
      if (datos === null) {
        // Dos fallos seguidos: o es un servicio sin medición, o está caído; de
        // lo segundo ya avisa la barra de estado.
        fallos += 1;
        if (fallos >= 2 && actual === null) disponible = false;
        return;
      }
      fallos = 0;
      disponible = true;
      actual = datos;
      cpu = sumar(cpu, datos.equipo.cpu);
      paginas = sumar(paginas, datos.bot.paginas_por_minuto);
    }
    medir();
    const reloj = setInterval(medir, CADA);
    return () => {
      vivo = false;
      clearInterval(reloj);
    };
  });

  const memoria = $derived(
    actual?.equipo.memoria_total && actual.equipo.memoria_usada !== null
      ? (100 * actual.equipo.memoria_usada) / actual.equipo.memoria_total
      : null
  );
  const saturado = $derived(
    (actual?.equipo.cpu ?? 0) >= SATURADO || (memoria ?? 0) >= SATURADO
  );

  function cifra(valor: number | null | undefined, decimales = 0): string {
    if (valor === null || valor === undefined) return '—';
    return valor.toLocaleString('es-CO', { maximumFractionDigits: decimales });
  }

  /** La tendencia de una serie como puntos de un `polyline` en una caja de 100 × 30. */
  function trazo(serie: number[], tope: number): string {
    if (serie.length < 2) return '';
    const maximo = Math.max(tope, ...serie) || 1;
    return serie
      .map((valor, i) => {
        const x = (100 * i) / (MUESTRAS - 1) + (100 * (MUESTRAS - serie.length)) / (MUESTRAS - 1);
        const y = 29 - (27 * valor) / maximo;
        return `${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(' ');
  }

  /** Qué muestra el puntero sobre una tendencia: índice en la serie, o nada. */
  let señalada = $state<{ serie: 'cpu' | 'paginas'; indice: number } | null>(null);

  function señalar(evento: PointerEvent, serie: 'cpu' | 'paginas', datos: number[]) {
    const caja = (evento.currentTarget as SVGElement).getBoundingClientRect();
    const fraccion = (evento.clientX - caja.left) / caja.width;
    const desde = MUESTRAS - datos.length;
    const indice = Math.round(fraccion * (MUESTRAS - 1)) - desde;
    señalada = indice >= 0 && indice < datos.length ? { serie, indice } : null;
  }

  function segundosAtras(serie: number[], indice: number): string {
    const s = ((serie.length - 1 - indice) * CADA) / 1000;
    return s === 0 ? 'ahora' : `hace ${s} s`;
  }
</script>

{#if disponible}
  <section class="rendimiento panel" aria-label="Rendimiento en vivo">
    <header>
      <h2>Rendimiento en vivo</h2>
      <span class="vivo" class:apagado={actual === null} title="Se actualiza cada 2 segundos">
        <span class="punto"></span>{actual === null ? 'midiendo…' : 'en vivo'}
      </span>
    </header>

    {#if saturado}
      <p class="aviso" role="status">
        <span class="pill pill-warn">⚠ Equipo saturado</span>
        Va más lento de lo que podría: baje «Archivos en paralelo» en la corrida.
      </p>
    {/if}

    <h3 class="caps">Equipo</h3>
    <div class="fichas">
      <div class="ficha ancha">
        <span class="rotulo">CPU</span>
        <span class="valor tabular">{cifra(actual?.equipo.cpu)}<small>%</small></span>
        <svg
          class="tendencia"
          viewBox="0 0 100 30"
          preserveAspectRatio="none"
          role="img"
          aria-label={`Uso de CPU de los últimos minutos; ahora ${cifra(actual?.equipo.cpu)} %`}
          onpointermove={(e) => señalar(e, 'cpu', cpu)}
          onpointerleave={() => (señalada = null)}
        >
          <line class="base" x1="0" y1="29" x2="100" y2="29" />
          <polyline points={trazo(cpu, 100)} />
          {#if señalada?.serie === 'cpu'}
            {@const x = (100 * (MUESTRAS - cpu.length + señalada.indice)) / (MUESTRAS - 1)}
            <line class="cursor" x1={x} y1="0" x2={x} y2="30" />
          {/if}
        </svg>
        {#if señalada?.serie === 'cpu'}
          <span class="dato tabular">
            {cifra(cpu[señalada.indice])} % · {segundosAtras(cpu, señalada.indice)}
          </span>
        {/if}
      </div>
      <div class="ficha">
        <span class="rotulo">Memoria</span>
        <span class="valor tabular">{cifra(memoria)}<small>%</small></span>
        <span class="progress progress-sm"
          ><span class="progress-fill" style:width={`${memoria ?? 0}%`}></span></span
        >
        <span class="pie tabular">
          {actual?.equipo.memoria_usada != null ? formatBytes(actual.equipo.memoria_usada) : '—'} de
          {actual?.equipo.memoria_total != null ? formatBytes(actual.equipo.memoria_total) : '—'}
        </span>
      </div>
      <div class="ficha">
        <span class="rotulo">Carga</span>
        <span class="valor tabular">{cifra(actual?.equipo.carga, 1)}</span>
        <span class="pie tabular">{cifra(actual?.equipo.nucleos)} núcleos</span>
      </div>
    </div>

    <h3 class="caps">Bot</h3>
    <div class="fichas">
      <div class="ficha ancha">
        <span class="rotulo">Páginas por minuto</span>
        <span class="valor tabular">{cifra(actual?.bot.paginas_por_minuto)}</span>
        <svg
          class="tendencia"
          viewBox="0 0 100 30"
          preserveAspectRatio="none"
          role="img"
          aria-label={`Páginas leídas por minuto en los últimos minutos; ahora ${cifra(actual?.bot.paginas_por_minuto)}`}
          onpointermove={(e) => señalar(e, 'paginas', paginas)}
          onpointerleave={() => (señalada = null)}
        >
          <line class="base" x1="0" y1="29" x2="100" y2="29" />
          <polyline points={trazo(paginas, 10)} />
          {#if señalada?.serie === 'paginas'}
            {@const x = (100 * (MUESTRAS - paginas.length + señalada.indice)) / (MUESTRAS - 1)}
            <line class="cursor" x1={x} y1="0" x2={x} y2="30" />
          {/if}
        </svg>
        {#if señalada?.serie === 'paginas'}
          <span class="dato tabular">
            {cifra(paginas[señalada.indice])} pág./min · {segundosAtras(paginas, señalada.indice)}
          </span>
        {/if}
      </div>
      <div class="ficha">
        <span class="rotulo">Documentos por minuto</span>
        <span class="valor tabular">{cifra(actual?.bot.documentos_por_minuto, 1)}</span>
      </div>
      <div class="ficha">
        <span class="rotulo">Leyendo / en cola</span>
        <span class="valor tabular"
          >{cifra(actual?.bot.documentos_en_curso)}<small> / {cifra(actual?.bot.en_cola)}</small></span
        >
      </div>
      <div class="ficha">
        <span class="rotulo">Memoria del bot</span>
        <span class="valor tabular small"
          >{actual?.bot.memoria != null ? formatBytes(actual.bot.memoria) : '—'}</span
        >
      </div>
      <div class="ficha">
        <span class="rotulo">Procesos de lectura</span>
        <span class="valor tabular">{cifra(actual?.bot.procesos)}</span>
      </div>
    </div>
  </section>
{/if}

<style>
  .rendimiento {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }
  h2 {
    margin: 0;
    font-size: var(--text-lg);
    font-weight: 650;
    letter-spacing: -0.015em;
  }
  h3 {
    margin: var(--space-1) 0 0;
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .vivo {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .punto {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--good);
    animation: latido 2s var(--ease-in-out) infinite;
  }
  .apagado .punto {
    background: var(--muted);
    animation: none;
  }
  @keyframes latido {
    50% {
      opacity: 0.35;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .punto {
      animation: none;
    }
  }

  .aviso {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-2);
    margin: 0;
    font-size: var(--text-xs);
    line-height: 1.45;
    color: var(--ink-2);
  }

  .fichas {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-1);
  }
  .ficha {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    border: 1px solid var(--rule);
    border-radius: var(--radius);
    background: var(--surface-1);
    padding: var(--space-2) var(--space-3);
  }
  .ancha {
    grid-column: 1 / -1;
  }
  .rotulo {
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .valor {
    font-size: var(--text-xl);
    font-weight: 650;
    line-height: 1.1;
    color: var(--ink);
  }
  .valor.small {
    font-size: var(--text-md);
  }
  .valor small {
    margin-left: 1px;
    font-size: var(--text-sm);
    font-weight: 500;
    color: var(--muted);
  }
  .pie {
    font-size: var(--text-xs);
    color: var(--muted);
  }

  .tendencia {
    width: 100%;
    height: 2.25rem;
    margin-top: 2px;
    overflow: visible;
    cursor: crosshair;
  }
  .tendencia polyline {
    fill: none;
    stroke: var(--s1);
    stroke-width: 2;
    stroke-linejoin: round;
    stroke-linecap: round;
    vector-effect: non-scaling-stroke;
  }
  .tendencia .base {
    stroke: var(--grid);
    stroke-width: 1;
    vector-effect: non-scaling-stroke;
  }
  .tendencia .cursor {
    stroke: var(--axis);
    stroke-width: 1;
    vector-effect: non-scaling-stroke;
  }
  .dato {
    position: absolute;
    top: var(--space-2);
    right: var(--space-3);
    font-size: var(--text-xs);
    color: var(--ink-2);
  }
</style>
