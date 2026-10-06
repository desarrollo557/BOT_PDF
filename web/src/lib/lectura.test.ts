import { describe, expect, it } from 'vitest';
import { lecturaOptions, reasonForLectura } from './lectura';
import type { Health } from './api';

/**
 * Con qué se lee el papel: dos opciones y ni una más.
 *
 * Lo que se fija aquí es sobre todo **cómo se llaman**. El operador se quedó
 * parado delante de este selector -- «no sé qué opción elegir aquí» -- porque
 * decía «Tesseract» y «+ Mistral OCR», que son nombres de producto y no
 * describen la decisión. Lo que él sabe de su caja es si está escrita a mano o
 * a máquina, así que las opciones se llaman por eso: «Solo OCR» y «OCR + IA».
 *
 * No es cosmético. Elegir mal aquí no da error: da una carpeta entera de
 * archivos nombrados por su orden y un inventario sin una sola cédula, y eso no
 * se descubre hasta que el trabajo terminó.
 */

const salud = (parcial: Partial<Health> = {}): Health =>
  ({
    status: 'ok',
    api_revision: 17,
    features: [],
    document_workers: 3,
    page_workers: 8,
    ...parcial
  }) as Health;

describe('las dos formas de leer', () => {
  it('son tres, y en orden de coste creciente', () => {
    const opciones = lecturaOptions(salud({ readers: { local: true, mistral: true, 'mistral-nombres': true } }));
    expect(opciones.map((opcion) => opcion.id)).toEqual(['local', 'mistral', 'mistral-nombres']);
  });

  it('se llaman como las llamaría un archivista, no como el proveedor', () => {
    const opciones = lecturaOptions(salud({ readers: { local: true, mistral: true, 'mistral-nombres': true } }));
    expect(opciones.map((opcion) => opcion.label)).toEqual([
      'Solo OCR',
      'OCR + IA',
      'OCR + IA (ahorro)'
    ]);
  });

  it('la de ahorro dice qué deja de leer, porque es una renuncia', () => {
    const opciones = lecturaOptions(salud({ readers: { local: true, mistral: true, 'mistral-nombres': true } }));
    const ahorro = opciones.find((opcion) => opcion.id === 'mistral-nombres');
    // Diez caras por página facturada, a cambio de leer sólo el nombre. En un
    // libro manuscrito eso no quita nada -- el folio y la fecha salen ilegibles
    // igual -- pero el operador tiene que poder saberlo antes de elegir.
    expect(ahorro?.hint).toMatch(/diez caras/i);
    expect(ahorro?.hint).toMatch(/sólo el nombre/i);
  });

  it('ninguna etiqueta nombra un producto', () => {
    const opciones = lecturaOptions(salud({ readers: { local: true, mistral: true, 'mistral-nombres': true } }));
    for (const opcion of opciones) {
      expect(opcion.label).not.toMatch(/tesseract|mistral/i);
    }
  });

  it('dicen cuál cuesta dinero y cuál no', () => {
    const [soloOcr, conIa] = lecturaOptions(salud({ readers: { local: true, mistral: true, 'mistral-nombres': true } }));
    expect(soloOcr.hint).toMatch(/gratis/);
    expect(conIa.hint).toMatch(/se paga/);
  });
});

describe('lo que no se puede pedir se dice, no se esconde', () => {
  it('«Solo OCR» siempre se puede pedir', () => {
    const [soloOcr] = lecturaOptions(null);
    expect(soloOcr.available).toBe(true);
    expect(soloOcr.reason).toBeNull();
  });

  it('sin llave, la IA se ofrece apagada y con el motivo', () => {
    const opciones = lecturaOptions(salud({ readers: { local: true, mistral: false, 'mistral-nombres': false } }));
    const conIa = opciones.find((opcion) => opcion.id === 'mistral');
    expect(conIa?.available).toBe(false);
    // El motivo tiene que decirle al operador qué hacer, no sólo qué falla.
    expect(conIa?.reason).toMatch(/Solo OCR/);
  });

  it('un servicio que no contesta no es un servicio sin llaves', () => {
    const conIa = lecturaOptions(null).find((opcion) => opcion.id === 'mistral');
    expect(conIa?.available).toBe(false);
    expect(conIa?.reason).toMatch(/no informó/);
  });

  it('elegir la IA sin llave se explica antes de subir el archivo', () => {
    const opciones = lecturaOptions(salud({ readers: { local: true, mistral: false, 'mistral-nombres': false } }));
    expect(reasonForLectura('mistral', opciones)).not.toBeNull();
    expect(reasonForLectura('local', opciones)).toBeNull();
  });
});
