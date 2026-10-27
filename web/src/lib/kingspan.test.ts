import { describe, expect, it } from 'vitest';

import { HABILIDADES } from './habilidades';

describe('el inventario de Kingspan pide el acta de transferencia', () => {
  const kingspan = HABILIDADES.find((habilidad) => habilidad.id === 'kingspan');

  it('ofrece las actas del inventario oficial, las mismas que valida el servicio', () => {
    // ACTAS_DE_TRANSFERENCIA en backend/src/resolutions/domain/kingspan.py
    expect(kingspan?.actasDeTransferencia).toEqual(['012', '015', '070', '088', '092', '094', '169']);
  });

  it('ninguna otra habilidad pide acta', () => {
    const otras = HABILIDADES.filter((habilidad) => habilidad.id !== 'kingspan');
    expect(otras.some((habilidad) => habilidad.actasDeTransferencia)).toBe(false);
  });
});
