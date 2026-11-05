/**
 * Cómo se dice en la pantalla de la carpeta si va por red o por local, a qué
 * velocidad y cuánto falta (lo pidió el operador el 2026-11-05).
 *
 * Las cifras -- la velocidad, lo que falta -- las escribe el servicio
 * (`domain/ritmo.py`), para que la pantalla y el Excel digan lo mismo; aquí
 * sólo se arman las frases.
 */
import type { LadoDeLaRed, RedDeLaCorrida } from './types';

/** «Red · 4,2 MB/s», «Local · 110 MB/s», «Red · midiendo…». */
export function lado(datos: LadoDeLaRed, midiendo: boolean): string {
  const acceso = datos.acceso === 'red' ? 'Red' : datos.acceso === 'local' ? 'Local' : '—';
  if (datos.mb_s != null) return `${acceso} · ${datos.velocidad}`;
  return midiendo ? `${acceso} · midiendo…` : acceso;
}

/**
 * «Falta ~3 h 10 min (la red, ~40 min)», con «al menos» mientras el origen
 * se sigue recorriendo; `null` si todavía no hay con qué estimar.
 */
export function loQueFalta(red: RedDeLaCorrida): string | null {
  if (red.falta_s == null) {
    return red.red_s != null ? `Mover lo que queda por la red: ~${red.falta_red}` : null;
  }
  if (red.falta_s === 0) return null;
  const cuanto = `${red.al_menos ? 'Falta al menos' : 'Falta'} ~${red.falta}`;
  return red.red_s != null && red.red_s > 0 ? `${cuanto} (la red, ~${red.falta_red})` : cuanto;
}

/** Si algún lado va por la red: entonces la línea se resalta. */
export function vaPorLaRed(red: RedDeLaCorrida): boolean {
  return red.origen.acceso === 'red' || red.destino.acceso === 'red';
}
