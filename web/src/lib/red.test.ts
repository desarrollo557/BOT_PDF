import { afterEach, describe, expect, it, vi } from 'vitest';
import { alPedirCredenciales, ApiError, browseFolders, credencialesPedidas } from './api';

const RECURSO = '\\\\200.100.20.97\\afinia';

function json(status: number, cuerpo: unknown): Response {
  return new Response(JSON.stringify(cuerpo), {
    status,
    headers: { 'content-type': 'application/json' }
  });
}

const PIDE = (motivo = 'El servidor pide usuario y clave') =>
  json(401, {
    detail: { codigo: 'credenciales_de_red', recurso: RECURSO, mensaje: `${motivo}: ${RECURSO}` }
  });
const LISTADO = { path: RECURSO + '\\', parent: null, drives: [], folders: [] };

describe('la carpeta de red que pide usuario y clave', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    alPedirCredenciales(null);
  });

  it('reconoce la pregunta del servicio', () => {
    expect(credencialesPedidas({ detail: { codigo: 'credenciales_de_red', recurso: RECURSO, mensaje: 'x' } })).toEqual({
      recurso: RECURSO,
      mensaje: 'x'
    });
    expect(credencialesPedidas({ detail: 'La carpeta no existe' })).toBeNull();
  });

  it('pregunta, conecta y repite la petición', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(PIDE())
      .mockResolvedValueOnce(json(200, { recurso: RECURSO, conectado: true }))
      .mockResolvedValueOnce(json(200, LISTADO));
    vi.stubGlobal('fetch', fetch);
    const preguntas: string[] = [];
    alPedirCredenciales(async (pedido) => {
      preguntas.push(pedido.mensaje);
      return { usuario: 'SIAR\\desarrollo', clave: 'secreta' };
    });

    expect(await browseFolders(RECURSO)).toEqual(LISTADO);
    expect(preguntas).toEqual([`El servidor pide usuario y clave: ${RECURSO}`]);
    const [url, init] = fetch.mock.calls[1];
    expect(url).toBe('/api/red/conectar');
    expect(JSON.parse(init.body)).toEqual({ ruta: RECURSO, usuario: 'SIAR\\desarrollo', clave: 'secreta' });
  });

  it('con la clave mala vuelve a preguntar con el motivo', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(PIDE())
        .mockResolvedValueOnce(PIDE('El usuario o la clave no son correctos'))
        .mockResolvedValueOnce(json(200, { conectado: true }))
        .mockResolvedValueOnce(json(200, LISTADO))
    );
    const preguntas: string[] = [];
    alPedirCredenciales(async (pedido) => {
      preguntas.push(pedido.mensaje);
      return { usuario: 'SIAR\\desarrollo', clave: preguntas.length === 1 ? 'mala' : 'buena' };
    });

    expect(await browseFolders(RECURSO)).toEqual(LISTADO);
    expect(preguntas[1]).toContain('no son correctos');
  });

  it('si cancela, el error dice qué pidió el servidor', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(PIDE()));
    alPedirCredenciales(async () => null);

    await expect(browseFolders(RECURSO)).rejects.toThrow(ApiError);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(PIDE()));
    await expect(browseFolders(RECURSO)).rejects.toThrow(/pide usuario y clave/);
  });
});
