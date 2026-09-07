import { describe, expect, it } from 'vitest';
import { oracleOptions, reasonFor, type OracleChoice } from './oracles';
import type { Health } from './api';

/**
 * Qué modelos puede ofrecer la pantalla, y cuáles tiene que negarse a ofrecer.
 *
 * El servicio rechaza con 422 una elección sin llave, así que nada de lo que
 * pase acá puede producir un corte equivocado. Lo que está en juego es peor de
 * otra manera: ofrecer un modelo que no se puede pedir gasta la decisión del
 * operador y la contesta con un error después de que ya eligió el archivo.
 *
 * Y el caso que importa de verdad es el del servicio que no contesta o que es
 * más viejo que esta pantalla. Ahí no se sabe qué llaves hay, y no saber no es
 * lo mismo que no haber: se ofrece el automático, que siempre se puede pedir, y
 * se dice por qué los demás están apagados.
 */

const salud = (parcial: Partial<Health> = {}): Health =>
  ({
    status: 'ok',
    api_revision: 17,
    features: ['oracle-choice', 'segment-task'],
    document_workers: 3,
    page_workers: 8,
    vision: 'disabled',
    queued: 0,
    queue_limit: 10000,
    ...parcial
  }) as Health;

const buscar = (opciones: ReturnType<typeof oracleOptions>, id: OracleChoice) => {
  const opcion = opciones.find((candidate) => candidate.id === id);
  if (!opcion) throw new Error(`falta la opción ${id}`);
  return opcion;
};

describe('lo que la pantalla ofrece', () => {
  it('nombra los cuatro caminos, siempre en el mismo orden', () => {
    expect(oracleOptions(salud()).map((option) => option.id)).toEqual([
      'auto',
      'claude',
      'gemini',
      'mistral'
    ]);
  });

  it('habilita el modelo cuyo llave el servicio declara', () => {
    const opciones = oracleOptions(
      salud({ oracles: { auto: true, claude: false, gemini: true, mistral: false } })
    );
    expect(buscar(opciones, 'gemini').available).toBe(true);
    expect(buscar(opciones, 'claude').available).toBe(false);
  });

  it('el automático se puede pedir siempre', () => {
    const opciones = oracleOptions(
      salud({ oracles: { auto: true, claude: false, gemini: false, mistral: false } })
    );
    expect(buscar(opciones, 'auto').available).toBe(true);
    expect(buscar(opciones, 'auto').reason).toBeNull();
  });

  it('un modelo apagado dice por qué', () => {
    const opciones = oracleOptions(
      salud({ oracles: { auto: true, claude: false, gemini: true, mistral: false } })
    );
    expect(buscar(opciones, 'mistral').reason).toMatch(/llave/i);
  });

  it('un modelo disponible no arrastra ninguna excusa', () => {
    const opciones = oracleOptions(
      salud({ oracles: { auto: true, claude: true, gemini: true, mistral: true } })
    );
    for (const opcion of opciones) {
      expect(opcion.reason).toBeNull();
    }
  });

  it('cada modelo trae una etiqueta y una pista', () => {
    for (const opcion of oracleOptions(salud())) {
      expect(opcion.label.length).toBeGreaterThan(0);
      expect(opcion.hint.length).toBeGreaterThan(0);
    }
  });
});

describe('cuando no se sabe qué hay del otro lado', () => {
  it('sin conexión sólo queda el automático', () => {
    const opciones = oracleOptions(null);
    expect(buscar(opciones, 'auto').available).toBe(true);
    expect(buscar(opciones, 'claude').available).toBe(false);
  });

  it('sin conexión lo dice, en vez de apagar sin explicar', () => {
    expect(buscar(oracleOptions(null), 'gemini').reason).toMatch(/servicio/i);
  });

  it('un servicio viejo no declara los modelos y no se le inventan', () => {
    const opciones = oracleOptions(salud({ api_revision: 16, features: [] }));
    expect(buscar(opciones, 'mistral').available).toBe(false);
    expect(buscar(opciones, 'mistral').reason).toMatch(/servicio/i);
  });

  it('un servicio viejo igual deja separar por el automático', () => {
    const opciones = oracleOptions(salud({ api_revision: 16, features: [] }));
    expect(buscar(opciones, 'auto').available).toBe(true);
  });
});

describe('por qué no se puede pedir lo que está elegido', () => {
  const opciones = oracleOptions(
    salud({ oracles: { auto: true, claude: false, gemini: true, mistral: false } })
  );

  it('lo elegido y disponible no tiene nada que explicar', () => {
    expect(reasonFor('gemini', opciones)).toBeNull();
  });

  it('lo elegido y apagado explica por qué', () => {
    expect(reasonFor('claude', opciones)).toMatch(/llave/i);
  });

  it('el automático nunca bloquea una carga', () => {
    expect(reasonFor('auto', opciones)).toBeNull();
  });
});
