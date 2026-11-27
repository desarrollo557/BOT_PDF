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
 *
 * Desde el 2026-11-27, también la velocidad en PDF por minuto -- la de ahora y
 * la acumulada, en total y por PC --, quién es el principal y los recursos de
 * cada PC. El operador: «llevar un promedio de velocidad de procesamiento de
 * archivos por minuto contando los PC activos», y el principal «deberá tener
 * más capacidad de recursos, RAM, disco». Las sumas, los promedios y el aviso
 * los hace el servicio; aquí, otra vez, sólo las palabras.
 */
import type { Pregunta } from './confirmar.svelte';
import type { EquipoDeLaCorrida, EquiposDeLaCorrida, OrdenDeParar, RecursosDelEquipo } from './types';

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
/** Siempre un decimal, con la coma: «1,5», «18,4», «3,0». */
const UN_DECIMAL = new Intl.NumberFormat('es-CO', { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/** El número, o null si no lo hay: null, ausente, NaN o infinito. */
function numero(valor: number | null | undefined): number | null {
  return valor != null && Number.isFinite(valor) ? valor : null;
}

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

/**
 * «1,5 PDF/min», «18,4 PDF/min»: la velocidad con un decimal y la coma. Era
 * «88 PDF/h» hasta el 2026-11-27, cuando el operador la pidió por minuto. «—»
 * mientras el servicio no la sabe.
 */
export function porMinuto(pdfPorMinuto: number | null | undefined): string {
  const valor = numero(pdfPorMinuto);
  return valor == null ? '—' : `${UN_DECIMAL.format(valor)} PDF/min`;
}

/** Lo de un servicio anterior al 2026-11-27, que sólo daba el ritmo por hora: entre 60. */
function porHoraEnMinutos(equipo: EquipoDeLaCorrida): number | null {
  const porHora = numero(equipo.pdf_por_hora);
  return porHora == null ? null : porHora / 60;
}

/**
 * Lo que procesa ahora, en PDF por minuto: lo de sus últimos 10 min, o null en
 * sus 2 primeros minutos. Sólo si el servicio no lo trae -- uno anterior --,
 * su ritmo por hora entre 60: un null del servicio de hoy no se rellena.
 */
function ahoraDe(equipo: EquipoDeLaCorrida): number | null {
  return equipo.pdf_por_minuto === undefined ? porHoraEnMinutos(equipo) : numero(equipo.pdf_por_minuto);
}

/**
 * Su promedio desde que se unió, en PDF por minuto; null en sus 5 primeros
 * minutos. Con un servicio anterior, su ritmo por hora entre 60, que era lo
 * mismo contado con lo hecho.
 */
export function promedioDe(equipo: EquipoDeLaCorrida): number | null {
  return equipo.pdf_por_minuto_promedio === undefined
    ? porHoraEnMinutos(equipo)
    : numero(equipo.pdf_por_minuto_promedio);
}

// -- los recursos de cada PC (2026-11-27) -----------------------------------------------
//
// El operador: el principal «deberá tener más capacidad de recursos, RAM,
// disco». Cada latido trae lo que el PC midió de sí mismo; las cifras van en
// base 1024 y con coma, como `tamanoLegible` de `velocidad.ts`.

const GB = 1024 ** 3;
/** Con menos de esto libre en el disco, el PC va justo. */
const DISCO_JUSTO = 10 * GB;
/** Y con la RAM a este porcentaje o más. */
const RAM_JUSTA = 90;
/** Hasta un decimal, como el aviso de recursos del servicio: «12,4», «16». */
const HASTA_UN_DECIMAL = new Intl.NumberFormat('es-CO', { maximumFractionDigits: 1 });

/** Bytes en GB, como los dice el aviso del servicio («16 GB», «7,7 GB»): «12,4», «16». */
function gigas(bytes: number): string {
  return HASTA_UN_DECIMAL.format(bytes / GB);
}

/**
 * Lo libre del disco en GB, hacia abajo para no prometer lo que no hay: «120»;
 * por debajo de 10, con su decimal: «8,5».
 */
function gigasLibres(bytes: number): string {
  const gb = Math.max(0, bytes) / GB;
  return gb < 10 ? HASTA_UN_DECIMAL.format(Math.floor(gb * 10) / 10) : MILES.format(Math.floor(gb));
}

/**
 * Los recursos de un PC en trozos, en este orden: «12 núcleos», «RAM 12,4 /
 * 15,5 GB», «disco 120 GB libres» y «CPU 73 %». Lo que no se midió no sale.
 */
export function partesDeRecursos(recursos: RecursosDelEquipo | null | undefined): string[] {
  if (!recursos) return [];
  const partes: string[] = [];
  const nucleos = numero(recursos.nucleos);
  if (nucleos != null) partes.push(`${MILES.format(nucleos)} ${nucleos === 1 ? 'núcleo' : 'núcleos'}`);
  const usada = numero(recursos.memoria_usada);
  const total = numero(recursos.memoria_total);
  if (usada != null && total != null) partes.push(`RAM ${gigas(usada)} / ${gigas(total)} GB`);
  else if (total != null) partes.push(`RAM ${gigas(total)} GB`);
  else if (usada != null) partes.push(`RAM ${gigas(usada)} GB en uso`);
  const libre = numero(recursos.disco_libre);
  if (libre != null) partes.push(`disco ${gigasLibres(libre)} GB libres`);
  const cpu = numero(recursos.cpu);
  if (cpu != null) partes.push(`CPU ${MILES.format(cpu)} %`);
  return partes;
}

/** «12 núcleos · RAM 12,4 / 15,5 GB · disco 120 GB libres · CPU 73 %»; «—» si no midió nada. */
export function recursosDe(recursos: RecursosDelEquipo | null | undefined): string {
  const partes = partesDeRecursos(recursos);
  return partes.length ? partes.join(' · ') : '—';
}

/**
 * Por qué un PC va justo, en palabras: «La RAM está al 93 %.», «Quedan 8,5 GB
 * libres en el disco.» o las dos juntas; null si va holgado o no se sabe. Justo
 * es con la RAM al 90 % o más, o con menos de 10 GB libres en el disco.
 */
export function alertaDeRecursos(recursos: RecursosDelEquipo | null | undefined): string | null {
  if (!recursos) return null;
  const avisos: string[] = [];
  const usada = numero(recursos.memoria_usada);
  const total = numero(recursos.memoria_total);
  const porcentaje = usada != null && total != null && total > 0 ? (100 * usada) / total : null;
  // Hacia abajo, como lo libre del disco: un 89,9 % no se dice 90 %.
  if (porcentaje != null && porcentaje >= RAM_JUSTA) avisos.push(`la RAM está al ${Math.floor(porcentaje)} %`);
  const libre = numero(recursos.disco_libre);
  if (libre != null && libre < DISCO_JUSTO) avisos.push(`quedan ${gigasLibres(libre)} GB libres en el disco`);
  if (!avisos.length) return null;
  const frase = avisos.join(' y ');
  return `${frase[0].toUpperCase()}${frase.slice(1)}.`;
}

/** Si un PC va justo de RAM o de disco: su casilla de recursos se marca en la tabla. */
export function recursosEnAlerta(recursos: RecursosDelEquipo | null | undefined): boolean {
  return alertaDeRecursos(recursos) !== null;
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
 * «6 vivos · 18,3 PDF/min», con «1 caído» si lo hay: sólo los de esta corrida
 * que no se retiraron, y lo que procesan ahora, sumado, los vivos que ya lo
 * tienen. Hasta el 2026-11-27 decía «1.096 PDF/h».
 */
export function resumen(equipos: readonly EquipoDeLaCorrida[]): string {
  const enLaCorrida = equipos.filter((equipo) => esDeEstaCorrida(equipo) && !terminado(equipo));
  const vivos = enLaCorrida.filter((equipo) => equipo.vivo);
  const caidos = enLaCorrida.length - vivos.length;
  const ritmos = vivos.flatMap((equipo) => {
    const ahora = ahoraDe(equipo);
    return ahora == null ? [] : [ahora];
  });
  const partes = [`${vivos.length} ${vivos.length === 1 ? 'vivo' : 'vivos'}`];
  if (caidos) partes.push(`${caidos} ${caidos === 1 ? 'caído' : 'caídos'}`);
  if (ritmos.length) partes.push(porMinuto(ritmos.reduce((suma, valor) => suma + valor, 0)));
  return partes.join(' · ');
}

/** Una cifra de la fila de arriba: rótulo, valor y la nota de debajo. */
export interface LineaDeVelocidad {
  clave: 'ahora' | 'por-pc' | 'acumulado' | 'principal';
  rotulo: string;
  valor: string;
  nota: string | null;
}

/** El principal entre los equipos de la lista: por el id de la cabecera o, si no está, por su marca. */
function principalDe(datos: EquiposDeLaCorrida): EquipoDeLaCorrida | null {
  return (
    datos.equipos.find((equipo) => equipo.id === datos.principal) ??
    datos.equipos.find((equipo) => equipo.principal) ??
    null
  );
}

/**
 * La fila de cifras de la corrida compartida (2026-11-27): «Ahora: 18,4
 * PDF/min entre 6 PC», «Promedio por PC: 3,1 PDF/min», «Acumulado: 17,9
 * PDF/min» (con lo que toca a cada PC en la nota) y «Principal: SIAR
 * (ad21be)». Los totales y los promedios son del servicio (`velocidad`): aquí
 * sólo se dicen.
 *
 * Con `enVivo` falso -- la corrida terminada, la foto -- no hay «ahora»: sólo
 * lo acumulado y el principal, si se saben. Una corrida que va sola, o un
 * servicio anterior, no tiene fila.
 */
export function lineasDeVelocidad(datos: EquiposDeLaCorrida, enVivo = true): LineaDeVelocidad[] {
  if (!datos.compartida) return [];
  const lineas: LineaDeVelocidad[] = [];
  const velocidad = datos.velocidad;
  if (velocidad) {
    const activos = velocidad.pc_activos;
    // Sin cifra: o ninguno lleva sus 2 min (5 para la acumulada), o no queda ninguno.
    const sinCifra = activos > 0 ? 'midiendo…' : 'ningún PC activo';
    if (enVivo) {
      const total = numero(velocidad.actual.total);
      const porPc = numero(velocidad.actual.por_pc);
      // Entre cuántos se repartió de verdad: un PC recién unido todavía mide y
      // no entra en el promedio; dividir el total entre todos los activos no
      // cuadraba con «por PC» (2026-11-27).
      const conCifra = typeof velocidad.actual.pc === 'number' ? velocidad.actual.pc : activos;
      const midiendo = Math.max(0, activos - conCifra);
      let nota = conCifra === 1 ? 'en 1 PC' : `entre ${MILES.format(conCifra)} PC`;
      if (midiendo > 0) nota += ` (${MILES.format(midiendo)} midiendo)`;
      lineas.push({
        clave: 'ahora',
        rotulo: 'Ahora',
        valor: porMinuto(total),
        nota: total == null ? sinCifra : nota
      });
      lineas.push({
        clave: 'por-pc',
        rotulo: 'Ahora por PC',
        valor: porMinuto(porPc),
        nota: porPc == null ? sinCifra : 'lo que procesa cada PC ahora'
      });
    }
    const acumulado = numero(velocidad.acumulada.total);
    if (enVivo || acumulado != null) {
      const porPc = numero(velocidad.acumulada.por_pc);
      let nota = sinCifra;
      if (acumulado != null) {
        nota = porPc == null ? 'desde que se unió cada PC' : `${porMinuto(porPc)} por PC, desde que se unió cada uno`;
      }
      lineas.push({ clave: 'acumulado', rotulo: 'Acumulado', valor: porMinuto(acumulado), nota });
    }
  }
  if (datos.principal !== undefined) {
    const principal = principalDe(datos);
    const quien = principal ? rotuloDe(principal) : datos.principal;
    if (quien || enVivo) {
      // Sin principal con PC vivos: se están uniendo o todos tienen orden de
      // parar (el paso de «Parar todos con calma»); decir «ninguno vivo» engañaba.
      let nota = (velocidad?.pc_activos ?? 0) > 0 ? 'eligiendo… (se están uniendo o deteniendo)' : 'ninguno vivo ahora';
      if (quien) {
        nota = `${principal?.este ? 'es este equipo: ' : ''}escribe los Excel generales y cierra la corrida`;
      }
      lineas.push({ clave: 'principal', rotulo: 'Principal', valor: quien ?? '—', nota });
    }
  }
  return lineas;
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
