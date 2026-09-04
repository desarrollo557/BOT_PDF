/**
 * Human units, in one place.
 *
 * Sizes and durations are shown on four different screens; deriving them
 * separately in each is how the same batch ends up reading 1.2 GB in one place
 * and 1,288 MB in another.
 */

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];

/** Bytes at three significant figures, in the largest unit that stays >= 1. */
export function formatBytes(bytes: number): string {
  if (!bytes || bytes < 0) return '0 B';
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = value >= 100 || unit === 0 ? 0 : value >= 10 ? 1 : 2;
  return `${value.toFixed(digits)} ${UNITS[unit]}`;
}

/** A duration a person would say out loud, not a count of seconds. */
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '—';
  if (seconds < 10) return `${seconds.toFixed(1)} s`;
  if (seconds < 60) return `${Math.round(seconds)} s`;

  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  if (minutes < 60) return `${minutes} min ${String(rest).padStart(2, '0')} s`;

  const hours = Math.floor(minutes / 60);
  return `${hours} h ${String(minutes % 60).padStart(2, '0')} min`;
}

/**
 * Cómo se llama lo que produjo un documento, según lo que resultó ser.
 *
 * La pantalla nació sabiendo contar una sola cosa -- resoluciones -- y desde
 * que procesa libros de registro y expedientes académicos, "12 resoluciones"
 * delante de un libro de diplomas es una cifra correcta con la palabra
 * equivocada. El tipo lo decide el backend sobre lo que está impreso en las
 * páginas, así que aquí sólo se traduce.
 *
 * Un informe anterior a que el tipo existiera no lo trae, y entonces se dice
 * "unidades documentales", que es lo que son en cualquiera de los tres casos.
 */
const UNIT_NAMES: Record<string, [string, string]> = {
  resolucion: ['resolución', 'resoluciones'],
  diploma: ['registro de diploma', 'registros de diploma'],
  matricula: ['expediente', 'expedientes']
};

export function unitFor(
  report: { document_type?: string } | null | undefined,
  count: number
): string {
  const names = UNIT_NAMES[report?.document_type ?? ''];
  if (!names) return count === 1 ? 'unidad documental' : 'unidades documentales';
  return count === 1 ? names[0] : names[1];
}
