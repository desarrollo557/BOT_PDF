import { describe, expect, it } from 'vitest';
import type { RedDeLaCorrida } from './types';
import { lado, loQueFalta, vaPorLaRed } from './velocidad';

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
