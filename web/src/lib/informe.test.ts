import { describe, expect, it } from 'vitest';
import { describir, merge, summarise, type Completion } from './report.svelte';
import type { FilaDeActa, Job } from './types';

/**
 * Lo que dice el informe de cierre tiene que ser lo que pasó.
 *
 * De una carpeta de diez actas decía «2 unidades procesadas», «11 documentos»
 * y «10 resoluciones · archivos generados»: el título no decía qué, un PDF
 * contaba dos veces y las actas no generan ningún archivo.
 */

function fila(acta: string): FilaDeActa {
  return {
    archivo: `${acta}.pdf`,
    acta,
    fecha: '17-12-2012',
    folio_inicial: 1,
    folio_final: 21,
    folios: 21,
    resumen: 'Sesionó el consejo.',
    observaciones: ''
  };
}

function acta(id: string): Job {
  return {
    id,
    batch_id: null,
    filename: `${id}.pdf`,
    bytes: 100,
    operator: 'siar',
    task: 'inventory_file',
    state: 'done',
    created_at: '2026-10-05T10:00:00Z',
    started_at: '2026-10-05T10:00:00Z',
    finished_at: '2026-10-05T10:00:03Z',
    error: null,
    report: { document: `${id}.pdf`, page_count: 22, inventario_actas: [fila(id)] },
    progress: {
      stage: 'done',
      page_count: 22,
      pages_done: 22,
      failed_pages: 0,
      by_provenance: { text_layer: 21, ocr_full_page: 1 },
      ribbon: 'f' + 't'.repeat(21),
      percent: 100,
      pages_per_second: 7,
      elapsed_seconds: 3
    }
  } as Job;
}

describe('un acta cuenta como acta', () => {
  it('se cuentan las actas inventariadas y se llaman actas', () => {
    const informe = summarise('carpeta:r1', 'carpeta', 'UPD3859771', [acta('a'), acta('b')]);

    expect(informe.resolutions).toBe(2);
    expect(informe.actas).toBe(2);
    expect(informe.unidad).toEqual(['acta', 'actas']);
    expect(informe.items.map((item) => item.resolutions)).toEqual([1, 1]);
  });

  it('cómo se leyó cada página sale de la cinta cuando el informe no lo trae', () => {
    const informe = summarise('doc:a', 'documento', 'a.pdf', [acta('a')]);

    expect(informe.provenance).toEqual({ text_layer: 21, ocr_full_page: 1 });
  });
});

describe('el título de una tanda dice qué trae', () => {
  const parte = (kind: Completion['kind'], title: string) =>
    ({ ...summarise(`${kind}:${title}`, kind, title, []), kind, title }) as Completion;

  it('una carpeta y un documento', () => {
    expect(describir([parte('carpeta', 'UPD3859771'), parte('documento', 'x.pdf')])).toBe(
      'Carpeta UPD3859771 y 1 documento'
    );
  });

  it('muchas carpetas se cuentan', () => {
    const tres = ['A', 'B', 'C'].map((nombre) => parte('carpeta', nombre));
    expect(describir(tres)).toBe('3 carpetas');
  });

  it('al juntar, las entregas de cada carpeta se conservan', () => {
    const carpeta = parte('carpeta', 'UPD3859771');
    carpeta.entregas = [
      {
        nombre: 'UPD3859771',
        origen: 'C:/FUENTE/UPD3859771',
        destino: 'C:/DESTINO',
        archivos: 0,
        inventarioDe: 'r1',
        inventario: 'ACTAS UPD3859771__inventario.xlsx'
      }
    ];
    const tanda = merge([carpeta, parte('documento', 'x.pdf')]);

    expect(tanda.title).toBe('Carpeta UPD3859771 y 1 documento');
    expect(tanda.entregas).toHaveLength(1);
  });
});
