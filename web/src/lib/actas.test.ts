/**
 * Las actas de consejo en la pantalla, y la descarga del Excel que dejan.
 *
 * Fija dos cosas. Que la habilidad se ofrezca sólo contra un servicio que
 * declara el tipo `acta-consejo` -- uno anterior lo leería como «auto» y las
 * actas acabarían en otra ruta sin aviso --. Y que la planilla bajada conserve
 * el nombre que le dio el servicio, que es el de la carpeta o el documento:
 * descargar por `fetch` pierde el que traería el enlace, y un «download.xlsx»
 * en la carpeta de descargas no le dice a nadie de qué caja salió.
 */
import { describe, expect, it } from 'vitest';
import type { Health } from './api';
import { nombreDeLaDescarga } from './api';
import { HABILIDADES, motivoNoDisponible } from './habilidades';

const actas = HABILIDADES.find((habilidad) => habilidad.id === 'actas')!;

function servicio(tipos: string[]): Health {
  return {
    status: 'ok',
    api_revision: 20,
    document_types: tipos.map((id) => ({ id, label: id }))
  } as Health;
}

describe('la habilidad de actas de consejo', () => {
  it('existe, declara su tipo y deja elegir entre inventariar y dividir', () => {
    expect(actas).toBeDefined();
    expect(actas.tipo).toBe('acta-consejo');
    // La acción la elige el operador: sólo el Excel, o además una carpeta por
    // sesión con un PDF por pieza. Inventariar va primero, que es lo que se
    // hace si no se elige otra cosa.
    expect(actas.task).toBeNull();
    expect(actas.acciones?.map((accion) => accion.id)).toEqual(['inventory_file', 'both']);
  });

  it('pide la ayuda de pago, que es la que lee el folio y escribe el resumen', () => {
    expect(actas.pideLectura?.id).toBe('mistral');
  });

  it('se ofrece contra un servicio que declara el tipo', () => {
    expect(motivoNoDisponible(actas, servicio(['auto', 'diploma', 'acta-consejo']))).toBeNull();
  });

  it('y no contra uno que no lo declara', () => {
    expect(motivoNoDisponible(actas, servicio(['auto', 'diploma']))).not.toBeNull();
  });
});

describe('nombreDeLaDescarga', () => {
  it('lee el nombre simple', () => {
    expect(nombreDeLaDescarga('attachment; filename="ACTAS 2012__FUID.xlsx"')).toBe(
      'ACTAS 2012__FUID.xlsx'
    );
  });

  it('prefiere el UTF-8, que es el que trae las tildes y la ñ', () => {
    expect(
      nombreDeLaDescarga(
        "attachment; filename=\"N 22__FUID.xlsx\"; filename*=UTF-8''1N%C2%B022%20Diciembre__FUID.xlsx"
      )
    ).toBe('1N°22 Diciembre__FUID.xlsx');
  });

  it('sin cabecera no inventa un nombre', () => {
    expect(nombreDeLaDescarga(null)).toBeNull();
  });
});
