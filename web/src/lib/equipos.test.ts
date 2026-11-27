/**
 * El monitoreo de los equipos de una corrida compartida (2026-11-26): el
 * operador pidió «un monitoreo para ver los que están conectados y poder
 * desconectarlos». Esto fija las palabras de cada estado, el ritmo y el
 * resumen, quién va aparte, a quién se le ofrece cada botón -- manda
 * `se_puede_parar` del servicio -- y las dos llamadas al servicio.
 *
 * Desde el 2026-11-27 (revisión 27), también la velocidad en PDF por minuto
 * con un decimal y la coma («1,5 PDF/min»; antes «88 PDF/h»), la fila de
 * cifras de arriba -- ahora, promedio por PC, acumulado y el principal --, que
 * con la corrida terminada no dice nada de «ahora», y los recursos de cada PC
 * con su aviso: la RAM al 90 % o más, o menos de 10 GB libres en el disco.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, equiposDeLaCorrida, pararEquipo, setIdentidad } from './api';
import {
  accionesDe,
  alertaDeRecursos,
  cifra,
  estadoDe,
  falloDeLaOrden,
  haceCuanto,
  idCorto,
  lineasDeVelocidad,
  type LineaDeVelocidad,
  notaDeDetenida,
  notaDeParando,
  objetivosDePararTodos,
  partesDeRecursos,
  porMinuto,
  porQueAparte,
  preguntaDeParar,
  preguntaDePararTodos,
  promedioDe,
  recursosDe,
  recursosEnAlerta,
  resumen,
  rotuloDe,
  separar
} from './equipos';
import type { EquipoDeLaCorrida, EquiposDeLaCorrida, RecursosDelEquipo, VelocidadDeLaCorrida } from './types';

function equipo(cambios: Partial<EquipoDeLaCorrida> = {}): EquipoDeLaCorrida {
  const nombre = cambios.equipo ?? 'COORDINADORTIC';
  return {
    id: `${nombre}-1e52b0`,
    equipo: nombre,
    version: 'ddebddab810d',
    misma_version: true,
    corrida: '20261126-094756-d1057b',
    de_esta_corrida: true,
    estado: 'procesando',
    vivo: true,
    este: false,
    hechos: 141,
    en_curso: 7,
    unido: '2026-11-26T09:48:00',
    escrito: '2026-11-26T11:24:00',
    quieto_hace: 4.2,
    pdf_por_hora: 88.1,
    orden: null,
    se_puede_parar: true,
    por_que_no: null,
    // Lo de la revisión 27 (2026-11-27): 141 entregados en 96 minutos.
    principal: false,
    entregados: 141,
    pdf_por_minuto: 1.47,
    pdf_por_minuto_promedio: 1.47,
    recursos: null,
    ...cambios
  };
}

/** El mismo equipo como lo daba un servicio anterior a la revisión 27: sin los campos nuevos. */
function deUnServicioAnterior(nuevo: EquipoDeLaCorrida): EquipoDeLaCorrida {
  const anterior = { ...nuevo };
  for (const campo of ['principal', 'entregados', 'pdf_por_minuto', 'pdf_por_minuto_promedio', 'recursos'] as const) {
    delete anterior[campo];
  }
  return anterior;
}

/** Lo que contesta el servicio a una orden para un equipo que ya no late. */
const YA_NO_LATE =
  '«COORDINADORTIC-1e52b0» ya no late: sus PDF los toman los demás solos y su latido se borra a los 3 minutos.';

/**
 * Los seis de la corrida de la mañana, con su ritmo medido: por hora, como lo
 * daba el servicio anterior (suman 1.096), y por minuto (suman 18,27). El
 * principal es el SIAR que lanzó primero.
 */
const LOS_SEIS = [
  equipo({ equipo: 'COORDINADORTIC', pdf_por_hora: 88, pdf_por_minuto: 1.47 }),
  equipo({ equipo: 'SIAR', id: 'SIAR-6ad99c', pdf_por_hora: 122, pdf_por_minuto: 2.03 }),
  equipo({ equipo: 'DESKTOP-UMCOEU8', pdf_por_hora: 154, pdf_por_minuto: 2.57 }),
  equipo({ equipo: 'VISUALIZADOR', pdf_por_hora: 156, pdf_por_minuto: 2.6 }),
  equipo({ equipo: 'DESARROLLADOR', id: 'DESARROLLADOR-fa12b8', pdf_por_hora: 177, pdf_por_minuto: 2.95, este: true }),
  equipo({ equipo: 'SIAR', id: 'SIAR-ad21be', pdf_por_hora: 399, pdf_por_minuto: 6.65, principal: true })
];

describe('el estado de cada equipo, en palabras', () => {
  it('procesando, uniéndose (con o sin tilde) y cerrando, con el punto en verde y latiendo', () => {
    expect(estadoDe(equipo())).toEqual({ etiqueta: 'Procesando', tono: 'good', latiendo: true, caido: false });
    expect(estadoDe(equipo({ estado: 'uniéndose' })).etiqueta).toBe('Uniéndose');
    expect(estadoDe(equipo({ estado: 'uniendose' })).etiqueta).toBe('Uniéndose');
    expect(estadoDe(equipo({ estado: 'cerrando' })).etiqueta).toBe('Cerrando la corrida');
  });

  it('parando con calma dice de quién es la orden; parando ya, sin más', () => {
    const calma = estadoDe(
      equipo({ orden: { modo: 'calma', por: 'SIAR-ad21be', equipo_que_ordena: 'SIAR', cuando: '2026-11-26T11:30:00' } })
    );
    expect(calma).toEqual({
      etiqueta: 'Parando con calma · orden de SIAR',
      tono: 'warn',
      latiendo: true,
      caido: false
    });
    expect(estadoDe(equipo({ orden: { modo: 'calma' } })).etiqueta).toBe('Parando con calma');
    expect(estadoDe(equipo({ orden: { modo: 'ya', equipo_que_ordena: 'SIAR' } })).etiqueta).toBe('Parando ya');
  });

  it('un caído dice desde cuándo no late, en rojo y sin latir', () => {
    expect(estadoDe(equipo({ vivo: false, quieto_hace: 185 }))).toEqual({
      etiqueta: 'Caído · sin latido hace 3 min',
      tono: 'bad',
      latiendo: false,
      caido: true
    });
    // Caído manda sobre la orden que tuviera: ya no la está cumpliendo.
    expect(estadoDe(equipo({ vivo: false, quieto_hace: null, orden: { modo: 'calma' } })).etiqueta).toBe('Caído');
  });

  it('terminado no es caído, aunque ya no lata', () => {
    expect(estadoDe(equipo({ estado: 'terminado', vivo: false }))).toEqual({
      etiqueta: 'Terminado',
      tono: 'good',
      latiendo: false,
      caido: false
    });
  });

  it('con la corrida terminada es la foto: lo que decía cada latido, sin «Caído» y sin latir', () => {
    // El servicio retirado da a todos por no vivos, y su último latido es de hace horas.
    expect(estadoDe(equipo({ vivo: false, quieto_hace: 3 * 3600 }), false)).toEqual({
      etiqueta: 'Procesando',
      tono: 'good',
      latiendo: false,
      caido: false
    });
    expect(
      estadoDe(equipo({ vivo: false, orden: { modo: 'calma', equipo_que_ordena: 'SIAR' } }), false)
    ).toEqual({ etiqueta: 'Parando con calma · orden de SIAR', tono: 'warn', latiendo: false, caido: false });
    expect(estadoDe(equipo({ estado: 'uniéndose', vivo: false }), false).latiendo).toBe(false);
    expect(estadoDe(equipo({ estado: 'terminado', vivo: false }), false).etiqueta).toBe('Terminado');
  });
});

describe('las cifras de la tabla', () => {
  it('«hace X» en segundos, minutos u horas, hacia abajo', () => {
    expect(haceCuanto(4.2)).toBe('hace 4 s');
    expect(haceCuanto(0)).toBe('hace 1 s');
    expect(haceCuanto(59.9)).toBe('hace 59 s');
    expect(haceCuanto(60)).toBe('hace 1 min');
    expect(haceCuanto(179)).toBe('hace 2 min');
    expect(haceCuanto(2 * 3600 + 5)).toBe('hace 2 h');
    expect(haceCuanto(null)).toBe('—');
    expect(haceCuanto(Number.NaN)).toBe('—');
  });

  it('la velocidad por minuto con un decimal y la coma, o una raya mientras no se sabe', () => {
    expect(porMinuto(1.5)).toBe('1,5 PDF/min');
    expect(porMinuto(3)).toBe('3,0 PDF/min');
    expect(porMinuto(18.27)).toBe('18,3 PDF/min');
    expect(porMinuto(1234.56)).toBe('1.234,6 PDF/min');
    expect(porMinuto(null)).toBe('—');
    expect(porMinuto(undefined)).toBe('—');
    expect(porMinuto(Number.NaN)).toBe('—');
    expect(cifra(12345)).toBe('12.345');
    expect(cifra(undefined)).toBe('—');
  });

  it('el promedio desde que se unió; con un servicio anterior, su ritmo por hora entre 60', () => {
    expect(promedioDe(equipo({ pdf_por_minuto_promedio: 2.98 }))).toBe(2.98);
    // Sus 5 primeros minutos: el null del servicio de hoy se queda en null.
    expect(promedioDe(equipo({ pdf_por_minuto_promedio: null, pdf_por_hora: 120 }))).toBeNull();
    const anterior = deUnServicioAnterior(equipo({ pdf_por_hora: 120 }));
    expect(promedioDe(anterior)).toBe(2);
    expect(porMinuto(promedioDe(anterior))).toBe('2,0 PDF/min');
    expect(promedioDe(deUnServicioAnterior(equipo({ pdf_por_hora: null })))).toBeNull();
  });

  it('el arranque se lee aparte del nombre', () => {
    expect(idCorto(equipo())).toBe('1e52b0');
    expect(idCorto(equipo({ equipo: 'DESKTOP-UMCOEU8', id: 'DESKTOP-UMCOEU8-35cf6a' }))).toBe('35cf6a');
    expect(idCorto(equipo({ id: 'COORDINADORTIC' }))).toBe('');
    expect(rotuloDe(equipo())).toBe('COORDINADORTIC (1e52b0)');
  });
});

describe('el resumen de arriba', () => {
  it('«6 vivos · 18,3 PDF/min» con los seis de la mañana', () => {
    expect(resumen(LOS_SEIS)).toBe('6 vivos · 18,3 PDF/min');
  });

  it('cuenta los caídos aparte y su velocidad no suma', () => {
    const conUnCaido = [...LOS_SEIS, equipo({ equipo: 'VISUALIZADOR', id: 'VISUALIZADOR-84235e', vivo: false })];
    expect(resumen(conUnCaido)).toBe('6 vivos · 1 caído · 18,3 PDF/min');
  });

  it('sin velocidad todavía, sólo los vivos; los terminados y los de otra corrida no cuentan', () => {
    expect(
      resumen([
        equipo({ pdf_por_minuto: null, pdf_por_hora: null }),
        equipo({ equipo: 'SIAR', estado: 'terminado', vivo: false }),
        equipo({ equipo: 'ANALISSIG', de_esta_corrida: false })
      ])
    ).toBe('1 vivo');
  });

  it('con un servicio anterior, que no la da por minuto, su ritmo por hora entre 60', () => {
    // Los 1.096 PDF/h de la mañana son 18,3 PDF/min.
    expect(resumen(LOS_SEIS.map(deUnServicioAnterior))).toBe('6 vivos · 18,3 PDF/min');
    // Un null del servicio de hoy es «todavía no»: no se rellena con el ritmo por hora.
    expect(resumen([equipo({ pdf_por_minuto: null, pdf_por_hora: 120 })])).toBe('1 vivo');
  });
});

const GB = 1024 ** 3;

/** Nada medido: así llega lo que el PC no pudo medir. */
const NADA: RecursosDelEquipo = {
  nucleos: null,
  cpu: null,
  carga: null,
  memoria_usada: null,
  memoria_total: null,
  disco_libre: null,
  disco_total: null,
  disco: null
};

/** Un PC holgado: 12 núcleos, la RAM que ve Docker y el C: del equipo. */
const HOLGADO: RecursosDelEquipo = {
  nucleos: 12,
  cpu: 72.6,
  carga: 11.5,
  memoria_usada: 12.4 * GB,
  memoria_total: 15.5 * GB,
  disco_libre: 120.7 * GB,
  disco_total: 476 * GB,
  disco: '/equipo/c'
};

describe('los recursos de cada PC', () => {
  it('en una línea: núcleos, RAM, disco libre y CPU, en GB y con la coma', () => {
    expect(recursosDe(HOLGADO)).toBe('12 núcleos · RAM 12,4 / 15,5 GB · disco 120 GB libres · CPU 73 %');
    expect(partesDeRecursos(HOLGADO)).toEqual([
      '12 núcleos',
      'RAM 12,4 / 15,5 GB',
      'disco 120 GB libres',
      'CPU 73 %'
    ]);
  });

  it('lo que no se midió no sale; sin nada, una raya', () => {
    expect(recursosDe({ ...HOLGADO, nucleos: 1, memoria_usada: null, disco_libre: null, cpu: null })).toBe(
      '1 núcleo · RAM 15,5 GB'
    );
    expect(recursosDe({ ...HOLGADO, nucleos: null, memoria_total: null, cpu: null })).toBe(
      'RAM 12,4 GB en uso · disco 120 GB libres'
    );
    expect(recursosDe(NADA)).toBe('—');
    expect(partesDeRecursos(NADA)).toEqual([]);
    expect(recursosDe(null)).toBe('—');
    expect(recursosDe(undefined)).toBe('—');
  });

  it('lo libre del disco, hacia abajo: con un decimal por debajo de 10 GB y con el punto de miles', () => {
    expect(recursosDe({ ...NADA, disco_libre: 8.57 * GB })).toBe('disco 8,5 GB libres');
    expect(recursosDe({ ...NADA, disco_libre: 1536.9 * GB })).toBe('disco 1.536 GB libres');
  });

  it('los GB sin «,0», como el aviso del servicio: «16 GB», no «16,0 GB»', () => {
    expect(recursosDe({ ...NADA, memoria_usada: 12 * GB, memoria_total: 16 * GB })).toBe('RAM 12 / 16 GB');
    expect(recursosDe({ ...NADA, memoria_usada: 6.1 * GB, memoria_total: 7.7 * GB })).toBe('RAM 6,1 / 7,7 GB');
    expect(recursosDe({ ...NADA, disco_libre: 8 * GB })).toBe('disco 8 GB libres');
  });

  it('justo de RAM (90 % o más) o de disco (menos de 10 GB libres): se marca y se dice por qué', () => {
    expect(recursosEnAlerta(HOLGADO)).toBe(false);
    expect(alertaDeRecursos(HOLGADO)).toBeNull();

    const sinRam = { ...HOLGADO, memoria_usada: 14.5 * GB };
    expect(recursosEnAlerta(sinRam)).toBe(true);
    expect(alertaDeRecursos(sinRam)).toBe('La RAM está al 93 %.');
    expect(alertaDeRecursos({ ...HOLGADO, memoria_usada: 9 * GB, memoria_total: 10 * GB })).toBe(
      'La RAM está al 90 %.'
    );
    expect(recursosEnAlerta({ ...HOLGADO, memoria_usada: 8.99 * GB, memoria_total: 10 * GB })).toBe(false);

    // Hacia abajo, como se pinta: 9,96 GB libres son «9,9», no «10».
    expect(alertaDeRecursos({ ...HOLGADO, disco_libre: 9.96 * GB })).toBe('Quedan 9,9 GB libres en el disco.');
    expect(recursosEnAlerta({ ...HOLGADO, disco_libre: 10 * GB })).toBe(false);
    expect(alertaDeRecursos({ ...sinRam, disco_libre: 8.5 * GB })).toBe(
      'La RAM está al 93 % y quedan 8,5 GB libres en el disco.'
    );

    // Sin el total de la RAM no hay porcentaje: no se avisa de lo que no se sabe.
    expect(recursosEnAlerta({ ...sinRam, memoria_total: null })).toBe(false);
    expect(recursosEnAlerta(NADA)).toBe(false);
    expect(recursosEnAlerta(null)).toBe(false);
  });
});

describe('quién va aparte y en qué orden', () => {
  it('los de otra corrida o versión van aparte, con su porqué', () => {
    const otraCorrida = equipo({ equipo: 'ANALISSIG', de_esta_corrida: false });
    const otraVersion = equipo({ equipo: 'VIEJO', misma_version: false });
    const { deEsta, otros } = separar([otraCorrida, equipo(), otraVersion]);
    expect(deEsta.map((e) => e.equipo)).toEqual(['COORDINADORTIC']);
    // Como en el servicio, el que dice ser de esta corrida va antes.
    expect(otros.map((e) => e.equipo)).toEqual(['VIEJO', 'ANALISSIG']);
    expect(porQueAparte(otraCorrida)).toBe('otra corrida');
    expect(porQueAparte(otraVersion)).toBe('otra versión del bot');
    expect(porQueAparte(equipo())).toBeNull();
  });

  it('el orden del servicio: vivos primero, este primero entre ellos, luego por nombre y por id', () => {
    const { deEsta } = separar([
      equipo({ equipo: 'ZETA', vivo: false }),
      equipo({ equipo: 'BETA' }),
      equipo({ equipo: 'SIAR', id: 'SIAR-b' }),
      equipo({ equipo: 'SIAR', id: 'SIAR-a' }),
      equipo({ equipo: 'analissig' }),
      equipo({ equipo: 'YO', este: true })
    ]);
    // El nombre, sin mirar mayúsculas, como el `casefold` del servicio.
    expect(deEsta.map((e) => e.id)).toEqual([
      'YO-1e52b0',
      'analissig-1e52b0',
      'BETA-1e52b0',
      'SIAR-a',
      'SIAR-b',
      'ZETA-1e52b0'
    ]);
  });
});

describe('a quién se le ofrece parar (manda el servicio)', () => {
  it('con se_puede_parar, los dos botones', () => {
    expect(accionesDe(equipo(), true)).toEqual({ calma: true, ya: true, porQueNo: null });
  });

  it('sin él, ninguno, y el porqué del servicio', () => {
    const cerrando = equipo({
      estado: 'cerrando',
      se_puede_parar: false,
      por_que_no: '«COORDINADORTIC-1e52b0» está cerrando la corrida: termina solo en unos minutos.'
    });
    expect(accionesDe(cerrando, true)).toEqual({
      calma: false,
      ya: false,
      porQueNo: '«COORDINADORTIC-1e52b0» está cerrando la corrida: termina solo en unos minutos.'
    });
  });

  it('con una orden de calma ya dada sólo queda «ya»; con «ya», nada', () => {
    expect(accionesDe(equipo({ orden: { modo: 'calma' } }), true)).toEqual({ calma: false, ya: true, porQueNo: null });
    expect(accionesDe(equipo({ orden: { modo: 'ya' } }), true).ya).toBe(false);
  });

  it('ni los de otra corrida ni nadie con la corrida terminada, aunque el servicio dijera que sí', () => {
    expect(accionesDe(equipo({ de_esta_corrida: false }), true).calma).toBe(false);
    expect(accionesDe(equipo(), false)).toEqual({ calma: false, ya: false, porQueNo: 'La corrida ya terminó.' });
  });

  it('«Parar todos con calma» va a los que se puede, con este equipo al final', () => {
    const objetivos = objetivosDePararTodos(
      [
        ...LOS_SEIS,
        equipo({ equipo: 'CAIDO', vivo: false, se_puede_parar: false, por_que_no: 'ya no late' }),
        equipo({ equipo: 'PARANDO', orden: { modo: 'calma' } }),
        equipo({ equipo: 'ANALISSIG', de_esta_corrida: false })
      ],
      true
    );
    expect(objetivos.map((e) => e.id)).toEqual([
      'COORDINADORTIC-1e52b0',
      'DESKTOP-UMCOEU8-1e52b0',
      'SIAR-6ad99c',
      'SIAR-ad21be',
      'VISUALIZADOR-1e52b0',
      'DESARROLLADOR-fa12b8'
    ]);
    expect(objetivosDePararTodos(LOS_SEIS, false)).toEqual([]);
  });

  it('el que se está uniendo va con los de esta corrida, dice «Uniéndose» y se le puede parar', () => {
    // Todavía late sin corrida: el servicio lo cuenta como posible miembro de ésta.
    const entrante = equipo({
      equipo: 'ENTRANTE',
      corrida: null,
      estado: 'uniéndose',
      hechos: 0,
      en_curso: 0,
      unido: null,
      pdf_por_hora: null
    });
    const { deEsta, otros } = separar([...LOS_SEIS, entrante]);
    expect(deEsta).toContain(entrante);
    expect(otros).toEqual([]);
    expect(porQueAparte(entrante)).toBeNull();
    expect(estadoDe(entrante).etiqueta).toBe('Uniéndose');
    expect(accionesDe(entrante, true)).toEqual({ calma: true, ya: true, porQueNo: null });
    expect(objetivosDePararTodos(deEsta, true).map((e) => e.id)).toContain('ENTRANTE-1e52b0');
  });
});

describe('las confirmaciones', () => {
  it('«Parar ya» va en rojo y avisa que otro equipo lo relee y puede pagarse otra vez', () => {
    const pregunta = preguntaDeParar(LOS_SEIS[0], 'ya', LOS_SEIS);
    expect(pregunta.titulo).toBe('¿Parar ya COORDINADORTIC?');
    expect(pregunta.peligro).toBe(true);
    expect(pregunta.mensaje).toContain('lo vuelve a leer otro equipo');
    expect(pregunta.mensaje).toContain('puede pagarse otra vez');
  });

  it('«Parar con calma» no es de peligro, y dice quién sigue con lo que falta', () => {
    const pregunta = preguntaDeParar(LOS_SEIS[4], 'calma', LOS_SEIS);
    expect(pregunta.titulo).toBe('¿Parar con calma este equipo (DESARROLLADOR)?');
    expect(pregunta.peligro).toBeUndefined();
    expect(pregunta.mensaje).toContain('lo siguen los demás equipos');
    // El último que queda: lo que falta espera a que se vuelva a lanzar.
    expect(preguntaDeParar(LOS_SEIS[4], 'calma', [LOS_SEIS[4]]).mensaje).toContain('vuelva a lanzar la carpeta');
  });

  it('dos PC con el mismo nombre se distinguen por su arranque', () => {
    expect(preguntaDeParar(LOS_SEIS[1], 'calma', LOS_SEIS).titulo).toBe('¿Parar con calma SIAR (6ad99c)?');
  });

  it('«Parar todos» dice a cuántos, este incluido, y qué pasa con lo que nadie tomó', () => {
    const pregunta = preguntaDePararTodos(objetivosDePararTodos(LOS_SEIS, true));
    expect(pregunta.titulo).toBe('¿Parar con calma los 6 equipos de la corrida?');
    expect(pregunta.mensaje).toContain('Son 6 equipos, este incluido:');
    // Los dos «SIAR» de la mañana eran dos PC: cada uno con su arranque.
    expect(pregunta.mensaje).toContain(
      'COORDINADORTIC, DESKTOP-UMCOEU8, SIAR (6ad99c), SIAR (ad21be), VISUALIZADOR y DESARROLLADOR (este)'
    );
    expect(pregunta.mensaje).toContain('termina lo que está leyendo, lo entrega y se retira');
    expect(pregunta.mensaje).toContain('queda para cuando se vuelva a lanzar la carpeta');
    // Con los demás ya parando, queda uno: es el que falta.
    const uno = preguntaDePararTodos([LOS_SEIS[4]]);
    expect(uno.titulo).toBe('¿Parar con calma el único equipo que falta?');
    expect(uno.mensaje).toMatch(/^Es este equipo \(DESARROLLADOR\)\. Termina lo que está leyendo/);
  });

  it('el fallo de una orden lleva el nombre del equipo si el servicio no lo dice', () => {
    expect(falloDeLaOrden(LOS_SEIS[0], 'Ese equipo no está en esta corrida.')).toBe(
      'COORDINADORTIC: Ese equipo no está en esta corrida.'
    );
    expect(falloDeLaOrden(LOS_SEIS[0], YA_NO_LATE)).toBe(YA_NO_LATE);
  });
});

describe('las notas de la corrida que para', () => {
  it('mientras para, de quién es la orden y qué hace', () => {
    expect(notaDeParando({ modo: 'calma', equipo_que_ordena: 'SIAR' })).toBe(
      'Parando con calma por orden de SIAR: termina lo que está leyendo, lo entrega y se retira.'
    );
    expect(notaDeParando(null)).toBeNull();
  });

  it('ya detenida, quién la detuvo y cómo, con la frase que completa el servicio', () => {
    expect(notaDeDetenida('el equipo SIAR (operador Juan), con «Parar con calma»')).toBe(
      'Detenido por el equipo SIAR (operador Juan), con «Parar con calma».'
    );
    expect(notaDeDetenida('el equipo SIAR, con «Parar ya».')).toBe('Detenido por el equipo SIAR, con «Parar ya».');
    expect(notaDeDetenida(null)).toBeNull();
    expect(notaDeDetenida('  ')).toBeNull();
  });
});

function json(status: number, cuerpo: unknown): Response {
  return new Response(JSON.stringify(cuerpo), { status, headers: { 'content-type': 'application/json' } });
}

/** Sin ninguna velocidad todavía. */
const SIN_VELOCIDAD: VelocidadDeLaCorrida = {
  pc_activos: 0,
  actual: { total: null, por_pc: null },
  acumulada: { total: null, por_pc: null }
};

/**
 * Lo que contesta el servicio (revisión 27) con los seis de la mañana. Las
 * cifras de `velocidad` son las del ejemplo del contrato: las suma el servicio,
 * no la pantalla.
 */
const LISTA: EquiposDeLaCorrida = {
  compartida: true,
  corrida: '20261126-094756-d1057b',
  version: 'ddebddab810d',
  este: 'DESARROLLADOR-fa12b8',
  activa: true,
  principal: 'SIAR-ad21be',
  velocidad: {
    pc_activos: 6,
    actual: { total: 18.4, por_pc: 3.07 },
    acumulada: { total: 17.9, por_pc: 2.98 }
  },
  aviso_de_recursos:
    'El principal SIAR (ad21be) tiene menos RAM (8 GB) que COORDINADORTIC (16 GB): conviene lanzar primero en el PC con más recursos.',
  equipos: LOS_SEIS
};

/** Lo que contesta para una corrida que va sola. */
const SOLA: EquiposDeLaCorrida = {
  compartida: false,
  corrida: null,
  version: 'ddebddab810d',
  este: null,
  activa: true,
  principal: null,
  velocidad: SIN_VELOCIDAD,
  aviso_de_recursos: null,
  equipos: []
};

function cifraDe(lineas: LineaDeVelocidad[], clave: LineaDeVelocidad['clave']): LineaDeVelocidad | undefined {
  return lineas.find((linea) => linea.clave === clave);
}

describe('la fila de cifras de arriba (2026-11-27)', () => {
  it('ahora entre los PC activos, el promedio por PC, lo acumulado y el principal', () => {
    expect(lineasDeVelocidad(LISTA)).toEqual([
      { clave: 'ahora', rotulo: 'Ahora', valor: '18,4 PDF/min', nota: 'entre 6 PC' },
      { clave: 'por-pc', rotulo: 'Ahora por PC', valor: '3,1 PDF/min', nota: 'lo que procesa cada PC ahora' },
      {
        clave: 'acumulado',
        rotulo: 'Acumulado',
        valor: '17,9 PDF/min',
        nota: '3,0 PDF/min por PC, desde que se unió cada uno'
      },
      {
        clave: 'principal',
        rotulo: 'Principal',
        valor: 'SIAR (ad21be)',
        nota: 'escribe los Excel generales y cierra la corrida'
      }
    ]);
  });

  it('el principal que es este equipo lo dice; sin principal, una raya mientras la corrida sigue', () => {
    expect(cifraDe(lineasDeVelocidad({ ...LISTA, principal: 'DESARROLLADOR-fa12b8' }), 'principal')).toEqual({
      clave: 'principal',
      rotulo: 'Principal',
      valor: 'DESARROLLADOR (fa12b8)',
      nota: 'es este equipo: escribe los Excel generales y cierra la corrida'
    });
    // Si la cabecera no lo trae, vale la marca de su fila.
    expect(cifraDe(lineasDeVelocidad({ ...LISTA, principal: null }), 'principal')?.valor).toBe('SIAR (ad21be)');
    const sinPrincipal = { ...LISTA, principal: null, equipos: LOS_SEIS.map((e) => ({ ...e, principal: false })) };
    expect(cifraDe(lineasDeVelocidad(sinPrincipal), 'principal')).toEqual({
      clave: 'principal',
      rotulo: 'Principal',
      valor: '—',
      nota: 'eligiendo… (se están uniendo o deteniendo)'
    });
    // Sin nadie activo, sí: ninguno vivo.
    const sinNadie = { ...sinPrincipal, velocidad: SIN_VELOCIDAD };
    expect(cifraDe(lineasDeVelocidad(sinNadie), 'principal')?.nota).toBe('ninguno vivo ahora');
  });

  it('mientras ninguno lleva sus primeros minutos, «midiendo…»; en 1 PC, «en 1 PC»', () => {
    const midiendo = lineasDeVelocidad({ ...LISTA, velocidad: { ...SIN_VELOCIDAD, pc_activos: 3 } });
    expect(midiendo.slice(0, 3).map((linea) => [linea.valor, linea.nota])).toEqual([
      ['—', 'midiendo…'],
      ['—', 'midiendo…'],
      ['—', 'midiendo…']
    ]);
    expect(cifraDe(lineasDeVelocidad({ ...LISTA, velocidad: SIN_VELOCIDAD }), 'ahora')?.nota).toBe('ningún PC activo');
    const uno = lineasDeVelocidad({
      ...LISTA,
      velocidad: { pc_activos: 1, actual: { total: 2.5, por_pc: 2.5 }, acumulada: { total: 2.4, por_pc: null } }
    });
    expect(cifraDe(uno, 'ahora')).toEqual({ clave: 'ahora', rotulo: 'Ahora', valor: '2,5 PDF/min', nota: 'en 1 PC' });
    expect(cifraDe(uno, 'acumulado')?.nota).toBe('desde que se unió cada PC');
  });

  it('el total se reparte entre los PC con cifra y dice cuántos siguen midiendo', () => {
    const tres = lineasDeVelocidad({
      ...LISTA,
      velocidad: {
        pc_activos: 3,
        actual: { total: 6, por_pc: 3, pc: 2 },
        acumulada: { total: 2.98, por_pc: 2.98, pc: 1 }
      }
    });
    expect(cifraDe(tres, 'ahora')?.nota).toBe('entre 2 PC (1 midiendo)');
    expect(cifraDe(tres, 'por-pc')?.valor).toBe('3,0 PDF/min');
  });

  it('con la corrida terminada no hay «ahora»: sólo lo acumulado y el principal, si se saben', () => {
    expect(lineasDeVelocidad(LISTA, false).map((linea) => linea.clave)).toEqual(['acumulado', 'principal']);
    // El servicio retirado da a todos por no vivos: sin cifras ni principal, no queda fila.
    const retirada = {
      ...LISTA,
      activa: false,
      principal: null,
      velocidad: SIN_VELOCIDAD,
      equipos: LOS_SEIS.map((e) => ({ ...e, vivo: false, principal: false }))
    };
    expect(lineasDeVelocidad(retirada, false)).toEqual([]);
  });

  it('una corrida que va sola, o un servicio anterior, no tiene fila', () => {
    expect(lineasDeVelocidad(SOLA)).toEqual([]);
    expect(lineasDeVelocidad({ ...LISTA, principal: undefined, velocidad: undefined })).toEqual([]);
  });
});

describe('las llamadas al servicio', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setIdentidad(null);
  });

  it('pide la lista de la corrida, con su id escapado', async () => {
    const fetch = vi.fn(async (_url: string) => json(200, LISTA));
    vi.stubGlobal('fetch', fetch);
    expect(await equiposDeLaCorrida('20261126/x y')).toEqual(LISTA);
    expect(fetch.mock.calls[0][0]).toBe('/api/folder-runs/20261126%2Fx%20y/equipos');
  });

  it('ordena parar con el modo en el cuerpo, la cédula de quien ordena y los ids escapados', async () => {
    const fetch = vi.fn(async (_url: string, _init?: RequestInit) => json(200, LISTA));
    vi.stubGlobal('fetch', fetch);
    setIdentidad('1047000000');
    expect(await pararEquipo('corrida-1', 'DESKTOP UMCOEU8-35cf6a', 'calma')).toEqual(LISTA);
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe('/api/folder-runs/corrida-1/equipos/DESKTOP%20UMCOEU8-35cf6a/parar');
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual({ modo: 'calma' });
    expect((init?.headers as Record<string, string>)['X-Cedula']).toBe('1047000000');
  });

  it('un rechazo llega con la frase del servicio', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(409, { detail: YA_NO_LATE })));
    const fallo = await pararEquipo('corrida-1', 'COORDINADORTIC-1e52b0', 'ya').catch((error) => error);
    expect(fallo).toBeInstanceOf(ApiError);
    expect(fallo.message).toBe(YA_NO_LATE);
    vi.stubGlobal('fetch', vi.fn(async () => json(404, { detail: 'Ese equipo no está en esta corrida.' })));
    await expect(equiposDeLaCorrida('corrida-1')).rejects.toThrow('Ese equipo no está en esta corrida.');
  });
});
