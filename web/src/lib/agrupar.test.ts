import { afterEach, describe, expect, it, vi } from 'vitest';
import { uploadDocument, type Health } from './api';
import { pageRange, unitFor } from './format';
import { HABILIDADES, motivoSinAgrupar } from './habilidades';

/**
 * La caja de correspondencia puede entregar un archivo por mes («por fecha»).
 *
 * Se fijan tres cosas que la pantalla tiene que cumplir para que la elección
 * sea de fiar: que la opción existe y que lo de siempre sigue siendo lo
 * primero; que contra un servicio que no la sabe hacer se ofrece apagada en vez
 * de ignorarse en silencio; y que viaja al servicio sólo cuando se pidió.
 */

const correspondencia = HABILIDADES.find((habilidad) => habilidad.id === 'correspondencia')!;
const porMes = correspondencia.agrupar!.opciones.find((opcion) => opcion.id === 'mes')!;

function health(features: string[]): Health {
  return { status: 'ok', api_revision: 19, features } as Health;
}

describe('la opción en la caja de correspondencia', () => {
  it('ofrece un archivo por documento y uno por mes, lo de siempre primero', () => {
    expect(correspondencia.agrupar?.opciones.map((opcion) => opcion.id)).toEqual([
      'documento',
      'mes'
    ]);
  });

  it('se nombra como lo dice el operador: por fecha', () => {
    expect(porMes.label).toMatch(/^Por fecha/);
    expect(porMes.agrupa).toContain('mismo mes');
  });

  it('sólo la caja de correspondencia la ofrece', () => {
    const conAgrupar = HABILIDADES.filter((habilidad) => habilidad.agrupar);
    expect(conAgrupar.map((habilidad) => habilidad.id)).toEqual(['correspondencia']);
  });

  it('dice cómo se llamará cada archivo', () => {
    expect(porMes.nombra).toContain('2023-05_');
  });
});

describe('contra un servicio que no la sabe hacer', () => {
  it('se puede pedir cuando el servicio la anuncia', () => {
    expect(motivoSinAgrupar(porMes, health(['agrupar-por-mes']))).toBeNull();
  });

  it('se apaga con su motivo cuando no la anuncia', () => {
    // Un servicio viejo ignoraría el parámetro y la caja saldría como siempre.
    expect(motivoSinAgrupar(porMes, health(['segment-task']))).toMatch(/reiniciarlo/);
  });

  it('y también mientras no se sabe qué anuncia, sin mandar a reiniciar', () => {
    // Puede estar arrancando: pedir que lo reinicien sería mandar a reiniciar
    // un servicio que ya es el bueno.
    const motivo = motivoSinAgrupar(porMes, null);
    expect(motivo).not.toBeNull();
    expect(motivo).not.toMatch(/reiniciarlo/);
  });

  it('lo de siempre no depende de ninguna capacidad', () => {
    const porDocumento = correspondencia.agrupar!.opciones[0];
    expect(motivoSinAgrupar(porDocumento, null)).toBeNull();
  });
});

describe('lo que viaja al servicio', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function urlDeLaSubida() {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 'x' }), { status: 202 })
    );
    vi.stubGlobal('fetch', fetch);
    return fetch;
  }

  it('por mes viaja como agrupar=mes', async () => {
    const fetch = urlDeLaSubida();
    await uploadDocument(
      new File(['%PDF'], 'caja.pdf'),
      undefined,
      'segment',
      'auto',
      'local',
      'auto',
      'pagina',
      'mes'
    );
    expect(String(fetch.mock.calls[0][0])).toContain('agrupar=mes');
  });

  it('por documento no viaja, para no molestar a un servicio anterior', async () => {
    const fetch = urlDeLaSubida();
    await uploadDocument(new File(['%PDF'], 'caja.pdf'), undefined, 'segment');
    expect(String(fetch.mock.calls[0][0])).not.toContain('agrupar');
  });
});

describe('pageRange', () => {
  it('junta las páginas seguidas en tramos', () => {
    expect(pageRange([1, 2, 4, 5])).toBe('1–2, 4–5');
  });

  it('no miente con un rango cuando hay huecos', () => {
    // Un archivo por mes junta documentos separados en la caja.
    expect(pageRange([1, 2, 4])).not.toBe('1–4');
    expect(pageRange([1, 2, 4])).toBe('1–2, 4');
  });

  it('una sola página y ninguna', () => {
    expect(pageRange([7])).toBe('7');
    expect(pageRange([])).toBe('');
  });
});

describe('lo que se cuenta', () => {
  it('una caja entregada por mes cuenta meses', () => {
    expect(unitFor({ agrupar: 'mes' }, 7)).toBe('meses');
    expect(unitFor({ agrupar: 'mes' }, 1)).toBe('mes');
  });

  it('por documento sigue contando como antes', () => {
    expect(unitFor({ agrupar: 'documento' }, 2)).toBe('unidades documentales');
  });
});
