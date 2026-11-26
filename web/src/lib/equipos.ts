/**
 * Los equipos de una corrida compartida, dichos en palabras del operador
 * (2026-11-26).
 *
 * El operador pidió «un monitoreo para ver los que están conectados y poder
 * desconectarlos»: son 6 o 7 PC sobre el mismo destino y la pantalla no decía
 * cuáles estaban ni dejaba pararlos. Las cifras -- el ritmo, el último latido,
 * si se le puede ordenar parar -- las da el servicio
 * (`GET /api/folder-runs/{id}/equipos`); aquí se arman las frases, el orden y a
 * quién se le ofrece cada botón.
 */
import type { Pregunta } from './confirmar.svelte';
import type { EquipoDeLaCorrida, OrdenDeParar } from './types';

/** El tono del punto de estado; la palabra de al lado dice siempre cuál es. */
export type Tono = 'good' | 'warn' | 'bad';

export interface EstadoDelEquipo {
  etiqueta: string;
  tono: Tono;
  /** Si late: entonces su punto late también, despacio. */
  latiendo: boolean;
  /** Si dejó de latir sin retirarse: sus PDF los toman los demás. */
  caido: boolean;
}

export interface AccionesDelEquipo {
  calma: boolean;
  ya: boolean;
  /** Por qué no hay botones, para el título y los lectores de pantalla. */
  porQueNo: string | null;
}

const MILES = new Intl.NumberFormat('es-CO', { maximumFractionDigits: 0 });

/** «uniéndose» y «uniendose» son lo mismo: se compara sin tildes ni mayúsculas. */
function plano(texto: string | null | undefined): string {
  return (texto ?? '')
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .trim()
    .toLowerCase();
}

function terminado(equipo: EquipoDeLaCorrida): boolean {
  return plano(equipo.estado) === 'terminado';
}

/** Una cifra con el punto de miles: «1.096»; «—» sin dato. */
export function cifra(valor: number | null | undefined): string {
  return valor == null || !Number.isFinite(valor) ? '—' : MILES.format(valor);
}

/**
 * «hace 4 s», «hace 3 min», «hace 2 h»: cuánto lleva sin latir, contado hacia
 * abajo para no exagerar (179 s todavía son «hace 2 min»). «—» sin dato.
 */
export function haceCuanto(segundos: number | null | undefined): string {
  if (segundos == null || !Number.isFinite(segundos)) return '—';
  const s = Math.max(0, segundos);
  if (s < 60) return `hace ${Math.max(1, Math.floor(s))} s`;
  if (s < 3600) return `hace ${Math.floor(s / 60)} min`;
  return `hace ${Math.floor(s / 3600)} h`;
}

/** «88 PDF/h», «1.096 PDF/h»; «—» mientras el servicio no lo sabe (menos de 5 min en la corrida). */
export function ritmo(pdfPorHora: number | null | undefined): string {
  if (pdfPorHora == null || !Number.isFinite(pdfPorHora)) return '—';
  return `${MILES.format(Math.round(pdfPorHora))} PDF/h`;
}

/** Quién dio la orden: el equipo desde el que se dio, si no su id, si no el operador. */
export function quienOrdena(orden: OrdenDeParar | null | undefined): string | null {
  return orden?.equipo_que_ordena || orden?.por || orden?.operador || null;
}

/** El arranque de un equipo sin su nombre: «1e52b0» de «COORDINADORTIC-1e52b0». */
export function idCorto(equipo: EquipoDeLaCorrida): string {
  const prefijo = `${equipo.equipo}-`;
  if (equipo.id.startsWith(prefijo)) return equipo.id.slice(prefijo.length);
  return equipo.id === equipo.equipo ? '' : equipo.id;
}

/**
 * El nombre con su arranque, para los botones: «COORDINADORTIC (1e52b0)». Un PC
 * reiniciado deja su arranque viejo, caído, junto al nuevo.
 */
export function rotuloDe(equipo: EquipoDeLaCorrida): string {
  const arranque = idCorto(equipo);
  return arranque ? `${equipo.equipo} (${arranque})` : equipo.equipo;
}

/** Si otro de la lista se llama igual: dos PC con el mismo nombre («SIAR-6ad99c» y «SIAR-ad21be»). */
function repetido(equipo: EquipoDeLaCorrida, equipos: readonly EquipoDeLaCorrida[]): boolean {
  return equipos.some((otro) => otro.id !== equipo.id && otro.equipo === equipo.equipo);
}

/**
 * Cómo se le nombra en una pregunta: «COORDINADORTIC», o «este equipo
 * (DESARROLLADOR)»; con su arranque si otro de la lista se llama igual.
 */
export function nombreDe(equipo: EquipoDeLaCorrida, equipos: readonly EquipoDeLaCorrida[] = []): string {
  const nombre = repetido(equipo, equipos) ? rotuloDe(equipo) : equipo.equipo;
  return equipo.este ? `este equipo (${nombre})` : nombre;
}

/** Lo que se dice arriba con la corrida terminada, en lugar del resumen de los vivos. */
export const FOTO_AL_RETIRARSE = 'Así estaban cuando este equipo se retiró.';

/**
 * Cómo está un equipo, en palabras: «Procesando», «Uniéndose», «Cerrando la
 * corrida», «Parando con calma · orden de SIAR», «Parando ya», «Caído · sin
 * latido hace 3 min» o «Terminado».
 *
 * Con `enVivo` falso -- la corrida de este equipo terminada -- es la foto de
 * cuando se retiró: lo que decía cada latido, sin «Caído» y sin punto que
 * late. El servicio ya no mira y da a todos por no vivos (2026-11-26).
 */
export function estadoDe(equipo: EquipoDeLaCorrida, enVivo = true): EstadoDelEquipo {
  const estado = plano(equipo.estado);
  if (estado === 'terminado') {
    return { etiqueta: 'Terminado', tono: 'good', latiendo: false, caido: false };
  }
  if (enVivo && !equipo.vivo) {
    const hace = haceCuanto(equipo.quieto_hace);
    return {
      etiqueta: hace === '—' ? 'Caído' : `Caído · sin latido ${hace}`,
      tono: 'bad',
      latiendo: false,
      caido: true
    };
  }
  const vivo = { latiendo: enVivo, caido: false };
  if (equipo.orden?.modo === 'ya') return { etiqueta: 'Parando ya', tono: 'warn', ...vivo };
  if (equipo.orden) {
    const quien = quienOrdena(equipo.orden);
    const etiqueta = quien ? `Parando con calma · orden de ${quien}` : 'Parando con calma';
    return { etiqueta, tono: 'warn', ...vivo };
  }
  if (estado === 'cerrando') return { etiqueta: 'Cerrando la corrida', tono: 'good', ...vivo };
  if (estado === 'uniendose') return { etiqueta: 'Uniéndose', tono: 'good', ...vivo };
  if (estado === 'procesando') return { etiqueta: 'Procesando', tono: 'good', ...vivo };
  // Un estado que esta pantalla no conoce (un servicio más nuevo): tal cual.
  const crudo = (equipo.estado ?? '').trim();
  return { etiqueta: crudo ? crudo[0].toUpperCase() + crudo.slice(1) : 'Conectado', tono: 'good', ...vivo };
}

/** Si reparte el trabajo de esta corrida: de la misma corrida y con la misma versión del bot. */
export function esDeEstaCorrida(equipo: EquipoDeLaCorrida): boolean {
  return equipo.de_esta_corrida && equipo.misma_version;
}

/** Por qué va aparte: «otra versión del bot» u «otra corrida»; null si es de esta. */
export function porQueAparte(equipo: EquipoDeLaCorrida): string | null {
  if (!equipo.misma_version) return 'otra versión del bot';
  if (!equipo.de_esta_corrida) return 'otra corrida';
  return null;
}

/**
 * El orden del servicio, por si llegara de otro modo: los de esta corrida
 * primero, luego los vivos, luego este equipo, luego por nombre (sin mirar
 * mayúsculas) y por id.
 */
export function ordenar(equipos: readonly EquipoDeLaCorrida[]): EquipoDeLaCorrida[] {
  const clave = (e: EquipoDeLaCorrida) => [e.de_esta_corrida ? 0 : 1, e.vivo ? 0 : 1, e.este ? 0 : 1];
  const texto = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);
  return [...equipos].sort((a, b) => {
    const x = clave(a);
    const y = clave(b);
    for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] - y[i];
    return texto(a.equipo.toLowerCase(), b.equipo.toLowerCase()) || texto(a.id, b.id);
  });
}

/** Los que reparten esta corrida y, aparte, los latidos de otra corrida o versión. */
export function separar(equipos: readonly EquipoDeLaCorrida[]): {
  deEsta: EquipoDeLaCorrida[];
  otros: EquipoDeLaCorrida[];
} {
  const ordenados = ordenar(equipos);
  return {
    deEsta: ordenados.filter(esDeEstaCorrida),
    otros: ordenados.filter((equipo) => !esDeEstaCorrida(equipo))
  };
}

/**
 * «6 vivos · 1.096 PDF/h», con «1 caído» si lo hay: sólo los de esta corrida
 * que no se retiraron, y el ritmo sumado de los vivos que ya lo tienen.
 */
export function resumen(equipos: readonly EquipoDeLaCorrida[]): string {
  const enLaCorrida = equipos.filter((equipo) => esDeEstaCorrida(equipo) && !terminado(equipo));
  const vivos = enLaCorrida.filter((equipo) => equipo.vivo);
  const caidos = enLaCorrida.length - vivos.length;
  const ritmos = vivos.flatMap((equipo) =>
    equipo.pdf_por_hora != null && Number.isFinite(equipo.pdf_por_hora) ? [equipo.pdf_por_hora] : []
  );
  const partes = [`${vivos.length} ${vivos.length === 1 ? 'vivo' : 'vivos'}`];
  if (caidos) partes.push(`${caidos} ${caidos === 1 ? 'caído' : 'caídos'}`);
  if (ritmos.length) partes.push(ritmo(ritmos.reduce((suma, valor) => suma + valor, 0)));
  return partes.join(' · ');
}

/**
 * Qué botones lleva un equipo. Manda `se_puede_parar` del servicio, que es
 * quien sabe si late o está cerrando; aquí sólo se quita lo que ya no haría
 * nada: «calma» a quien ya tiene una orden, y los dos a quien ya tiene «ya».
 * Los de otra corrida o versión, y todos con la corrida terminada, ninguno.
 */
export function accionesDe(equipo: EquipoDeLaCorrida, corridaActiva: boolean): AccionesDelEquipo {
  const ninguna = (porQueNo: string | null): AccionesDelEquipo => ({ calma: false, ya: false, porQueNo });
  if (!esDeEstaCorrida(equipo)) {
    return ninguna(equipo.por_que_no ?? 'Es de otra corrida o de otra versión del bot.');
  }
  if (!corridaActiva) return ninguna(equipo.por_que_no ?? 'La corrida ya terminó.');
  if (!equipo.se_puede_parar) return ninguna(equipo.por_que_no);
  if (equipo.orden?.modo === 'ya') return ninguna('Ya tiene la orden de parar ya.');
  return { calma: !equipo.orden, ya: true, porQueNo: null };
}

/**
 * A quiénes llega «Parar todos con calma»: los de esta corrida a los que todavía
 * se les puede ordenar, con este equipo al final. Si este se parara primero sin
 * nada en curso, su corrida terminaría y ya no podría ordenar a los demás.
 */
export function objetivosDePararTodos(
  equipos: readonly EquipoDeLaCorrida[],
  corridaActiva: boolean
): EquipoDeLaCorrida[] {
  const objetivos = ordenar(equipos).filter((equipo) => accionesDe(equipo, corridaActiva).calma);
  return [...objetivos.filter((equipo) => !equipo.este), ...objetivos.filter((equipo) => equipo.este)];
}

/** Si otro equipo de la corrida sigue tomando PDF cuando éste pare. */
function otrosSiguen(equipo: EquipoDeLaCorrida, equipos: readonly EquipoDeLaCorrida[]): boolean {
  return equipos.some(
    (otro) => otro.id !== equipo.id && esDeEstaCorrida(otro) && otro.vivo && !terminado(otro) && !otro.orden
  );
}

/**
 * La confirmación de parar un equipo. «Parar ya» va en rojo: lo que estaba
 * leyendo se lee otra vez en otro equipo, y lo leído con la IA puede pagarse
 * dos veces.
 */
export function preguntaDeParar(
  equipo: EquipoDeLaCorrida,
  modo: OrdenDeParar['modo'],
  equipos: readonly EquipoDeLaCorrida[]
): Pregunta {
  const quien = nombreDe(equipo, equipos);
  const siguen = otrosSiguen(equipo, equipos);
  if (modo === 'ya') {
    return {
      titulo: `¿Parar ya ${quien}?`,
      mensaje:
        'Se detiene en el acto, sin terminar lo que está leyendo: eso lo vuelve a leer ' +
        (siguen ? 'otro equipo' : 'el equipo que vuelva a lanzar la carpeta') +
        ' y puede pagarse otra vez. Lo que ya entregó se queda en el destino.',
      aceptar: 'Parar ya',
      volver: 'Seguir',
      peligro: true
    };
  }
  return {
    titulo: `¿Parar con calma ${quien}?`,
    mensaje:
      'Termina lo que está leyendo, lo entrega y se retira de la corrida. ' +
      (siguen
        ? 'Lo que no alcanzó a tomar lo siguen los demás equipos.'
        : 'Lo que no alcanzó a tomar queda para cuando se vuelva a lanzar la carpeta.'),
    aceptar: 'Parar con calma',
    volver: 'Seguir'
  };
}

/** La confirmación de «Parar todos con calma»: a cuántos y a quiénes, y qué pasa con lo que falta. */
export function preguntaDePararTodos(objetivos: readonly EquipoDeLaCorrida[]): Pregunta {
  const cuantos = objetivos.length;
  const conEste = objetivos.some((equipo) => equipo.este);
  const nombres = objetivos.map((equipo) => {
    const nombre = repetido(equipo, objetivos) ? rotuloDe(equipo) : equipo.equipo;
    return equipo.este ? `${nombre} (este)` : nombre;
  });
  const lista =
    nombres.length > 1 ? `${nombres.slice(0, -1).join(', ')} y ${nombres[nombres.length - 1]}` : (nombres[0] ?? '');
  const uno = cuantos === 1;
  const quienes = uno
    ? `Es ${objetivos[0] ? nombreDe(objetivos[0]) : lista}`
    : `Son ${cuantos} equipos${conEste ? ', este incluido' : ''}: ${lista}`;
  return {
    // Uno solo cuando los demás ya tienen su orden: es el que falta.
    titulo: uno ? '¿Parar con calma el único equipo que falta?' : `¿Parar con calma los ${cuantos} equipos de la corrida?`,
    mensaje:
      `${quienes}. ${uno ? 'Termina' : 'Cada uno termina'} lo que está leyendo, lo entrega y se retira. ` +
      'Lo que ninguno alcanzó a tomar queda para cuando se vuelva a lanzar la carpeta.',
    aceptar: 'Parar todos con calma',
    volver: 'Seguir'
  };
}

/**
 * Lo que no salió de una orden, con el nombre del equipo delante si el
 * servicio no lo dice ya («Ese equipo no está en esta corrida.»).
 */
export function falloDeLaOrden(equipo: EquipoDeLaCorrida, mensaje: string): string {
  return mensaje.includes(equipo.equipo) ? mensaje : `${equipo.equipo}: ${mensaje}`;
}

/**
 * La nota de la corrida que cumple una orden de parar: «Parando con calma por
 * orden de SIAR: termina lo que está leyendo, lo entrega y se retira.»
 */
export function notaDeParando(orden: OrdenDeParar | null | undefined): string | null {
  if (!orden) return null;
  const quien = quienOrdena(orden);
  const deQuien = quien ? ` por orden de ${quien}` : '';
  return orden.modo === 'ya'
    ? `Parando ya${deQuien}: lo que estaba leyendo lo vuelve a leer otro equipo.`
    : `Parando con calma${deQuien}: termina lo que está leyendo, lo entrega y se retira.`;
}

/**
 * Y la de la corrida que ya se detuvo por una orden. El servicio escribe quién
 * y cómo para completar la frase: «Detenido por el equipo SIAR (operador
 * Juan), con «Parar con calma».»
 */
export function notaDeDetenida(detenidoPor: string | null | undefined): string | null {
  const quien = detenidoPor?.trim().replace(/\.$/, '');
  return quien ? `Detenido por ${quien}.` : null;
}
