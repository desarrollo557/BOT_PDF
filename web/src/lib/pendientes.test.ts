import { describe, expect, it } from 'vitest';
import { pendientes, resueltos } from './pendientes';

describe('la Revisión que el agente ya resolvió (2026-11-23)', () => {
  const report = {
    review_queue: [
      { page: 1, reason: 'RE por confirmar: RE2310202408877', resuelto: { accion: 'decidido por el agente', conclusion: 'puso RE2310202408877' } },
      { page: 3, reason: 'la fecha del documento no se pudo leer' }
    ]
  };

  it('sólo espera a una persona lo que el agente no resolvió', () => {
    expect(pendientes(report).map((a) => a.page)).toEqual([3]);
    expect(resueltos(report).map((a) => a.page)).toEqual([1]);
  });

  it('un informe sin cola no tiene nada pendiente', () => {
    expect(pendientes(null)).toEqual([]);
    expect(pendientes({})).toEqual([]);
  });
});
