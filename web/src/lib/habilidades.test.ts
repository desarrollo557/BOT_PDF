/**
 * La habilidad «Calificaciones» en la pantalla (2026-11-27).
 *
 * Fija que la tarjeta exista y se declare con su tipo -- un servicio anterior la
 * leería como «auto» --, que escriba el FUID de la Universidad, que pregunte la
 * lectura como todas, y que la sugerencia de una carpeta la proponga cuando
 * reconoce un libro de calificaciones.
 */
import { describe, expect, it } from 'vitest';
import type { Health } from './api';
import { HABILIDADES, habilidadDelTipo, motivoNoDisponible } from './habilidades';

const calificaciones = HABILIDADES.find((habilidad) => habilidad.id === 'calificaciones')!;

function servicio(tipos: string[]): Health {
  return {
    status: 'ok',
    api_revision: 28,
    document_types: tipos.map((id) => ({ id, label: id }))
  } as Health;
}

describe('la habilidad de calificaciones', () => {
  it('existe, declara su tipo y escribe el FUID de la Universidad', () => {
    expect(calificaciones).toBeDefined();
    expect(calificaciones.titulo).toBe('Calificaciones');
    expect(calificaciones.tipo).toBe('calificaciones');
    expect(calificaciones.requiereTipo).toBe('calificaciones');
    expect(calificaciones.escribeFuid).toBe(true);
  });

  it('deja dividir e inventariar o sólo inventariar, y pregunta la lectura', () => {
    expect(calificaciones.task).toBeNull();
    expect(calificaciones.acciones?.map((accion) => accion.id)).toEqual(['both', 'inventory_file']);
    expect(calificaciones.pideLectura?.porque).toBeTruthy();
  });

  it('se ofrece sólo contra un servicio que declara el tipo', () => {
    expect(motivoNoDisponible(calificaciones, servicio(['auto', 'calificaciones']))).toBeNull();
    expect(motivoNoDisponible(calificaciones, servicio(['auto', 'historia-academica']))).not.toBeNull();
  });

  it('es la que se sugiere para un libro de calificaciones reconocido', () => {
    expect(habilidadDelTipo('calificaciones')?.id).toBe('calificaciones');
    // Y las historias siguen siendo historias.
    expect(habilidadDelTipo('historia-academica')?.id).toBe('historias');
  });
});
