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

export const UNREADABLE: Rung = {
  key: 'none',
  mark: 'x',
  label: 'Ilegible',
  hint: 'la página no pudo leerse y quedó para revisión',
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
  done: 'Listo',
  failed: 'Falló'
};

export const STAGE_LABELS: Record<string, string> = {
  queued: 'En cola',
  analysing: 'Leyendo páginas',
  grouping: 'Agrupando por resolución',
  assembling: 'Escribiendo los PDF',
  done: 'Listo',
  failed: 'Falló'
};
