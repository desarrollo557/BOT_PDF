import { RUNGS, UNREADABLE } from './rungs';
import type { Consumo } from './types';

/** Una foto del avance: cuándo, cuántas páginas y documentos iban, y a qué velocidad. */
export interface Muestra {
  t: number;
  paginas: number;
  documentos: number;
  velocidad: number;
}

/**
 * Las muestras recortadas a `capacidad` sin perder el principio de la corrida.
 *
 * Una corrida de horas no cabe a una muestra por segundo, y quedarse sólo con
 * las últimas borra justo lo que la gráfica de avance tiene que enseñar: desde
 * dónde se vino. Así que, al llenarse, se junta cada par en una: el eje sigue
 * cubriendo la corrida entera con la mitad de detalle.
 */
export function reducirMuestras(muestras: Muestra[], capacidad: number): Muestra[] {
  if (muestras.length <= capacidad) return muestras;
  const juntas: Muestra[] = [];
  for (let i = 0; i < muestras.length; i += 2) {
    const a = muestras[i];
    const b = muestras[i + 1];
    if (!b) {
      juntas.push(a);
      continue;
    }
    // La última de cada par: el avance acumulado es el de ese momento, y la
    // velocidad, la media de las dos.
    juntas.push({ ...b, velocidad: (a.velocidad + b.velocidad) / 2 });
  }
  return juntas;
}

/** El valor de eje redondeado hacia arriba a una cifra que se dice: 7,3 → 8; 140 → 200. */
export function techo(valor: number): number {
  const crudo = Math.max(valor, 1);
  const magnitud = 10 ** Math.floor(Math.log10(crudo));
  return Math.ceil(crudo / magnitud) * magnitud;
}

/** Páginas por segundo de media: lo hecho sobre el tiempo, sin contar el arranque en cero. */
export function velocidadMedia(paginas: number, segundos: number): number {
  return segundos >= 1 && paginas > 0 ? paginas / segundos : 0;
}

/**
 * Cuánto falta, en segundos, o `null` si no hay con qué estimarlo.
 *
 * Con la velocidad de ahora si la hay; si no -- entre un documento y el
 * siguiente de una carpeta la velocidad viva es cero --, con la media.
 */
export function restante(
  hechas: number,
  total: number,
  ahora: number,
  media: number
): number | null {
  if (!total || hechas >= total) return null;
  const velocidad = ahora > 0 ? ahora : media;
  return velocidad > 0 ? (total - hechas) / velocidad : null;
}

/** La hora a la que termina, si se sigue al ritmo de ahora. */
export function horaDeFin(segundosRestantes: number | null, desde = Date.now()): string | null {
  if (segundosRestantes === null || !Number.isFinite(segundosRestantes)) return null;
  return new Date(desde + segundosRestantes * 1000).toLocaleTimeString('es', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  });
}

/** Una parte de un todo: cada peldaño de la cascada con sus páginas. */
export interface Porcion {
  clave: string;
  etiqueta: string;
  color: string;
  valor: number;
}

/**
 * Dónde se resolvió cada página, sumando lo de varios documentos.
 *
 * Los peldaños salen siempre en el orden de la cascada y con su color fijo:
 * el mismo color quiere decir lo mismo en todas las gráficas de la pantalla.
 */
export function procedencia(conteos: Record<string, number>[]): Porcion[] {
  const total: Record<string, number> = {};
  for (const conteo of conteos) {
    for (const [clave, valor] of Object.entries(conteo ?? {})) {
      total[clave] = (total[clave] ?? 0) + (valor || 0);
    }
  }
  return [...RUNGS, UNREADABLE]
    .map((peldano) => ({
      clave: peldano.key,
      etiqueta: peldano.label,
      color: peldano.color,
      valor: total[peldano.key] ?? 0
    }))
    .filter((porcion) => porcion.valor > 0);
}

/**
 * El tiempo de cada etapa, sumado con lo que pasó desde la última vista.
 *
 * Varias a la vez cuentan cada una su tiempo: con tres documentos de un lote
 * leyendo páginas, «Leyendo páginas» acumula el triple. Es tiempo de trabajo,
 * no de reloj, y es lo que dice dónde se va el esfuerzo.
 */
export function acumularEtapas(
  acumulado: Record<string, number>,
  etapas: (string | null | undefined)[],
  segundos: number
): Record<string, number> {
  if (segundos <= 0) return acumulado;
  const siguiente = { ...acumulado };
  for (const etapa of etapas) {
    if (!etapa || etapa === 'done' || etapa === 'failed') continue;
    siguiente[etapa] = (siguiente[etapa] ?? 0) + segundos;
  }
  return siguiente;
}

/** Cuántas páginas quedaron marcadas para revisión en una cinta de avance. */
export function marcadasEnCinta(cinta: string | null | undefined): number {
  let cuenta = 0;
  for (const marca of cinta ?? '') if (marca === UNREADABLE.mark) cuenta++;
  return cuenta;
}

/**
 * Lo gastado con la IA por varios documentos, en una sola cuenta.
 *
 * `null` si ninguno la usó. El coste sólo se suma si todos lo traen: un total
 * que deja fuera a uno sin precio parecería más barato de lo que fue.
 */
export function sumarConsumos(consumos: (Consumo | null | undefined)[]): Consumo | null {
  const con = consumos.filter((c): c is Consumo => Boolean(c && c.peticiones));
  if (!con.length) return null;
  const suma = (campo: keyof Omit<Consumo, 'proveedores' | 'coste_estimado' | 'moneda'>) =>
    con.reduce((total, c) => total + (c[campo] || 0), 0);
  const costes = con.map((c) => c.coste_estimado);
  return {
    proveedores: {},
    peticiones: suma('peticiones'),
    paginas_facturadas: suma('paginas_facturadas'),
    tokens_entrada: suma('tokens_entrada'),
    tokens_salida: suma('tokens_salida'),
    tokens_cache: suma('tokens_cache'),
    tokens: suma('tokens'),
    rechazos: suma('rechazos'),
    fallos: suma('fallos'),
    coste_estimado: costes.every((c) => c !== null)
      ? costes.reduce<number>((total, c) => total + (c ?? 0), 0)
      : null,
    moneda: con[0].moneda
  };
}
