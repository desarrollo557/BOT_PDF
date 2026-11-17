import { describe, expect, it } from 'vitest';
import { nombresPorMirar, QUARANTINE_FILE, whereItLanded } from './revision';
import type { Job, Report } from './types';

/**
 * Llevar de una página a revisar hasta el PDF que la contiene.
 *
 * Sin esto, la pantalla de revisión decía "la página 111 tiene un problema" y
 * ahí terminaba: para verla había que adivinar cuál de los veintinueve archivos
 * del expediente se la había llevado.
 */

function job(report: Partial<Report> | null): Job {
  return {
    id: 'job-1',
    batch_id: null,
    filename: 'expediente.pdf',
    bytes: 1024,
    operator: null,
    task: 'split',
    state: 'done',
    created_at: '2026-09-02T12:00:00Z',
    started_at: '2026-09-02T12:00:00Z',
    finished_at: '2026-09-02T12:00:10Z',
    error: null,
    report: report
      ? ({ document: 'expediente.pdf', page_count: 7, ...report } as Report)
      : null,
    progress: {
      stage: 'done',
      page_count: 7,
      pages_done: 7,
      failed_pages: 0,
      by_provenance: {},
      review: {},
      ribbon: '',
      percent: 100,
      pages_per_second: 1,
      elapsed_seconds: 1
    }
  } as Job;
}

describe('whereItLanded', () => {
  it('nombra el archivo del disco cuando hay inventario', () => {
    const con = job({
      inventory: {
        source_document: 'expediente.pdf',
        source_pages: 7,
        generated_files: 1,
        pages_accounted_for: 7,
        items: [
          {
            file_name: 'RESOLUCION_00086.pdf',
            code: '00086',
            title: 'Acta',
            page_count: 3,
            first_page: 3,
            last_page: 5,
            page_numbers: [3, 4, 5]
          }
        ],
        quarantine_pages: [],
        review_pages: [4]
      }
    });
    expect(whereItLanded(con, 4)).toEqual({ file: 'RESOLUCION_00086.pdf', code: '00086' });
  });

  it('una página en cuarentena va a su propio archivo', () => {
    const con = job({ quarantine: [1, 2] });
    expect(whereItLanded(con, 1)).toEqual({ file: QUARANTINE_FILE, code: null });
  });

  it('la cuarentena manda sobre el inventario', () => {
    // Una página en cuarentena no pertenece a ninguna resolución, así que
    // buscarla entre los grupos sólo podría dar un falso positivo.
    const con = job({
      quarantine: [1],
      groups: [{ code: '00086', title: null, pages: [1, 2], size: 2 }]
    });
    expect(whereItLanded(con, 1).file).toBe(QUARANTINE_FILE);
  });

  it('sin inventario todavía dice de qué unidad es la página', () => {
    const con = job({ groups: [{ code: '00086', title: null, pages: [3, 4], size: 2 }] });
    expect(whereItLanded(con, 4)).toEqual({ file: null, code: '00086' });
  });

  it('una página que no está en ninguna parte no inventa un destino', () => {
    const con = job({ groups: [{ code: '00086', title: null, pages: [3], size: 1 }] });
    expect(whereItLanded(con, 9)).toEqual({ file: null, code: null });
  });

  it('un trabajo sin informe no rompe la pantalla', () => {
    expect(whereItLanded(job(null), 1)).toEqual({ file: null, code: null });
  });
});

describe('las historias académicas (2026-11-17)', () => {
  const historias = {
    groups: [{ code: '01_CAMPO-TORREGROZA-ETILVIA-LEONOR-49731465.pdf' }],
    outputs: ['UPD1/01_CAMPO-TORREGROZA-ETILVIA-LEONOR-49731465.pdf', 'UPD1/02_CANTILLO-TORRES-IVONNE.pdf'],
    inventario_actas: [
      {
        tipo: 'HISTORIA ACADEMICA',
        nombre: 'CAMPO TORREGROZA ETILVIA LEONOR',
        pagina_inicial: 23,
        pagina_final: 24,
        archivo_generado: '01_CAMPO-TORREGROZA-ETILVIA-LEONOR-49731465.pdf',
        revision_del_nombre: { estado: 'corregido', lecturas: ['CAMPO TERNEGROZA ETDRIA LEONOR'] }
      },
      {
        tipo: 'HISTORIA ACADEMICA',
        nombre: 'CANTILLO TORRES IVONNE',
        pagina_inicial: 25,
        pagina_final: 26,
        archivo_generado: '02_CANTILLO-TORRES-IVONNE.pdf',
        revision_del_nombre: { estado: 'duda', lecturas: ['CANTILLO TORRES IRONNE'] }
      },
      {
        tipo: 'HISTORIA ACADEMICA',
        nombre: 'ACUNA MEZA PEDRO',
        pagina_inicial: 1,
        pagina_final: 2,
        revision_del_nombre: { estado: 'confirmado' }
      }
    ]
  } as unknown as Partial<Report>;

  it('la página lleva al PDF del estudiante, aunque sus grupos no digan páginas', () => {
    expect(whereItLanded(job(historias), 24)).toEqual({
      file: 'UPD1/01_CAMPO-TORREGROZA-ETILVIA-LEONOR-49731465.pdf',
      code: '01_CAMPO-TORREGROZA-ETILVIA-LEONOR-49731465.pdf'
    });
    // Una página de nadie no rompe la pantalla.
    expect(whereItLanded(job(historias), 99)).toEqual({ file: null, code: null });
  });

  it('los nombres por mirar: los dudosos primero, y nunca los confirmados', () => {
    const nombres = nombresPorMirar([job(historias)]);
    expect(nombres.map(({ fila }) => fila.nombre)).toEqual(['CANTILLO TORRES IVONNE', 'CAMPO TORREGROZA ETILVIA LEONOR']);
    // Cada uno con su número en las filas del informe: con él se pide su renglón y se corrige.
    expect(nombres.map(({ numero }) => numero)).toEqual([2, 1]);
    expect(nombresPorMirar([job(null)])).toEqual([]);
  });

  it('los nombres por mirar son de cualquier habilidad: graduados de un acta colectiva en la misma página', () => {
    const acta = {
      inventario_actas: [
        { tipo: 'ACTA DE GRADO', nombre: 'PEREZ GOMEZ JUANA', pagina_inicial: 3, revision_del_nombre: { estado: 'duda' } },
        { tipo: 'ACTA DE GRADO', nombre: 'RUIZ DIAZ PEDRO', pagina_inicial: 3, revision_del_nombre: { estado: 'corregido' } },
        { tipo: 'NOMINA', nombre: 'CASTELLAR MEZA TULIO', revision_del_nombre: { estado: 'duda' } }
      ]
    } as unknown as Partial<Report>;
    const nombres = nombresPorMirar([job(acta)]);
    expect(nombres.map(({ numero }) => numero)).toEqual([3, 1, 2]);
  });
});
