import { describe, expect, it } from 'vitest';
import {
  avisoDeLaMuestra,
  esDeFilas,
  faseEnCurso,
  filasDelCuadre,
  habilidadesDeLaMuestra,
  iaDeLaMuestra,
  muestraVacia,
  paraMirar,
  porCiento,
  rotuloDeLaMuestra,
  textoSinMuestra,
  tonoDeLaEtapa,
  topeDeLaEscala,
  topeDelMargen
} from './auditoria';
import type { ComparacionDeLaEntrega, MargenDeUnaHabilidad, MuestraAuditada } from './types';

function comparacion(cambios: Partial<ComparacionDeLaEntrega> = {}): ComparacionDeLaEntrega {
  return {
    entradas_origen: 4,
    carpetas_origen: 3,
    carpetas_destino: 2,
    carpetas_con_pdf: 2,
    carpetas_completas: 2,
    pdf_origen: 3,
    pdf_entregados: 3,
    documentos_entregados: 6,
    filas_del_indice: 6,
    sin_pdf: [{ carpeta: '6909379', motivo: 'carpeta totalmente vacía', evidencia: '0 archivos al listarla' }],
    archivos_en_la_raiz: [],
    sobran: [],
    faltan: [],
    pdf_sin_entregar: [],
    registros_que_no_cuadran: [],
    completa: true,
    ...cambios
  };
}

function muestra(cambios: Partial<MuestraAuditada> = {}): MuestraAuditada {
  return {
    semilla: 7,
    candidatos: 100,
    revisados: 100,
    bien: 99,
    errores: 0,
    dudosos: 1,
    no_auditados: 0,
    ampliada: false,
    margen: {
      errores: 0,
      revisados: 100,
      tasa: 0,
      desde: 0,
      hasta: 0.037,
      confianza: 0.95,
      aceptable: 0.05,
      dictamen: 'dentro del margen',
      texto: '0 de 100 con error',
      texto_del_dictamen: 'Dentro del margen aceptable (5 %)'
    },
    pdfs: [
      { pdf: 'a.pdf', estado: 'bien', hallazgos: [], paginas: 3, archivos: 2, costuras: 2, dentro_del_margen: 2, preguntadas_a_la_ia: 0, habilidad: '' },
      { pdf: 'b.pdf', estado: 'dudoso', hallazgos: ['hojas 1-2: TERCERO'], paginas: 3, archivos: 3, costuras: 2, dentro_del_margen: 1, preguntadas_a_la_ia: 0, habilidad: '' },
      { pdf: 'c.pdf', estado: 'error', hallazgos: ['falta la hoja 3'], paginas: 3, archivos: 2, costuras: 2, dentro_del_margen: 2, preguntadas_a_la_ia: 0, habilidad: '' }
    ],
    ...cambios
  };
}

describe('el cuadre de origen y destino', () => {
  it('tres cuentas que cuadran', () => {
    const filas = filasDelCuadre(comparacion());
    expect(filas.map((fila) => [fila.etiqueta, fila.origen, fila.destino, fila.cuadra])).toEqual([
      ['PDF', 3, 3, true],
      ['Documentos', 6, 6, true],
      ['Carpetas', 2, 2, true]
    ]);
  });

  it('lo que falta no cuadra', () => {
    const filas = filasDelCuadre(comparacion({ pdf_entregados: 2, carpetas_completas: 1, completa: false }));
    expect(filas.filter((fila) => !fila.cuadra).map((fila) => fila.etiqueta)).toEqual(['PDF', 'Carpetas']);
  });

  it('sin índices no hay registros que descuadren', () => {
    expect(filasDelCuadre(comparacion({ filas_del_indice: 0 }))[1].cuadra).toBe(true);
  });
});

describe('cómo terminó y cómo va', () => {
  it('el tono de cada final', () => {
    expect(tonoDeLaEtapa('Terminado')).toBe('good');
    expect(tonoDeLaEtapa('Terminado con faltantes')).toBe('bad');
    expect(tonoDeLaEtapa('Terminado: error fuera del margen')).toBe('bad');
    expect(tonoDeLaEtapa('Terminado: errores dentro del margen')).toBe('accent');
    expect(tonoDeLaEtapa('Terminado con errores en la muestra')).toBe('warn');
    expect(tonoDeLaEtapa(null)).toBe('neutral');
  });

  it('la fase en curso', () => {
    expect(faseEnCurso({ estado: 'auditando', fase: 'muestra', hechos: 37, total: 100 })).toBe(
      'Revisando la muestra al azar: 37 de 100 PDF'
    );
    expect(faseEnCurso({ estado: 'auditando', fase: 'cuadre', hechos: 1200, total: 30000 })).toContain('1.200 de 30.000');
  });
});

describe('la muestra y su margen', () => {
  it('lo que hay que mirar, con error primero', () => {
    expect(paraMirar(muestra()).map((pdf) => pdf.pdf)).toEqual(['c.pdf', 'b.pdf']);
  });

  it('la escala llega al menos al doble del margen aceptable', () => {
    expect(topeDeLaEscala(muestra())).toBeCloseTo(0.1);
    const fuera = muestra({ margen: { ...muestra().margen, hasta: 0.2 } });
    expect(topeDeLaEscala(fuera)).toBeCloseTo(0.25);
  });

  it('el por ciento con coma', () => {
    expect(porCiento(0.037)).toBe('3,7 %');
    expect(porCiento(0.05)).toBe('5 %');
  });
});

describe('cada habilidad contra su margen', () => {
  function habilidad(
    clave: string,
    dictamen: MargenDeUnaHabilidad['margen']['dictamen'],
    revisados: number
  ): MargenDeUnaHabilidad {
    return {
      clave,
      habilidad: clave,
      revisados,
      bien: revisados,
      errores: 0,
      dudosos: 0,
      no_auditados: 0,
      margen: { ...muestra().margen, dictamen, revisados }
    };
  }

  it('con una sola habilidad no se repite: el margen de la corrida ya es el suyo', () => {
    expect(habilidadesDeLaMuestra(muestra({ por_habilidad: [habilidad('kingspan', 'dentro del margen', 100)] }))).toEqual([]);
    expect(habilidadesDeLaMuestra(muestra())).toEqual([]);
  });

  it('la que se sale primero, luego la más revisada', () => {
    const por_habilidad = [
      habilidad('correspondencia', 'dentro del margen', 80),
      habilidad('historias', 'sin certeza', 5),
      habilidad('diplomas', 'fuera del margen', 15),
      habilidad('actas-de-grado', 'sin certeza', 10)
    ];
    expect(habilidadesDeLaMuestra(muestra({ por_habilidad })).map((h) => h.clave)).toEqual([
      'diplomas',
      'actas-de-grado',
      'historias',
      'correspondencia'
    ]);
  });

  it('la escala de una habilidad, como la de la corrida', () => {
    expect(topeDelMargen({ ...muestra().margen, aceptable: 0.02, hasta: 0.3 })).toBeCloseTo(0.375);
  });
});

describe('la muestra de filas del inventario (2026-11-09)', () => {
  const fila = {
    pdf: '00C003284/UPD3859771/1N°22.pdf · págs. 1-22 · acta 022',
    estado: 'bien' as const,
    hallazgos: [],
    paginas: 22,
    archivos: 0,
    costuras: 0,
    dentro_del_margen: 0,
    preguntadas_a_la_ia: 0,
    habilidad: 'actas'
  };

  it('sin unidad es de PDF, como las auditorías anteriores', () => {
    expect(esDeFilas(muestra())).toBe(false);
    expect(esDeFilas(muestra({ unidad: 'filas' }))).toBe(true);
    expect(esDeFilas(null)).toBe(false);
  });

  it('el rótulo dice filas del inventario o PDF', () => {
    expect(rotuloDeLaMuestra(muestra())).toBe('Muestra al azar: 100 PDF');
    expect(rotuloDeLaMuestra(muestra({ unidad: 'filas', pdfs: [fila] }))).toBe('Muestra al azar: 100 filas del inventario');
    expect(rotuloDeLaMuestra(muestra({ unidad: 'filas', revisados: 200, ampliada: true }))).toBe(
      'Muestra al azar: 200 filas del inventario, ampliada por los errores'
    );
  });

  it('la fase en curso cuenta filas', () => {
    expect(faseEnCurso({ estado: 'auditando', fase: 'muestra', unidad: 'filas', hechos: 12, total: 100 })).toBe(
      'Revisando la muestra al azar: 12 de 100 filas'
    );
    expect(faseEnCurso({ estado: 'auditando', fase: 'muestra', unidad: 'pdf', hechos: 12, total: 100 })).toBe(
      'Revisando la muestra al azar: 12 de 100 PDF'
    );
  });

  it('el aviso del resumen dice filas', () => {
    const deFilas = muestra({ unidad: 'filas', bien: 98, revisados: 100 });
    expect(avisoDeLaMuestra(deFilas)).toBe('muestra: 98 de 100 filas bien · error < 3,7 %, dentro del margen');
    expect(avisoDeLaMuestra(muestra())).toBe('muestra: 99 de 100 bien · error < 3,7 %, dentro del margen');
  });

  it('la IA de la muestra: lo que revisó y lo que costó', () => {
    const conIa = muestra({
      unidad: 'filas',
      con_ia: true,
      preguntadas_a_la_ia: 4,
      consumo_ia: { peticiones: 4, tokens_entrada: 2500, tokens_salida: 620, tokens: 3120 }
    });
    const texto = iaDeLaMuestra(conIa);
    expect(texto).toBe('La IA revisó 4 datos dudosos · 4 peticiones · 3.120 tokens');
    expect(iaDeLaMuestra(muestra({ unidad: 'filas', con_ia: true, preguntadas_a_la_ia: 1 }))).toBe(
      'La IA revisó 1 dato dudoso'
    );
  });

  it('una IA caída no «revisó» nada: se dice (la revisión, 2026-11-09)', () => {
    const caida = muestra({
      unidad: 'filas',
      con_ia: true,
      preguntadas_a_la_ia: 0,
      consumo_ia: { peticiones: 0, tokens_entrada: 0, tokens_salida: 0, tokens: 0, fallos: 2 }
    });
    expect(iaDeLaMuestra(caida)).toBe('La IA no respondió: lo dudoso queda para revisar · la IA no respondió en 2 filas');
    const aMedias = muestra({
      unidad: 'filas',
      con_ia: true,
      preguntadas_a_la_ia: 3,
      consumo_ia: { peticiones: 3, tokens_entrada: 900, tokens_salida: 100, tokens: 1000, fallos: 1 }
    });
    expect(iaDeLaMuestra(aMedias)).toBe(
      'La IA revisó 3 datos dudosos · 3 peticiones · 1.000 tokens · la IA no respondió en 1 fila'
    );
  });

  it('sin IA lo dice: lo dudoso queda para revisar', () => {
    expect(iaDeLaMuestra(muestra({ unidad: 'filas', con_ia: false }))).toBe('Sin IA: lo dudoso queda para revisar');
  });

  it('una muestra de PDF no habla de la IA de filas', () => {
    expect(iaDeLaMuestra(muestra())).toBeNull();
  });
});

describe('una muestra vacía no se dibuja como «< 0 %»', () => {
  const vacia = muestra({
    candidatos: 0,
    revisados: 0,
    bien: 0,
    dudosos: 0,
    pdfs: [],
    margen: { ...muestra().margen, revisados: 0, hasta: 0, dictamen: 'sin certeza' }
  });

  it('sin nada revisado está vacía', () => {
    expect(muestraVacia(vacia)).toBe(true);
    expect(muestraVacia(muestra())).toBe(false);
  });

  it('sin candidatos: la corrida no entregó nada que revisar', () => {
    expect(textoSinMuestra(vacia)).toBe(
      'Sin muestra: la corrida no entregó PDF cortados ni filas de inventario que revisar'
    );
  });

  it('con candidatos que no se pudieron abrir', () => {
    expect(textoSinMuestra({ ...vacia, candidatos: 30 })).toBe('Sin muestra: no se pudo revisar ningún elemento');
  });

  it('el aviso del resumen no dice «error < 0 %, sin certeza»', () => {
    const aviso = avisoDeLaMuestra(vacia);
    expect(aviso).toContain('Sin muestra');
    expect(aviso).not.toContain('< 0');
    expect(aviso).not.toContain('sin certeza');
  });
});
