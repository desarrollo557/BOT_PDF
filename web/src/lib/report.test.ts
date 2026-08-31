import { describe, expect, it } from 'vitest';
import { merge, Reports, summarise } from './report.svelte';
import type { Job } from './types';

/**
 * When a completion report is allowed to interrupt.
 *
 * The rule is narrow on purpose: a modal may only appear for work this tab
 * watched go from in flight to settled. The service keeps finished runs in
 * memory, so every reload re-delivers them as "done" -- and without this rule a
 * refresh popped a report for work that had finished an hour earlier.
 */

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: 'job-1',
    batch_id: null,
    filename: 'expediente.pdf',
    bytes: 1024,
    operator: null,
    state: 'done',
    created_at: '2026-08-31T12:00:00Z',
    started_at: '2026-08-31T12:00:00Z',
    finished_at: '2026-08-31T12:00:10Z',
    error: null,
    report: {
      document: 'expediente.pdf',
      page_count: 7,
      groups: [{ code: '00086', title: 'Acta', pages: [1, 2], size: 2 }],
      quarantine: [],
      repairs: [],
      review_queue: [],
      outputs: ['00086__acta.pdf'],
      stats: {
        by_provenance: { text_layer: 7 },
        escalated: 0,
        vision_requests: 0,
        resolved_by_context: 0,
        vision_page_ratio: 0,
        failed_pages: {}
      },
      inventory: null
    },
    progress: {
      stage: 'done',
      page_count: 7,
      pages_done: 7,
      failed_pages: 0,
      by_provenance: {},
      ribbon: 'ttttttt',
      percent: 100,
      pages_per_second: 1,
      elapsed_seconds: 7
    },
    ...overrides
  };
}

describe('cuándo se levanta un informe', () => {
  it('no interrumpe por trabajo que ya estaba terminado al conectar', () => {
    // Exactly the reported bug: reload the page, the service replays a run it
    // finished long ago, and a modal appears out of nowhere.
    const reports = new Reports();

    reports.register(summarise('carpeta:abc', 'carpeta', 'C:/entrada', [job()]));

    expect(reports.showing).toBeNull();
    expect(reports.history).toHaveLength(1);
  });

  it('interrumpe por trabajo que esta pestaña vio correr', () => {
    const reports = new Reports();

    reports.watch('carpeta:abc');
    reports.register(summarise('carpeta:abc', 'carpeta', 'C:/entrada', [job()]));
    reports.settle(false);

    expect(reports.showing?.id).toBe('carpeta:abc');
  });

  it('no levanta el mismo informe dos veces', () => {
    // Frames keep arriving after a run settles; the report is raised once.
    const reports = new Reports();
    reports.watch('doc:1');
    reports.register(summarise('doc:1', 'documento', 'a.pdf', [job()]));
    reports.settle(false);
    reports.close();
    reports.register(summarise('doc:1', 'documento', 'a.pdf', [job()]));
    reports.settle(false);

    expect(reports.showing).toBeNull();
    expect(reports.history).toHaveLength(1);
  });

  it('archiva en silencio lo viejo y sólo anuncia lo nuevo', () => {
    const reports = new Reports();
    reports.register(summarise('doc:viejo', 'documento', 'viejo.pdf', [job()]));

    reports.watch('doc:nuevo');
    reports.register(
      summarise('doc:nuevo', 'documento', 'nuevo.pdf', [job({ id: 'job-2' })])
    );
    reports.settle(false);

    expect(reports.showing?.id).toBe('doc:nuevo');
    expect(reports.history.map((item) => item.id)).toEqual(['doc:nuevo', 'doc:viejo']);
  });

  it('un informe archivado se puede reabrir a mano', () => {
    const reports = new Reports();
    reports.register(summarise('doc:1', 'documento', 'a.pdf', [job()]));

    reports.open('doc:1');

    expect(reports.showing?.id).toBe('doc:1');
  });
});

describe('lo que dice el informe', () => {
  it('suma lo que realmente pasó', () => {
    const completion = summarise('lote:1', 'lote', 'Lote', [
      job(),
      job({ id: 'job-2', bytes: 2048 })
    ]);

    expect(completion.documents).toBe(2);
    expect(completion.pages).toBe(14);
    expect(completion.resolutions).toBe(2);
    expect(completion.bytes).toBe(3072);
    expect(completion.elapsedSeconds).toBe(10);
  });

  it('cuenta los documentos que fallaron aparte', () => {
    const completion = summarise('lote:1', 'lote', 'Lote', [
      job(),
      job({ id: 'job-2', state: 'failed', report: null, error: 'boom' })
    ]);

    expect(completion.documents).toBe(2);
    expect(completion.failedDocuments).toBe(1);
    expect(completion.pages).toBe(7);
  });

  it('no inventa cifras cuando los documentos ya no están', () => {
    // The honest zero. The page that builds a folder report is responsible for
    // filling these from the run's own totals; what must never happen is a
    // number that looks real and is not.
    const completion = summarise('carpeta:1', 'carpeta', 'C:/entrada', []);

    expect(completion.documents).toBe(0);
    expect(completion.pages).toBe(0);
    expect(completion.bytes).toBe(0);
    expect(completion.elapsedSeconds).toBe(0);
  });

  it('lleva el operador que hizo el trabajo', () => {
    const completion = summarise('doc:1', 'documento', 'a.pdf', [
      job({ operator: 'María Martínez' })
    ]);
    expect(completion.operator).toBe('María Martínez');
  });
});

describe('un solo informe por tanda, no uno por archivo', () => {
  /**
   * The reported annoyance: attach twenty files, and the first one to finish
   * raises a modal over a queue that is still running. Closing it only lets the
   * next one through.
   */
  function terminado(reports: Reports, id: string, filename: string) {
    reports.watch(id);
    reports.register(
      summarise(id, 'documento', filename, [job({ id: `${id}-job`, filename })])
    );
  }

  it('no interrumpe mientras el resto de la cola sigue corriendo', () => {
    const reports = new Reports();

    terminado(reports, 'doc:1', 'uno.pdf');
    reports.settle(true);
    terminado(reports, 'doc:2', 'dos.pdf');
    reports.settle(true);

    expect(reports.showing).toBeNull();
  });

  it('al terminar todo levanta un único informe con el total', () => {
    const reports = new Reports();

    terminado(reports, 'doc:1', 'uno.pdf');
    terminado(reports, 'doc:2', 'dos.pdf');
    terminado(reports, 'doc:3', 'tres.pdf');
    reports.settle(true);
    reports.settle(false);

    expect(reports.showing?.kind).toBe('tanda');
    expect(reports.showing?.documents).toBe(3);
    expect(reports.showing?.pages).toBe(21);
    expect(reports.showing?.resolutions).toBe(3);
    expect(reports.showing?.parts).toHaveLength(3);
    // Cada archivo sigue entero en el detalle: la tanda resume, no reemplaza.
    expect(reports.showing?.items.map((item) => item.filename)).toEqual([
      'uno.pdf',
      'dos.pdf',
      'tres.pdf'
    ]);
  });

  it('un solo archivo se muestra tal cual, sin envolverlo en una tanda', () => {
    const reports = new Reports();

    terminado(reports, 'doc:1', 'uno.pdf');
    reports.settle(false);

    expect(reports.showing?.kind).toBe('documento');
    expect(reports.showing?.title).toBe('uno.pdf');
  });

  it('el reloj de la tanda es el que vio la persona, no la suma de los tramos', () => {
    // Tres documentos de diez segundos procesados a la vez duraron diez
    // segundos, no treinta.
    const base = Date.parse('2026-08-31T12:00:10Z');
    const uno = summarise('doc:1', 'documento', 'uno.pdf', [job()]);
    const dos = summarise('doc:2', 'documento', 'dos.pdf', [job({ id: 'job-2' })]);

    const tanda = merge([uno, dos]);

    expect(uno.elapsedSeconds).toBe(10);
    expect(tanda.elapsedSeconds).toBe(10);
    expect(tanda.finishedAt).toBe(base);
  });
});
