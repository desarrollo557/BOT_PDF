import { describe, expect, it } from 'vitest';
import {
  acumularEtapas,
  marcadasEnCinta,
  procedencia,
  reducirMuestras,
  restante,
  sumarConsumos,
  techo,
  velocidadMedia,
  type Muestra
} from './rendimiento';

function muestras(n: number): Muestra[] {
  return Array.from({ length: n }, (_, i) => ({
    t: i * 1000,
    paginas: i * 2,
    documentos: Math.floor(i / 10),
    velocidad: 2
  }));
}

describe('las muestras de la corrida', () => {
  it('no se tocan mientras caben', () => {
    const pocas = muestras(10);
    expect(reducirMuestras(pocas, 20)).toBe(pocas);
  });

  it('al llenarse se juntan de a dos sin perder el principio ni el final', () => {
    const todas = muestras(21);
    const reducidas = reducirMuestras(todas, 20);
    expect(reducidas.length).toBe(11);
    expect(reducidas[0].t).toBe(1000);
    expect(reducidas.at(-1)?.paginas).toBe(40);
  });
});

describe('las cifras de velocidad', () => {
  it('el eje se redondea a una cifra que se dice', () => {
    expect(techo(7.3)).toBe(8);
    expect(techo(140)).toBe(200);
    expect(techo(0)).toBe(1);
  });

  it('la media no existe antes del primer segundo', () => {
    expect(velocidadMedia(10, 0.5)).toBe(0);
    expect(velocidadMedia(120, 60)).toBe(2);
  });

  it('lo que falta usa la media cuando la velocidad de ahora es cero', () => {
    expect(restante(50, 100, 0, 2)).toBe(25);
    expect(restante(50, 100, 5, 2)).toBe(10);
    expect(restante(100, 100, 5, 2)).toBeNull();
    expect(restante(10, 0, 5, 2)).toBeNull();
    expect(restante(10, 100, 0, 0)).toBeNull();
  });
});

describe('la procedencia de las páginas', () => {
  it('suma varios documentos y respeta el orden de la cascada', () => {
    const partes = procedencia([
      { ocr_region: 3, text_layer: 10 },
      { text_layer: 5, none: 1 }
    ]);
    expect(partes.map((p) => [p.clave, p.valor])).toEqual([
      ['text_layer', 15],
      ['ocr_region', 3],
      ['none', 1]
    ]);
  });
});

describe('el tiempo por etapa', () => {
  it('cada etapa abierta suma su tiempo, y las terminadas no', () => {
    let tiempos = acumularEtapas({}, ['analysing', 'analysing', 'done'], 1);
    tiempos = acumularEtapas(tiempos, ['grouping'], 0.5);
    expect(tiempos).toEqual({ analysing: 2, grouping: 0.5 });
  });
});

it('cuenta las páginas marcadas en la cinta', () => {
  expect(marcadasEnCinta('ttxhx..')).toBe(2);
  expect(marcadasEnCinta(undefined)).toBe(0);
});

describe('el consumo de varios documentos', () => {
  const uno = {
    proveedores: {},
    peticiones: 2,
    paginas_facturadas: 3,
    tokens_entrada: 100,
    tokens_salida: 10,
    tokens_cache: 0,
    tokens: 110,
    rechazos: 0,
    fallos: 1,
    coste_estimado: 0.5,
    moneda: 'USD'
  };

  it('suma lo de todos y deja fuera a los que no usaron la IA', () => {
    const total = sumarConsumos([uno, null, { ...uno, peticiones: 0 }, uno]);
    expect(total?.peticiones).toBe(4);
    expect(total?.paginas_facturadas).toBe(6);
    expect(total?.coste_estimado).toBe(1);
  });

  it('sin precio en uno, no hay coste total', () => {
    expect(sumarConsumos([uno, { ...uno, coste_estimado: null }])?.coste_estimado).toBeNull();
  });

  it('sin nadie que la usara, no hay consumo', () => {
    expect(sumarConsumos([null, undefined])).toBeNull();
  });
});
