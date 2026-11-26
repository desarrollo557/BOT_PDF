/**
 * El monitoreo de los equipos de una corrida compartida (2026-11-26): el
 * operador pidió «un monitoreo para ver los que están conectados y poder
 * desconectarlos». Esto fija las palabras de cada estado, el ritmo y el
 * resumen, quién va aparte, a quién se le ofrece cada botón -- manda
 * `se_puede_parar` del servicio -- y las dos llamadas al servicio.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, equiposDeLaCorrida, pararEquipo, setIdentidad } from './api';
import {
  accionesDe,
  cifra,
  estadoDe,
  falloDeLaOrden,
  haceCuanto,
  idCorto,
  notaDeDetenida,
  notaDeParando,
  objetivosDePararTodos,
  porQueAparte,
  preguntaDeParar,
  preguntaDePararTodos,
  resumen,
  ritmo,
  rotuloDe,
  separar
} from './equipos';
import type { EquipoDeLaCorrida, EquiposDeLaCorrida } from './types';

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
    ...cambios
  };
}

/** Lo que contesta el servicio a una orden para un equipo que ya no late. */
const YA_NO_LATE =
  '«COORDINADORTIC-1e52b0» ya no late: sus PDF los toman los demás solos y su latido se borra a los 3 minutos.';

/** Los seis de la corrida de la mañana, con su ritmo medido (PDF/h). */
const LOS_SEIS = [
  equipo({ equipo: 'COORDINADORTIC', pdf_por_hora: 88 }),
  equipo({ equipo: 'SIAR', id: 'SIAR-6ad99c', pdf_por_hora: 122 }),
  equipo({ equipo: 'DESKTOP-UMCOEU8', pdf_por_hora: 154 }),
  equipo({ equipo: 'VISUALIZADOR', pdf_por_hora: 156 }),
  equipo({ equipo: 'DESARROLLADOR', id: 'DESARROLLADOR-fa12b8', pdf_por_hora: 177, este: true }),
  equipo({ equipo: 'SIAR', id: 'SIAR-ad21be', pdf_por_hora: 399 })
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

  it('el ritmo con el punto de miles, o una raya mientras no se sabe', () => {
    expect(ritmo(88.1)).toBe('88 PDF/h');
    expect(ritmo(1096.4)).toBe('1.096 PDF/h');
    expect(ritmo(null)).toBe('—');
    expect(cifra(12345)).toBe('12.345');
    expect(cifra(undefined)).toBe('—');
  });

  it('el arranque se lee aparte del nombre', () => {
    expect(idCorto(equipo())).toBe('1e52b0');
    expect(idCorto(equipo({ equipo: 'DESKTOP-UMCOEU8', id: 'DESKTOP-UMCOEU8-35cf6a' }))).toBe('35cf6a');
    expect(idCorto(equipo({ id: 'COORDINADORTIC' }))).toBe('');
    expect(rotuloDe(equipo())).toBe('COORDINADORTIC (1e52b0)');
  });
});

describe('el resumen de arriba', () => {
  it('«6 vivos · 1.096 PDF/h» con los seis de la mañana', () => {
    expect(resumen(LOS_SEIS)).toBe('6 vivos · 1.096 PDF/h');
  });

  it('cuenta los caídos aparte y su ritmo no suma', () => {
    const conUnCaido = [...LOS_SEIS, equipo({ equipo: 'VISUALIZADOR', id: 'VISUALIZADOR-84235e', vivo: false })];
    expect(resumen(conUnCaido)).toBe('6 vivos · 1 caído · 1.096 PDF/h');
  });

  it('sin ritmo todavía, sólo los vivos; los terminados y los de otra corrida no cuentan', () => {
    expect(
      resumen([
        equipo({ pdf_por_hora: null }),
        equipo({ equipo: 'SIAR', estado: 'terminado', vivo: false }),
        equipo({ equipo: 'ANALISSIG', de_esta_corrida: false })
      ])
    ).toBe('1 vivo');
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

const LISTA: EquiposDeLaCorrida = {
  compartida: true,
  corrida: '20261126-094756-d1057b',
  version: 'ddebddab810d',
  este: 'DESARROLLADOR-fa12b8',
  activa: true,
  equipos: LOS_SEIS
};

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
