/**
 * Cómo se dice en la pantalla de la carpeta si va por red o por local, a qué
 * velocidad y cuánto falta (lo pidió el operador el 2026-11-05).
 *
 * Las cifras -- la velocidad, lo que falta -- las escribe el servicio
 * (`domain/ritmo.py`), para que la pantalla y el Excel digan lo mismo; aquí
 * sólo se arman las frases.
 */
import type { DescargaDeRed, LadoDeLaRed, RedDeLaCorrida } from './types';

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
    return red.red_s != null ? `Mover lo que queda por la red: ${aprox(red.falta_red)}` : null;
  }
  if (red.falta_s === 0) return null;
  const cuanto = `${red.al_menos ? 'Falta al menos' : 'Falta'} ${aprox(red.falta)}`;
  return red.red_s != null && red.red_s > 0 ? `${cuanto} (la red, ${aprox(red.falta_red)})` : cuanto;
}

/** «~40 min»; «menos de 1 min» va sin la tilde, que ya dice que es aproximado («~menos de 1 min»). */
function aprox(duracion: string): string {
  return duracion.startsWith('menos') ? duracion : `~${duracion}`;
}

/** Si algún lado va por la red: entonces la línea se resalta. */
export function vaPorLaRed(red: RedDeLaCorrida): boolean {
  return red.origen.acceso === 'red' || red.destino.acceso === 'red';
}

// -- la descarga de un PDF de la red ------------------------------------------------------
//
// El operador, 2026-11-09: «cuando esté un archivo o un PDF a procesar en la red
// y se esté bajando, que se muestre el progreso de descarga, el tamaño del
// archivo, esos detallitos». Las cifras van en base 1024 y con coma, como las
// escribe el servicio (`domain/ritmo.py`), no como `formatBytes`.

const MB = 1024 * 1024;

function conComa(valor: number): string {
  // «9,96» redondea a «10»: sin decimal, como lo de diez para arriba.
  return (Math.round(valor * 10) / 10 < 10 ? valor.toFixed(1) : valor.toFixed(0)).replace('.', ',');
}

/** «850 KB», «2,4 MB», «410 MB», «1,6 GB». */
export function tamanoLegible(bytes: number): string {
  if (Math.round(bytes / 1024) < 1024) return `${Math.round(bytes / 1024)} KB`;
  const mb = bytes / MB;
  if (Math.round(mb) >= 1024) return `${(mb / 1024).toFixed(1).replace('.', ',')} GB`;
  return `${conComa(mb)} MB`;
}

/** «123 / 410 MB»; con unidades distintas, «850 KB / 410 MB». */
function deCuanto(bytes: number, total: number): string {
  const hecho = tamanoLegible(bytes);
  const todo = tamanoLegible(total);
  const espacio = hecho.lastIndexOf(' ');
  const unidad = hecho.slice(espacio + 1);
  return todo.endsWith(` ${unidad}`) ? `${hecho.slice(0, espacio)} / ${todo}` : `${hecho} / ${todo}`;
}

/**
 * El porcentaje bajado, para la barra: `null` si no se sabe el tamaño o si
 * todavía espera turno (la barra va entonces sin porcentaje). Nunca dice 100
 * antes de acabar, y nunca más de 100 si el archivo creció mientras bajaba.
 */
export function avanceDeLaDescarga(descarga: DescargaDeRed): number | null {
  if (descarga.estado !== 'bajando' || !descarga.total) return null;
  return Math.min(100, Math.floor((100 * descarga.bytes) / descarga.total));
}

/** «45 s», «2 min», «1 h 05 min»: lo que falta de una descarga, en corto. */
export function faltaCorta(segundos: number | null | undefined): string | null {
  if (segundos == null || !Number.isFinite(segundos)) return null;
  if (Math.round(segundos) < 60) return `${Math.max(1, Math.round(segundos))} s`;
  const minutos = Math.round(segundos / 60);
  if (minutos < 60) return `${minutos} min`;
  return `${Math.floor(minutos / 60)} h ${String(minutos % 60).padStart(2, '0')} min`;
}

/**
 * La línea de un PDF que se baja: «Bajando de la red · 123 / 410 MB · 30 % ·
 * 3,5 MB/s · falta ~1 min»; mientras espera, «Esperando turno para bajar de la
 * red · 410 MB».
 */
export function bajandoDeLaRed(descarga: DescargaDeRed): string {
  if (descarga.estado === 'esperando') {
    return descarga.total
      ? `Esperando turno para bajar de la red · ${tamanoLegible(descarga.total)}`
      : 'Esperando turno para bajar de la red';
  }
  const partes = ['Bajando de la red'];
  partes.push(descarga.total ? deCuanto(descarga.bytes, descarga.total) : tamanoLegible(descarga.bytes));
  const avance = avanceDeLaDescarga(descarga);
  if (avance != null) partes.push(`${avance} %`);
  if (descarga.velocidad) partes.push(descarga.velocidad);
  const falta = faltaCorta(descarga.falta_s);
  if (falta) partes.push(`falta ~${falta}`);
  if ((descarga.intento ?? 1) > 1) partes.push(`intento ${descarga.intento}`);
  return partes.join(' · ');
}

/**
 * Lo que baja ahora la corrida, para la línea «Red»: «Bajando 2 PDF · 246 / 820
 * MB»; `null` si no baja ninguno. Los que esperan turno no cuentan.
 */
export function resumenDeLasDescargas(descargas: DescargaDeRed[]): string | null {
  const bajando = descargas.filter((d) => d.estado === 'bajando');
  if (!bajando.length) return null;
  const bytes = bajando.reduce((suma, d) => suma + d.bytes, 0);
  // Con alguno de tamaño desconocido, la suma de los totales no es un total.
  const total = bajando.every((d) => d.total > 0) ? bajando.reduce((suma, d) => suma + d.total, 0) : 0;
  const cuantos = bajando.length === 1 ? '1 PDF' : `${bajando.length} PDF`;
  return `Bajando ${cuantos} · ${total ? deCuanto(bytes, total) : tamanoLegible(bytes)}`;
}
