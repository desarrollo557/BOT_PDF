import { describe, expect, it } from 'vitest';
import type { DescargaDeRed, RedDeLaCorrida } from './types';
import {
  avanceDeLaDescarga,
  bajandoDeLaRed,
  faltaCorta,
  lado,
  loQueFalta,
  resumenDeLasDescargas,
  tamanoLegible,
  vaPorLaRed
} from './velocidad';

function red(cambios: Partial<RedDeLaCorrida> = {}): RedDeLaCorrida {
  return {
    origen: { acceso: 'red', mb_s: 4.2, velocidad: '4,2 MB/s' },
    destino: { acceso: 'local', mb_s: 110, velocidad: '110 MB/s' },
    prueba: { estado: 'hecha' },
    falta_s: 11_400,
    falta: '3 h 10 min',
    red_s: 2_400,
    falta_red: '40 min',
    al_menos: false,
    ...cambios
  };
}

describe('la red de la corrida', () => {
  it('dice el acceso y la velocidad de cada lado', () => {
    expect(lado(red().origen, false)).toBe('Red · 4,2 MB/s');
    expect(lado(red().destino, false)).toBe('Local · 110 MB/s');
  });

  it('mientras mide, lo dice', () => {
    expect(lado({ acceso: 'red', mb_s: null, velocidad: '—' }, true)).toBe('Red · midiendo…');
    expect(lado({ acceso: null, mb_s: null, velocidad: '—' }, false)).toBe('—');
  });

  it('lo que falta, con la parte de la red', () => {
    expect(loQueFalta(red())).toBe('Falta ~3 h 10 min (la red, ~40 min)');
    expect(loQueFalta(red({ al_menos: true, red_s: null }))).toBe('Falta al menos ~3 h 10 min');
  });

  it('«menos de 1 min» va sin la tilde (salía «~menos de 1 min», 2026-11-09)', () => {
    expect(loQueFalta(red({ falta_s: null, falta: '—', falta_red: 'menos de 1 min' }))).toBe(
      'Mover lo que queda por la red: menos de 1 min'
    );
    expect(loQueFalta(red({ falta: 'menos de 1 min', falta_red: 'menos de 1 min' }))).toBe(
      'Falta menos de 1 min (la red, menos de 1 min)'
    );
  });

  it('sin ritmo aún, sólo lo de la red; terminada, nada', () => {
    expect(loQueFalta(red({ falta_s: null, falta: '—' }))).toBe('Mover lo que queda por la red: ~40 min');
    expect(loQueFalta(red({ falta_s: null, red_s: null }))).toBeNull();
    expect(loQueFalta(red({ falta_s: 0 }))).toBeNull();
  });

  it('se resalta si algún lado va por la red', () => {
    expect(vaPorLaRed(red())).toBe(true);
    expect(
      vaPorLaRed(red({ origen: { acceso: 'local', mb_s: 1, velocidad: '1,0 MB/s' } }))
    ).toBe(false);
  });
});

const MB = 1024 * 1024;

function descarga(cambios: Partial<DescargaDeRed> = {}): DescargaDeRed {
  return {
    estado: 'bajando',
    bytes: 123 * MB,
    total: 410 * MB,
    mb_s: 3.5,
    velocidad: '3,5 MB/s',
    falta_s: 82,
    intento: 1,
    ...cambios
  };
}

describe('la descarga de un PDF de la red (2026-11-09)', () => {
  it('dice lo bajado, el tamaño, el porcentaje, la velocidad y lo que falta', () => {
    expect(bajandoDeLaRed(descarga())).toBe(
      'Bajando de la red · 123 / 410 MB · 30 % · 3,5 MB/s · falta ~1 min'
    );
    expect(avanceDeLaDescarga(descarga())).toBe(30);
  });

  it('esperando turno dice el tamaño y la barra va sin porcentaje', () => {
    const esperando = descarga({ estado: 'esperando', bytes: 0, mb_s: null, velocidad: '', falta_s: null });
    expect(bajandoDeLaRed(esperando)).toBe('Esperando turno para bajar de la red · 410 MB');
    expect(avanceDeLaDescarga(esperando)).toBeNull();
  });

  it('sin tamaño, lo bajado sin porcentaje; sin medir, sin velocidad ni lo que falta', () => {
    const sinTamano = descarga({ total: 0, falta_s: null });
    expect(bajandoDeLaRed(sinTamano)).toBe('Bajando de la red · 123 MB · 3,5 MB/s');
    expect(avanceDeLaDescarga(sinTamano)).toBeNull();
    expect(bajandoDeLaRed(descarga({ bytes: 0, mb_s: null, velocidad: '', falta_s: null }))).toBe(
      'Bajando de la red · 0 KB / 410 MB · 0 %'
    );
  });

  it('nunca dice 100 antes de acabar, ni pasa de 100', () => {
    expect(avanceDeLaDescarga(descarga({ bytes: 409.9 * MB }))).toBe(99);
    expect(avanceDeLaDescarga(descarga({ bytes: 500 * MB }))).toBe(100);
  });

  it('las cifras con coma y en base 1024, como el servicio', () => {
    expect(tamanoLegible(850 * 1024)).toBe('850 KB');
    expect(tamanoLegible(2.4 * MB)).toBe('2,4 MB');
    expect(tamanoLegible(1.6 * 1024 * MB)).toBe('1,6 GB');
    expect(bajandoDeLaRed(descarga({ bytes: 2.4 * MB, total: 8.5 * MB, falta_s: 2 }))).toBe(
      'Bajando de la red · 2,4 / 8,5 MB · 28 % · 3,5 MB/s · falta ~2 s'
    );
  });

  it('los redondeos no se contradicen (revisión, 2026-11-09)', () => {
    expect(tamanoLegible(9.96 * MB)).toBe('10 MB');
    expect(tamanoLegible(1023.9 * 1024)).toBe('1,0 MB');
    expect(faltaCorta(59.6)).toBe('1 min');
    expect(
      resumenDeLasDescargas([descarga({ bytes: 100 * MB, total: 200 * MB }), descarga({ bytes: 300 * MB, total: 0 })])
    ).toBe('Bajando 2 PDF · 400 MB');
  });

  it('lo que falta, en corto', () => {
    expect(faltaCorta(null)).toBeNull();
    expect(faltaCorta(0.4)).toBe('1 s');
    expect(faltaCorta(45)).toBe('45 s');
    expect(faltaCorta(150)).toBe('3 min');
    expect(faltaCorta(3900)).toBe('1 h 05 min');
  });

  it('si la red se cortó y la copia volvió a empezar, lo dice', () => {
    expect(bajandoDeLaRed(descarga({ intento: 2 }))).toMatch(/· intento 2$/);
  });

  it('el resumen de la corrida cuenta sólo lo que baja', () => {
    expect(resumenDeLasDescargas([])).toBeNull();
    expect(resumenDeLasDescargas([descarga({ estado: 'esperando', bytes: 0 })])).toBeNull();
    expect(
      resumenDeLasDescargas([descarga(), descarga({ bytes: 123 * MB, total: 410 * MB })])
    ).toBe('Bajando 2 PDF · 246 / 820 MB');
  });
});
