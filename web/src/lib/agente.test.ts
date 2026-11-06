import { describe, expect, it } from 'vitest';
import {
  ESTADOS,
  cinta,
  filasDeLosDatos,
  frase,
  porQuien,
  porcentaje,
  queMovio,
  rango,
  repartoDeCosturas,
  repartoDePdf
} from './agente';
import type { AgenteDeLaCorrida, RevisionDeCortes } from './types';

/** 1004569/UPD2437853 tras el agente: las hojas 4-5 volvieron al contrato. */
function corregida(): RevisionDeCortes {
  return {
    estado: 'corregido',
    resumen: 'Revisor de cortes: corregido (10 costuras, 9 dentro del margen; 1 corregidas)',
    costuras: 10,
    dentro_del_margen: 9,
    preguntadas_a_la_ia: 0,
    confirmadas_por_la_ia: 0,
    movimientos: [
      {
        paginas: [4, 5],
        desde: [4, 5, 7, 8, 9, 10, 11],
        hacia: [2, 3],
        por: 'dos pruebas del papel',
        motivo: 'la cláusula TERCERO de la hoja derecha sigue a la SEGUNDO de la izquierda',
        costura: [3, 4]
      }
    ],
    en_revision: [],
    documentos: [
      { paginas: [1], estado: 'validado' },
      { paginas: [2, 3, 4, 5], estado: 'corregido' },
      { paginas: [6], estado: 'validado' },
      { paginas: [7, 8, 9, 10, 11], estado: 'corregido' }
    ],
    fuera_del_margen: [
      { izq: 3, der: 4, decision: 'corte', confianza: 0.05, resultado: 'corregida', motivo: 'TERCERO tras SEGUNDO' }
    ]
  };
}

describe('la cinta de hojas', () => {
  it('cada hoja con su documento, y quién abre cada uno', () => {
    const { hojas, documentos } = cinta(corregida(), 11);
    expect(documentos).toBe(4);
    expect(hojas.map((hoja) => hoja.documento)).toEqual([0, 1, 1, 1, 1, 2, 3, 3, 3, 3, 3]);
    expect(hojas.filter((hoja) => hoja.abre).map((hoja) => hoja.pagina)).toEqual([1, 2, 6, 7]);
  });

  it('las hojas que movió el agente lo dicen', () => {
    const { hojas } = cinta(corregida(), 11);
    expect(hojas.filter((hoja) => hoja.movida).map((hoja) => hoja.pagina)).toEqual([4, 5]);
  });

  it('cada costura: unión o corte, y lo que hizo el agente', () => {
    const { costuras } = cinta(corregida(), 11);
    expect(costuras).toHaveLength(10);
    const tercera = costuras[2];
    expect(tercera).toMatchObject({ izq: 3, der: 4, tipo: 'union', resultado: 'corregida', confianza: 0.05 });
    expect(costuras[0]).toMatchObject({ tipo: 'corte', resultado: 'validada', motivo: null });
    expect(costuras.filter((c) => c.resultado === 'validada')).toHaveLength(9);
  });

  it('un informe sin documentos no inventa hojas', () => {
    const { hojas, costuras } = cinta({ estado: 'no corrió', resumen: 'falló' }, 3);
    expect(hojas.map((hoja) => hoja.documento)).toEqual([-1, -1, -1]);
    expect(costuras.every((c) => c.tipo === 'union')).toBe(true);
  });
});

describe('los repartos', () => {
  it('el anillo cuenta las costuras sin tramos en cero', () => {
    expect(repartoDeCosturas(corregida())).toEqual([
      { clave: 'validada', etiqueta: 'Dentro del margen', valor: 9, tono: 'good' },
      { clave: 'corregida', etiqueta: 'Corregidas', valor: 1, tono: 'accent' }
    ]);
  });

  it('la barra de la corrida cuenta los PDF', () => {
    const agente = {
      pdf: 26,
      validados: 24,
      corregidos: 1,
      en_revision: 1,
      sin_revisar: 0
    } as AgenteDeLaCorrida;
    expect(repartoDePdf(agente).map((tramo) => [tramo.clave, tramo.valor])).toEqual([
      ['validado', 24],
      ['corregido', 1],
      ['en revisión', 1]
    ]);
  });
});

describe('las frases', () => {
  it('el porcentaje no redondea a 100 lo que no es todo', () => {
    expect(porcentaje(9, 10)).toBe('90 %');
    expect(porcentaje(999, 1000)).toBe('99 %');
    expect(porcentaje(10, 10)).toBe('100 %');
    expect(porcentaje(0, 0)).toBeNull();
  });

  it('el rango de hojas', () => {
    expect(rango([5, 4])).toBe('4–5');
    expect(rango([1, 6, 7])).toBe('1, 6, 7');
    expect(rango([3])).toBe('3');
  });

  it('qué movió y quién lo decidió', () => {
    expect(queMovio(corregida().movimientos![0])).toBe('Hojas 4–5 → con las hojas 2–3');
    expect(queMovio({ paginas: [9], desde: [8, 9], hacia: null, por: 'la IA', motivo: '' })).toBe(
      'Hoja 9 → en su propio documento'
    );
    expect(porQuien('la IA')).toBe('Decidido por la IA');
    expect(porQuien('dos pruebas del papel')).toBe('Dos pruebas del papel');
  });

  it('la frase de cabecera dice lo que pasó con las cifras del informe', () => {
    expect(frase(corregida(), 11)).toBe('Revisó 10 costuras entre 11 hojas: 1 salió del margen, 1 corrección.');
    const validada = { ...corregida(), estado: 'validado' as const, dentro_del_margen: 10, movimientos: [] };
    expect(frase(validada, 11)).toBe('Revisó 10 costuras entre 11 hojas: todas dentro del margen de error.');
    expect(frase({ estado: 'validado', resumen: null, costuras: 0 }, 1)).toBe(
      'Una sola hoja: no hay costuras que revisar.'
    );
    expect(frase({ estado: 'no corrió', resumen: 'El revisor falló' }, 3)).toBe('El revisor falló');
  });
});

describe('los datos de cada documento', () => {
  it('una fila por dato, en su orden, con sus cuentas', () => {
    const filas = filasDeLosDatos({
      documentos: 30,
      completos: 2,
      con_dudas: 16,
      con_errores: 12,
      por_campo: {
        fechas: { bien: 24, dudas: 0, errores: 6 },
        nombre: { bien: 21, dudas: 0, errores: 9 },
        codigo: { bien: 6, dudas: 24, errores: 0 },
        identificacion: { bien: 8, dudas: 22, errores: 0 }
      }
    });
    expect(filas.map((fila) => fila.etiqueta)).toEqual(['Nombre', 'Cédula, TI o libreta', 'Código', 'Fechas extremas']);
    expect(filas[0]).toMatchObject({ bien: 21, errores: 9, total: 30 });
  });

  it('un dato con error en el registro en vivo se dice como tal', () => {
    expect(ESTADOS.datos).toEqual({ etiqueta: 'Dato con error', tono: 'bad' });
  });
});
