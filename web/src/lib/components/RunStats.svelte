<script lang="ts">
  import StatTile from '$lib/components/StatTile.svelte';
  import { formatBytes, formatDuration } from '$lib/format';
  import type { Consumo } from '$lib/types';

  /**
   * Las cifras de un trabajo en curso, sean uno o cincuenta documentos.
   *
   * Existe porque había tres. Un documento suelto medía «Almacenamiento», un
   * lote medía «Peso neto» y una carpeta no medía ninguna de las dos; el tiempo
   * se llamaba «Tiempo», «Transcurrido» o «Tardó» según dónde se mirara, y la
   * carpeta no decía ni cuántas páginas llevaba ni a qué velocidad. Eran tres
   * vocabularios para el mismo trabajo, y quien vigila una carga aprende a leer
   * uno y se pierde en el siguiente.
   *
   * Lo que se omite es lo que no existe -- una carga sin cola no enseña una cola
   * en cero -- pero lo que se enseña se llama siempre igual y va siempre en el
   * mismo sitio, que es lo que permite comparar dos cargas de un vistazo.
   */
  interface Props {
    pagesDone: number;
    pagesTotal: number;
    /** Cuántas unidades documentales han salido ya, y cómo se llaman. */
    units?: number | null;
    unitLabel?: string;
    bytesTotal?: number;
    /** Del peso de arriba, cuánto se ha leído ya. */
    bytesDone?: number;
    /** Páginas por segundo, ahora mismo. */
    rate?: number;
    elapsedSeconds?: number;
    /** Segundos que faltan, cuando se pueden estimar. */
    remainingSeconds?: number | null;
    queued?: number | null;
    failed?: number | null;
    /** El trabajo ya terminó: las medidas dejan de ser «ahora» y pasan a ser «en total». */
    settled?: boolean;
    /**
     * Lo gastado con los proveedores de pago. Se enseña en sus unidades --
     * páginas facturadas, tokens -- y en dinero sólo si hay un precio puesto.
     * Sin consumo no aparece nada: una carga leída con el motor local no
     * enseña un gasto en cero.
     */
    consumo?: Consumo | null;
  }

  let {
    pagesDone,
    pagesTotal,
    units = null,
    unitLabel = 'unidades',
    bytesTotal = 0,
    bytesDone = 0,
    rate = 0,
    elapsedSeconds = 0,
    remainingSeconds = null,
    queued = null,
    failed = null,
    settled = false,
    consumo = null
  }: Props = $props();

  /** Cuántas veces el proveedor pidió esperar o no contestó, en una frase. */
  const incidencias = $derived.by(() => {
    if (!consumo) return '';
    const partes: string[] = [];
    if (consumo.rechazos) partes.push(`${consumo.rechazos} esperas`);
    if (consumo.fallos) partes.push(`${consumo.fallos} sin respuesta`);
    return partes.join(' · ');
  });

  const costeTexto = $derived.by(() => {
    if (!consumo || consumo.coste_estimado === null || consumo.coste_estimado === undefined) return null;
    return `${consumo.coste_estimado.toFixed(2)} ${consumo.moneda}`;
  });

  const percent = $derived(pagesTotal ? Math.min(100, (100 * pagesDone) / pagesTotal) : 0);

  const timeNote = $derived.by(() => {
    if (settled) return 'en total';
    if (remainingSeconds && remainingSeconds > 0) return `faltan ~${formatDuration(remainingSeconds)}`;
    return 'calculando…';
  });

  const byteRate = $derived(elapsedSeconds > 0 && bytesDone ? bytesDone / elapsedSeconds : 0);
</script>

<div class="stats">
  <StatTile
    label={settled ? 'Tardó' : 'Tiempo'}
    value={formatDuration(elapsedSeconds)}
    note={timeNote}
  />

  <StatTile
    label="Páginas"
    value={pagesTotal ? `${pagesDone} / ${pagesTotal}` : String(pagesDone)}
    note={pagesTotal ? `${percent.toFixed(0)} % leído` : 'contando…'}
  />

  <StatTile
    label={settled ? 'Velocidad media' : 'Velocidad'}
    value={`${rate.toFixed(1)} p/s`}
    note={byteRate ? `${formatBytes(byteRate)}/s` : 'páginas por segundo'}
  />

  {#if bytesTotal}
    <StatTile
      label="Peso"
      value={formatBytes(bytesTotal)}
      note={bytesDone ? `${formatBytes(bytesDone)} leídos` : 'sin leer todavía'}
    />
  {/if}

  {#if units !== null}
    <StatTile
      label="Producido"
      value={units}
      note={unitLabel}
      tone={units > 0 ? 'good' : 'neutral'}
    />
  {/if}

  {#if queued}
    <StatTile label="En cola" value={queued} note="sin empezar" />
  {/if}

  {#if failed}
    <StatTile label="Con error" value={failed} note="no se pudieron procesar" tone="warning" />
  {/if}

  {#if consumo && consumo.paginas_facturadas}
    <StatTile
      label="Páginas facturadas"
      value={consumo.paginas_facturadas}
      note={`OCR de pago · ${consumo.peticiones} peticiones`}
    />
  {/if}

  {#if consumo && consumo.tokens}
    <StatTile
      label="Tokens"
      value={consumo.tokens.toLocaleString('es-CO')}
      note={`${consumo.tokens_entrada.toLocaleString('es-CO')} entrada · ${consumo.tokens_salida.toLocaleString('es-CO')} salida`}
    />
  {/if}

  {#if costeTexto}
    <StatTile label={settled ? 'Costó' : 'Coste estimado'} value={costeTexto} note="según el precio configurado" />
  {/if}

  {#if incidencias}
    <StatTile label="Proveedor" value={incidencias} note="reintentos y pérdidas" tone="warning" />
  {/if}
</div>

<style>
  /* Una sola rejilla para todas las cargas: las tejas caen en el mismo sitio
     tenga el trabajo cuatro cifras o siete, así que la vista no se recoloca al
     pasar de un documento suelto a un lote. */
  .stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(8.5rem, 1fr));
    gap: 0.9rem 1.5rem;
  }
</style>
