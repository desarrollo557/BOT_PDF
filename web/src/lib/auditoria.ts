/**
 * Cómo se dibuja la auditoría de cierre de una corrida (lo pidió el operador el
 * 2026-11-05: que al terminar se asegure que lo de la fuente está en el destino,
 * revise 100 PDF al azar «y todo manejando un margen de errores»).
 *
 * Las cuentas y el margen los calcula el servicio (`api/auditoria.py`); aquí
 * sólo se arman las filas del cuadre, los tonos y la escala del error.
 */
import type {
  AuditoriaDeCierre,
  ComparacionDeLaEntrega,
  MargenDeLaCorrida,
  MargenDeUnaHabilidad,
  MuestraAuditada,
  PdfAuditado
} from './types';
import type { Tono } from './agente';

export interface FilaDelCuadre {
  etiqueta: string;
  origen: number;
  destino: number;
  /** Rótulos de cada lado: «PDF en el origen», «entregados enteros». */
  dichoOrigen: string;
  dichoDestino: string;
  cuadra: boolean;
}

/** Las tres cuentas que tienen que dar lo mismo de un lado y del otro. */
export function filasDelCuadre(comparacion: ComparacionDeLaEntrega): FilaDelCuadre[] {
  return [
    {
      etiqueta: 'PDF',
      origen: comparacion.pdf_origen,
      destino: comparacion.pdf_entregados,
      dichoOrigen: 'en el origen',
      dichoDestino: 'entregados enteros',
      cuadra: comparacion.pdf_origen === comparacion.pdf_entregados
    },
    {
      etiqueta: 'Documentos',
      origen: comparacion.documentos_entregados,
      destino: comparacion.filas_del_indice,
      dichoOrigen: 'entregados',
      dichoDestino: 'filas en los índices',
      // Sin índices (otra habilidad) no hay filas que contar: no es un descuadre.
      cuadra: !comparacion.filas_del_indice || comparacion.documentos_entregados === comparacion.filas_del_indice
    },
    {
      etiqueta: 'Carpetas',
      origen: comparacion.carpetas_con_pdf,
      destino: comparacion.carpetas_completas,
      dichoOrigen: 'con PDF en el origen',
      dichoDestino: 'completas en el destino',
      cuadra: comparacion.carpetas_con_pdf === comparacion.carpetas_completas
    }
  ];
}

/** El tono de cómo terminó la corrida. */
export function tonoDeLaEtapa(etapa: string | null | undefined): Tono {
  if (!etapa) return 'neutral';
  if (etapa === 'Terminado') return 'good';
  if (etapa.includes('dentro del margen')) return 'accent';
  if (etapa.includes('faltantes') || etapa.includes('fuera del margen')) return 'bad';
  return 'warn';
}

export const DICTAMENES: Record<string, { etiqueta: string; tono: Tono }> = {
  'dentro del margen': { etiqueta: 'Dentro del margen', tono: 'good' },
  'sin certeza': { etiqueta: 'Sin certeza', tono: 'warn' },
  'fuera del margen': { etiqueta: 'Fuera del margen', tono: 'bad' }
};

export const ESTADOS_DE_LA_MUESTRA: Record<PdfAuditado['estado'], { etiqueta: string; tono: Tono }> = {
  bien: { etiqueta: 'Bien', tono: 'good' },
  error: { etiqueta: 'Con error', tono: 'bad' },
  dudoso: { etiqueta: 'Dudoso', tono: 'warn' },
  'no se pudo auditar': { etiqueta: 'No se pudo auditar', tono: 'neutral' }
};

/** Lo que dice la fase en curso: «Revisando la muestra: 37 de 100». */
export function faseEnCurso(auditoria: AuditoriaDeCierre): string {
  const hechos = auditoria.hechos ?? 0;
  const total = auditoria.total ?? 0;
  if (auditoria.fase === 'muestra') {
    return total ? `Revisando la muestra al azar: ${hechos} de ${total} PDF` : 'Eligiendo la muestra al azar…';
  }
  return total
    ? `Cuadrando el origen con el destino: ${hechos.toLocaleString('es-CO')} de ${total.toLocaleString('es-CO')} PDF`
    : 'Cuadrando el origen con el destino…';
}

/**
 * La escala del error: hasta dónde llega el eje para que se vean el intervalo
 * y el margen aceptable. Nunca menos del doble del margen.
 */
export function topeDeLaEscala(muestra: MuestraAuditada): number {
  return topeDelMargen(muestra.margen);
}

/** La escala de un margen cualquiera: el de la corrida o el de una habilidad. */
export function topeDelMargen({ hasta, aceptable }: MargenDeLaCorrida): number {
  return Math.min(1, Math.max(aceptable * 2, hasta * 1.25));
}

/**
 * Las habilidades de la muestra, cada una contra su margen, la que se sale
 * primero. Vacío si la muestra es de una sola: entonces el margen de la
 * corrida ya es el suyo.
 */
export function habilidadesDeLaMuestra(muestra: MuestraAuditada): MargenDeUnaHabilidad[] {
  const todas = muestra.por_habilidad ?? [];
  if (todas.length < 2) return [];
  const orden: Record<MargenDeLaCorrida['dictamen'], number> = {
    'fuera del margen': 0,
    'sin certeza': 1,
    'dentro del margen': 2
  };
  return [...todas].sort((a, b) => orden[a.margen.dictamen] - orden[b.margen.dictamen] || b.revisados - a.revisados);
}

/** «3,7 %», con coma decimal. */
export function porCiento(valor: number): string {
  const numero = Math.round(valor * 1000) / 10;
  return `${numero.toLocaleString('es-CO', { maximumFractionDigits: 1 })} %`;
}

/** Los PDF de la muestra que hay que mirar: con error primero, luego los dudosos y los que no se auditaron. */
export function paraMirar(muestra: MuestraAuditada): PdfAuditado[] {
  const orden: Record<PdfAuditado['estado'], number> = { error: 0, dudoso: 1, 'no se pudo auditar': 2, bien: 3 };
  return muestra.pdfs.filter((pdf) => pdf.estado !== 'bien').sort((a, b) => orden[a.estado] - orden[b.estado]);
}
