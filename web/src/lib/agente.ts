/**
 * Cómo se dibuja el trabajo del agente revisor (lo pidió el operador el
 * 2026-11-05: «que se muestre el trabajo del agente revisando todo en el front
 * de una manera gráfica muy llamativa pero profesional»).
 *
 * Todo sale del informe que dejó el servicio -- nada se estima --: las costuras
 * que salieron del margen vienen con su resultado, y las demás son las que el
 * agente validó, así que se deducen de los documentos que salieron.
 */
import type {
  AgenteDeLaCorrida,
  CuentasDeLosDatos,
  EstadoDelSuceso,
  FechasDeLaCorrida,
  MovimientoDelRevisor,
  RevisionDeCortes
} from './types';

/** El tono de cada estado, con su palabra: nada depende sólo del color. */
export type Tono = 'good' | 'accent' | 'warn' | 'bad' | 'ia' | 'neutral';

export const ESTADOS: Record<EstadoDelSuceso, { etiqueta: string; tono: Tono }> = {
  validado: { etiqueta: 'Validado', tono: 'good' },
  corregido: { etiqueta: 'Corregido', tono: 'accent' },
  'en revisión': { etiqueta: 'En revisión', tono: 'warn' },
  'no corrió': { etiqueta: 'Sin revisar', tono: 'bad' },
  problema: { etiqueta: 'No cuadra en el disco', tono: 'bad' },
  datos: { etiqueta: 'Dato con error', tono: 'bad' },
  // El revisor de fechas (2026-11-10): corregida con prueba, o a revisión con su motivo.
  'fecha corregida': { etiqueta: 'Fecha corregida', tono: 'accent' },
  'fecha a revisión': { etiqueta: 'Fecha a revisión', tono: 'warn' }
};

/**
 * «Fechas: 189 confirmadas · 0 corregidas · 5 a revisión» (lo pidió el
 * operador el 2026-11-10: ver que cada fecha inicial y final es la que es).
 * `null` si el revisor de fechas aún no revisó nada: no se dice «0 de 0».
 */
export function fraseDeFechas(fechas: FechasDeLaCorrida | null | undefined): string | null {
  if (!fechas?.revisados) return null;
  const partes = [
    `${fechas.confirmadas} ${fechas.confirmadas === 1 ? 'confirmada' : 'confirmadas'}`,
    `${fechas.corregidas} ${fechas.corregidas === 1 ? 'corregida' : 'corregidas'}`,
    `${fechas.a_revision} a revisión`
  ];
  return `Fechas: ${partes.join(' · ')}`;
}

/** La nota de la frase: los documentos sin fechas que revisar y lo que preguntó a la IA. */
export function notaDeFechas(fechas: FechasDeLaCorrida): string {
  const partes = [`${fechas.revisados} ${fechas.revisados === 1 ? 'documento revisado' : 'documentos revisados'}`];
  if (fechas.sin_dato) partes.push(`${fechas.sin_dato} sin fechas en su papel`);
  if (fechas.preguntadas_a_la_ia) {
    partes.push(`${fechas.preguntadas_a_la_ia} ${fechas.preguntadas_a_la_ia === 1 ? 'decidida' : 'decididas'} por la IA`);
  }
  return partes.join(' · ');
}

/** Cómo se llama cada dato que el agente revisa, en el orden en que se dice (2026-11-06). */
export const CAMPOS_DE_LOS_DATOS: Record<string, string> = {
  nombre: 'Nombre',
  identificacion: 'Cédula, TI o libreta',
  codigo: 'Código',
  fechas: 'Fechas extremas',
  archivo: 'Nombre del PDF'
};

export interface FilaDeUnDato {
  campo: string;
  etiqueta: string;
  bien: number;
  dudas: number;
  errores: number;
  /** En blanco en el papel, verificado. */
  enBlanco: number;
  total: number;
}

/** Una fila por dato, en su orden, con cuántos documentos lo tienen bien, para mirar o con error. */
export function filasDeLosDatos(datos: CuentasDeLosDatos): FilaDeUnDato[] {
  const orden = Object.keys(CAMPOS_DE_LOS_DATOS);
  const puesto = (campo: string) => (orden.includes(campo) ? orden.indexOf(campo) : orden.length);
  return Object.entries(datos.por_campo ?? {})
    .map(([campo, cuentas]) => ({
      campo,
      etiqueta: CAMPOS_DE_LOS_DATOS[campo] ?? campo,
      bien: cuentas.bien,
      dudas: cuentas.dudas,
      errores: cuentas.errores,
      enBlanco: cuentas.en_blanco ?? 0,
      total: cuentas.bien + cuentas.dudas + cuentas.errores + (cuentas.en_blanco ?? 0)
    }))
    .sort((a, b) => puesto(a.campo) - puesto(b.campo));
}

/** Lo que el agente hizo con una costura. */
export type ResultadoDeCostura = 'validada' | 'corregida' | 'confirmada' | 'revision';

export const RESULTADOS: Record<ResultadoDeCostura, { etiqueta: string; tono: Tono }> = {
  validada: { etiqueta: 'Validada', tono: 'good' },
  confirmada: { etiqueta: 'Confirmada por la IA', tono: 'ia' },
  corregida: { etiqueta: 'Corregida', tono: 'accent' },
  revision: { etiqueta: 'A revisión', tono: 'warn' }
};

export interface HojaDeLaCinta {
  pagina: number;
  /** El puesto del PDF en que salió, desde 0; -1 si no salió en ninguno. */
  documento: number;
  /** Si abre su PDF: ahí va el número del documento. */
  abre: boolean;
  /** La corrección que la trajo aquí, si el agente la movió. */
  movida: MovimientoDelRevisor | null;
  /** Por qué alguien tiene que mirarla, si va a revisión. */
  revision: string | null;
}

export interface CosturaDeLaCinta {
  izq: number;
  der: number;
  /** Cómo salieron: en el mismo PDF (unión) o en dos (corte). */
  tipo: 'union' | 'corte';
  resultado: ResultadoDeCostura;
  /** Lo que el papel decía en contra, si salió del margen. */
  motivo: string | null;
  confianza: number | null;
}

export interface Cinta {
  hojas: HojaDeLaCinta[];
  /** La costura entre la hoja `i` y la `i + 1`, en el mismo orden que `hojas`. */
  costuras: CosturaDeLaCinta[];
  documentos: number;
}

/** Las hojas del PDF de origen, en su orden, con el documento en que salió cada una y cada costura. */
export function cinta(revision: RevisionDeCortes, paginas: number): Cinta {
  const documentoDe = new Map<number, number>();
  (revision.documentos ?? []).forEach((documento, indice) => {
    for (const pagina of documento.paginas) documentoDe.set(pagina, indice);
  });
  const movidas = new Map<number, MovimientoDelRevisor>();
  for (const movimiento of revision.movimientos ?? []) {
    for (const pagina of movimiento.paginas) movidas.set(pagina, movimiento);
  }
  const enRevision = new Map<number, string>();
  for (const item of revision.en_revision ?? []) {
    if (!enRevision.has(item.page)) enRevision.set(item.page, item.reason);
  }
  const fueraEn = new Map((revision.fuera_del_margen ?? []).map((costura) => [costura.der, costura]));

  const total = Math.max(paginas, ...documentoDe.keys(), 0);
  const hojas: HojaDeLaCinta[] = [];
  const costuras: CosturaDeLaCinta[] = [];
  for (let pagina = 1; pagina <= total; pagina++) {
    const documento = documentoDe.get(pagina) ?? -1;
    hojas.push({
      pagina,
      documento,
      abre: pagina === 1 || documentoDe.get(pagina - 1) !== documento,
      movida: movidas.get(pagina) ?? null,
      revision: enRevision.get(pagina) ?? null
    });
    if (pagina < total) {
      const fuera = fueraEn.get(pagina + 1);
      costuras.push({
        izq: pagina,
        der: pagina + 1,
        tipo: documento === (documentoDe.get(pagina + 1) ?? -1) ? 'union' : 'corte',
        resultado: fuera?.resultado ?? 'validada',
        motivo: fuera?.motivo ?? null,
        confianza: fuera?.confianza ?? null
      });
    }
  }
  return { hojas, costuras, documentos: revision.documentos?.length ?? 0 };
}

export interface Tramo {
  clave: string;
  etiqueta: string;
  valor: number;
  tono: Tono;
}

/** Cómo se repartieron las costuras de un PDF: lo que dibuja el anillo. Sin los tramos en cero. */
export function repartoDeCosturas(revision: RevisionDeCortes): Tramo[] {
  const fuera = revision.fuera_del_margen ?? [];
  const cuenta = (resultado: ResultadoDeCostura) => fuera.filter((c) => c.resultado === resultado).length;
  const tramos: Tramo[] = [
    { clave: 'validada', etiqueta: 'Dentro del margen', valor: revision.dentro_del_margen ?? 0, tono: 'good' },
    { clave: 'confirmada', etiqueta: 'Confirmadas por la IA', valor: cuenta('confirmada'), tono: 'ia' },
    { clave: 'corregida', etiqueta: 'Corregidas', valor: cuenta('corregida'), tono: 'accent' },
    { clave: 'revision', etiqueta: 'A revisión', valor: cuenta('revision'), tono: 'warn' }
  ];
  return tramos.filter((tramo) => tramo.valor > 0);
}

/** Cómo salieron los PDF de una corrida: lo que dibuja la barra del monitor. Sin los tramos en cero. */
export function repartoDePdf(agente: AgenteDeLaCorrida): Tramo[] {
  const tramos: Tramo[] = [
    { clave: 'validado', etiqueta: 'Validados', valor: agente.validados, tono: 'good' },
    { clave: 'corregido', etiqueta: 'Corregidos', valor: agente.corregidos, tono: 'accent' },
    { clave: 'en revisión', etiqueta: 'En revisión', valor: agente.en_revision, tono: 'warn' },
    { clave: 'no corrió', etiqueta: 'Sin revisar', valor: agente.sin_revisar, tono: 'bad' }
  ];
  return tramos.filter((tramo) => tramo.valor > 0);
}

/** «97 %», o `null` sin nada que contar: una caja de una hoja no tiene costuras. */
export function porcentaje(parte: number, total: number): string | null {
  if (!total) return null;
  const valor = (parte / total) * 100;
  // 99,6 % no se redondea a 100: diría que no hubo nada fuera del margen.
  const redondeado = parte < total ? Math.min(Math.round(valor), 99) : 100;
  return `${redondeado} %`;
}

/** «4–5», «4, 7». */
export function rango(paginas: readonly number[] | null | undefined): string {
  const ordenadas = [...(paginas ?? [])].sort((a, b) => a - b);
  if (!ordenadas.length) return '';
  const seguidas = ordenadas.every((pagina, i) => i === 0 || pagina === ordenadas[i - 1] + 1);
  if (seguidas) return ordenadas.length === 1 ? `${ordenadas[0]}` : `${ordenadas[0]}–${ordenadas.at(-1)}`;
  return ordenadas.join(', ');
}

/** «Hojas 4–5 → con las hojas 2–3», «Hoja 9 → en su propio documento». */
export function queMovio(movimiento: MovimientoDelRevisor): string {
  const cuantas = movimiento.paginas.length === 1 ? 'Hoja' : 'Hojas';
  const destino = movimiento.hacia?.length
    ? `con ${movimiento.hacia.length === 1 ? 'la hoja' : 'las hojas'} ${rango(movimiento.hacia)}`
    : 'en su propio documento';
  return `${cuantas} ${rango(movimiento.paginas)} → ${destino}`;
}

/** Quién decidió una corrección, dicho para el operador. */
export function porQuien(por: string): string {
  if (por === 'la IA') return 'Decidido por la IA';
  if (por === 'dos pruebas del papel') return 'Dos pruebas del papel';
  return por.charAt(0).toUpperCase() + por.slice(1);
}

/**
 * La frase de cabecera: «Revisó 10 costuras entre 11 hojas: todas dentro del margen».
 * Se dice con las cifras del informe, no con su resumen técnico.
 */
export function frase(revision: RevisionDeCortes, paginas: number): string {
  if (revision.estado === 'no corrió') return revision.resumen ?? 'El agente no pudo revisar este PDF.';
  const costuras = revision.costuras ?? 0;
  if (!costuras) return `Una sola hoja: no hay costuras que revisar.`;
  const dentro = revision.dentro_del_margen ?? 0;
  const base = `Revisó ${costuras} ${costuras === 1 ? 'costura' : 'costuras'} entre ${paginas} hojas`;
  if (dentro === costuras) return `${base}: todas dentro del margen de error.`;
  const fuera = costuras - dentro;
  const corregidas = revision.movimientos?.length ?? 0;
  const partes = [`${fuera} ${fuera === 1 ? 'salió' : 'salieron'} del margen`];
  if (corregidas) partes.push(`${corregidas} ${corregidas === 1 ? 'corrección' : 'correcciones'}`);
  const confirmadas = revision.confirmadas_por_la_ia ?? 0;
  if (confirmadas) partes.push(`${confirmadas} ${confirmadas === 1 ? 'confirmada' : 'confirmadas'} por la IA`);
  const aRevision = revision.en_revision?.length ?? 0;
  if (aRevision) partes.push(`${aRevision} a revisión`);
  return `${base}: ${partes.join(', ')}.`;
}
