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
