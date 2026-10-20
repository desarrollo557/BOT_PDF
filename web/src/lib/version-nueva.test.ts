import { describe, expect, it } from 'vitest';
import { ESPERA_ENTRE_RECARGAS_MS, esDeVersionVieja, recargarUnaVez } from './version-nueva';

function almacen() {
  const datos = new Map<string, string>();
  return {
    getItem: (clave: string) => datos.get(clave) ?? null,
    setItem: (clave: string, valor: string) => void datos.set(clave, valor)
  };
}

describe('la pestaña de la versión anterior', () => {
  it('reconoce el archivo que ya no existe, en cada navegador', () => {
    // El mensaje real del otro escritorio, en Chrome/Edge.
    expect(
      esDeVersionVieja(
        new TypeError(
          'Failed to fetch dynamically imported module: http://localhost:8000/_app/immutable/nodes/3.DhUHgjH6.js'
        )
      )
    ).toBe(true);
    expect(esDeVersionVieja(new TypeError('Importing a module script failed.'))).toBe(true);
    expect(esDeVersionVieja(new Error('error loading dynamically imported module'))).toBe(true);
  });

  it('un error de verdad no se toma por versión vieja', () => {
    expect(esDeVersionVieja(new Error('No se pudo leer la carpeta'))).toBe(false);
    expect(esDeVersionVieja(undefined)).toBe(false);
  });

  it('recarga una vez y no entra en bucle', () => {
    const memoria = almacen();
    let recargas = 0;
    const recargar = () => void recargas++;

    expect(recargarUnaVez(memoria, recargar, 1_000_000)).toBe(true);
    // Vuelve a fallar enseguida: ya no es la versión, se enseña el error.
    expect(recargarUnaVez(memoria, recargar, 1_000_000 + 5_000)).toBe(false);
    // Mucho después, otra actualización: vale otra recarga.
    expect(recargarUnaVez(memoria, recargar, 1_000_000 + ESPERA_ENTRE_RECARGAS_MS + 1)).toBe(true);
    expect(recargas).toBe(2);
  });

  it('sin almacenamiento no recarga', () => {
    let recargas = 0;
    expect(recargarUnaVez(null, () => void recargas++)).toBe(false);
    expect(recargas).toBe(0);
  });
});
