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

/**
 * Si la muestra es de filas del inventario y no de PDF cortados. Desde el
 * 2026-11-09 una corrida de «Solo inventario» no entrega PDF cortados, y su
 * muestra son filas contra sus páginas del original: antes salía «muestra: 0
 * de 0» y un «< 0 % de error» que no medía nada.
 */
export function esDeFilas(algo: { unidad?: MuestraAuditada['unidad'] } | null | undefined): boolean {
  return algo?.unidad === 'filas';
}

/** Lo que se cuenta en la muestra: «filas» o «PDF». */
function queSeCuenta(algo: { unidad?: MuestraAuditada['unidad'] } | null | undefined): string {
  return esDeFilas(algo) ? 'filas' : 'PDF';
}

/** Lo que dice la fase en curso: «Revisando la muestra: 37 de 100». */
export function faseEnCurso(auditoria: AuditoriaDeCierre): string {
  const hechos = auditoria.hechos ?? 0;
  const total = auditoria.total ?? 0;
  if (auditoria.fase === 'muestra') {
    return total
      ? `Revisando la muestra al azar: ${hechos} de ${total} ${queSeCuenta(auditoria)}`
      : 'Eligiendo la muestra al azar…';
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

/**
 * Si la muestra no revisó nada. Una muestra vacía no mide ningún error:
 * Wilson con cero revisados da un intervalo sin sentido y se leía «< 0 % de
 * error, sin certeza» (2026-11-09). Se dice en palabras, sin reja ni escala.
 */
export function muestraVacia(muestra: MuestraAuditada): boolean {
  return !muestra.revisados;
}

/**
 * Por qué no hay muestra: o la corrida no entregó nada que revisar, o había
 * candidatos y ninguno se pudo abrir.
 */
export function textoSinMuestra(muestra: MuestraAuditada): string {
  return muestra.candidatos > 0
    ? 'Sin muestra: no se pudo revisar ningún elemento'
    : 'Sin muestra: la corrida no entregó PDF cortados ni filas de inventario que revisar';
}

/** El rótulo de la muestra: «Muestra al azar: 100 filas del inventario». */
export function rotuloDeLaMuestra(muestra: MuestraAuditada): string {
  const cuantos = esDeFilas(muestra) ? `${muestra.revisados} filas del inventario` : `${muestra.revisados} PDF`;
  return `Muestra al azar: ${cuantos}${muestra.ampliada ? ', ampliada por los errores' : ''}`;
}

/**
 * La muestra en una línea, para el aviso del Resumen: «muestra: 98 de 100
 * filas bien · error < 3,7 %, dentro del margen». Vacía, dice por qué; nunca
 * un «< 0 %».
 */
export function avisoDeLaMuestra(muestra: MuestraAuditada): string {
  if (muestraVacia(muestra)) return textoSinMuestra(muestra);
  const de = esDeFilas(muestra) ? ' filas' : '';
  const base = `muestra: ${muestra.bien} de ${muestra.revisados}${de} bien`;
  const dictamen = DICTAMENES[muestra.margen.dictamen];
  if (!dictamen) return base;
  const error = muestra.margen.errores ? porCiento(muestra.margen.tasa) : `< ${porCiento(muestra.margen.hasta)}`;
  return `${base} · error ${error}, ${dictamen.etiqueta.toLowerCase()}`;
}

/**
 * Qué hizo la IA en una muestra de filas: «La IA revisó 4 datos dudosos · 4
 * peticiones · 3.120 tokens», o que no la hubo porque la corrida se hizo sin
 * ella (el operador: la IA sólo si la corrida se hizo con ella). `null` en
 * las muestras que no lo dicen, las de PDF y las anteriores.
 */
export function iaDeLaMuestra(muestra: MuestraAuditada): string | null {
  if (muestra.con_ia === undefined) return null;
  if (!muestra.con_ia) return 'Sin IA: lo dudoso queda para revisar';
  const datos = muestra.preguntadas_a_la_ia ?? 0;
  const consumo = muestra.consumo_ia;
  const fallos = consumo?.fallos ?? 0;
  // Una IA caída o con la llave mala no «revisó» nada: se dice (la revisión, 2026-11-09).
  const sinRespuesta = fallos ? ` · la IA no respondió en ${fallos.toLocaleString('es-CO')} ${fallos === 1 ? 'fila' : 'filas'}` : '';
  if (!datos && fallos) return `La IA no respondió: lo dudoso queda para revisar${sinRespuesta}`;
  const revisados = `La IA revisó ${datos.toLocaleString('es-CO')} ${datos === 1 ? 'dato dudoso' : 'datos dudosos'}`;
  if (!consumo) return revisados;
  const peticiones = `${consumo.peticiones.toLocaleString('es-CO')} ${consumo.peticiones === 1 ? 'petición' : 'peticiones'}`;
  return `${revisados} · ${peticiones} · ${consumo.tokens.toLocaleString('es-CO')} tokens${sinRespuesta}`;
}

/** Los PDF de la muestra que hay que mirar: con error primero, luego los dudosos y los que no se auditaron. */
export function paraMirar(muestra: MuestraAuditada): PdfAuditado[] {
  const orden: Record<PdfAuditado['estado'], number> = { error: 0, dudoso: 1, 'no se pudo auditar': 2, bien: 3 };
  return muestra.pdfs.filter((pdf) => pdf.estado !== 'bien').sort((a, b) => orden[a.estado] - orden[b.estado]);
}
