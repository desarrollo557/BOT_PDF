import { describe, expect, it } from 'vitest';
import { enlaceAlDocumento, migasDe, padreDe } from './navegacion.svelte';

const url = (ruta: string) => new URL(ruta, 'http://localhost');

describe('la jerarquía de las vistas', () => {
  it('una sección no lleva migas ni padre', () => {
    expect(migasDe(url('/archivo'))).toEqual([]);
    expect(padreDe(url('/revision'))).toBeNull();
  });

  it('un documento sin origen cuelga del archivo', () => {
    expect(migasDe(url('/documento/abc'), 'UPD1.pdf')).toEqual([
      { etiqueta: 'Archivo', href: '/archivo' },
      { etiqueta: 'UPD1.pdf', href: null }
    ]);
    expect(padreDe(url('/documento/abc'))).toBe('/archivo');
  });

  it('abierto desde revisión, vuelve a revisión', () => {
    expect(padreDe(url(enlaceAlDocumento('abc', 'revision')))).toBe('/revision');
  });

  it('abierto desde una carpeta del archivo, vuelve a esa carpeta', () => {
    const enlace = url(enlaceAlDocumento('abc', 'archivo', 'ACTAS 2003'));
    const migas = migasDe(enlace, 'UPD1.pdf');
    expect(migas.map((m) => m.etiqueta)).toEqual(['Archivo', 'Carpeta ACTAS 2003', 'UPD1.pdf']);
    expect(padreDe(enlace)).toBe('/archivo?q=ACTAS+2003');
  });

  it('un origen inventado cae en el archivo', () => {
    expect(padreDe(url('/documento/abc?desde=otra'))).toBe('/archivo');
  });
});
