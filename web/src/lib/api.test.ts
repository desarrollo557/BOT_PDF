/**
 * Lo que se le enseña al operador cuando el servicio contesta que no.
 *
 * Un parámetro mal escrito volvía como la lista de errores de pydantic, y
 * metida en un `Error` la pantalla decía «[object Object]». Esto fija que un
 * fallo siempre se convierte en una frase, venga como venga.
 */
import { describe, expect, it } from 'vitest';
import { mensajeDe } from './api';

describe('mensajeDe', () => {
  it('usa la frase del servicio cuando la hay', () => {
    expect(mensajeDe(422, { detail: 'El parámetro «limit» debe ser un número entero.' })).toBe(
      'El parámetro «limit» debe ser un número entero.'
    );
  });

  it('convierte la lista de pydantic en una frase con el campo', () => {
    const mensaje = mensajeDe(422, {
      detail: [
        {
          type: 'int_parsing',
          loc: ['query', 'limit'],
          msg: 'Input should be a valid integer, unable to parse string as an integer',
          input: 'abc'
        }
      ]
    });
    expect(mensaje).toContain('«limit»');
    expect(mensaje).toContain('valid integer');
    expect(mensaje).not.toContain('[object Object]');
  });

  it('enseña cada error de la lista', () => {
    const mensaje = mensajeDe(422, {
      detail: [
        { loc: ['query', 'limit'], msg: 'uno' },
        { loc: ['query', 'offset'], msg: 'dos' }
      ]
    });
    expect(mensaje).toContain('«limit»: uno');
    expect(mensaje).toContain('«offset»: dos');
  });

  it('un 404 dice que el servicio es viejo, no que el dato está mal', () => {
    expect(mensajeDe(404, null)).toContain('reinicie el backend');
    expect(mensajeDe(405, {})).toContain('405');
  });

  it('sin nada que decir, al menos dice el código', () => {
    expect(mensajeDe(500, null)).toBe('Error 500');
    expect(mensajeDe(502, { detail: '' })).toBe('Error 502');
    expect(mensajeDe(422, { detail: [] })).toBe('Error 422');
  });
});
