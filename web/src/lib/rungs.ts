/**
 * The four rungs of the cascade, in the order they run, mapped to the first four
 * slots of the validated categorical palette. Fixed order, never cycled.
 *
 * "Unreadable" is deliberately not a fifth series: it is a status, and it always
 * ships with its own label so the meaning never rests on colour alone.
 */
export interface Rung {
  key: string;
  mark: string;
  label: string;
  hint: string;
  color: string;
}

export const RUNGS: Rung[] = [
  {
    key: 'text_layer',
    mark: 't',
    label: 'Capa de texto',
    hint: 'leído del texto incrustado, sin OCR',
    color: 'var(--s1)'
  },
  {
    key: 'ocr_region',
    mark: 'h',
    label: 'OCR de encabezado',
    hint: 'OCR sobre la banda superior únicamente',
    color: 'var(--s2)'
  },
  {
    key: 'ocr_full_page',
    mark: 'f',
    label: 'OCR de página completa',
    hint: 'la banda superior no devolvió nada',
    color: 'var(--s3)'
  },
  {
    key: 'vision_model',
    mark: 'v',
    label: 'Modelo de visión',
    hint: 'escalado al modelo',
    color: 'var(--s4)'
  }
];

/**
 * La marca de "mírame".
 *
 * Se llamaba "Ilegible", y casi nunca lo es: en un libro de folios la mayoría
 * de estas páginas se leyeron enteras y lo que falla es que el contenido no se
 * sostiene -- el folio del encabezado contra el del pie, un nombre que el
 * escaneo dejó con un dígito dentro. Llamarlas ilegibles mandaba a buscar un
 * problema de imagen donde hay un problema de dato.
 */
export const UNREADABLE: Rung = {
  key: 'none',
  mark: 'x',
  label: 'Requiere revisión',
  hint: 'la página quedó marcada para que alguien la mire',
  color: 'var(--critical)'
};

export const PENDING_COLOR = 'var(--grid)';

const BY_MARK = new Map([...RUNGS, UNREADABLE].map((rung) => [rung.mark, rung]));

export function rungForMark(mark: string): Rung | null {
  return BY_MARK.get(mark) ?? null;
}

export function colorForMark(mark: string): string {
  return rungForMark(mark)?.color ?? PENDING_COLOR;
}

export const STATE_LABELS: Record<string, string> = {
  queued: 'En cola',
  running: 'Procesando',
  paused: 'En pausa',
  done: 'Listo',
  failed: 'Falló',
  cancelled: 'Cancelado'
};

export const STAGE_LABELS: Record<string, string> = {
  queued: 'En cola',
  paused: 'En pausa, esperando reanudar',
  cancelled: 'Cancelado por el operador',
  analysing: 'Leyendo páginas',
  identifying: 'Reconociendo el documento',
  verifying: 'Contrastando lo leído',
  grouping: 'Agrupando por resolución',
  assembling: 'Escribiendo los PDF',
  inventorying: 'Escribiendo el inventario',
  delivering: 'Guardando el resultado',
  done: 'Listo',
  failed: 'Falló'
};

/**
 * Etapas que llevan su propio contador.
 *
 * Todas tardan lo bastante como para que enseñar sólo su nombre parezca un
 * cuelgue. La pantalla las trata distinto: además de la etiqueta, muestran por
 * dónde van y cuánto llevan en ello.
 */
export const COUNTED_STAGES = new Set([
  'analysing',
  'identifying',
  'verifying',
  'grouping',
  'assembling',
  'inventorying',
  'delivering'
]);

/**
 * Segundos de silencio a partir de los cuales se dice desde cuándo.
 *
 * Por debajo de esto un hueco es el ritmo normal del trabajo y anunciarlo sería
 * ruido. Por encima, callarse es lo que hace que la pantalla parezca colgada.
 */
export const SILENCE_THRESHOLD_SECONDS = 4;

/**
 * Qué está haciendo el trabajo ahora mismo, en una línea.
 *
 * Vive aquí y no en cada pantalla porque las dos que lo enseñan -- la tarjeta
 * del lote y el monitor de un documento -- tienen que decir lo mismo, y cuando
 * cada una lo componía por su cuenta sólo una de ellas acabó enseñando el
 * detalle: el monitor decía "Reconociendo el documento" durante doce minutos de
 * lectura, sin un número, mientras el trabajo iba por la página trescientas.
 *
 * El nombre de la etapa no basta: "Escribiendo los PDF" dice exactamente lo
 * mismo en el archivo 1 que en el 287. Por eso lleva detrás el contador de la
 * etapa y lo que el worker haya querido contar de ella.
 */
export function stageActivity(progress: {
  stage: string;
  pages_done?: number;
  page_count?: number;
  pages_per_second?: number;
  stage_done?: number;
  stage_total?: number;
  detail?: string | null;
}): string {
  const label = STAGE_LABELS[progress.stage] ?? progress.stage;
  if (progress.stage === 'analysing' || progress.stage === 'page') {
    const rate = progress.pages_per_second
      ? ` · ${progress.pages_per_second.toFixed(1)} p/s`
      : '';
    return `${label} · ${progress.pages_done ?? 0} de ${progress.page_count ?? 0} páginas${rate}`;
  }
  const done = progress.stage_done ?? 0;
  const total = progress.stage_total ?? 0;
  const counter = total ? ` · ${done} de ${total}` : '';
  const detail = progress.detail ? ` · ${progress.detail}` : '';
  return `${label}${counter}${detail}`;
}
