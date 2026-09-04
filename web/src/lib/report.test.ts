import { describe, expect, it } from 'vitest';
import { merge, Reports, summarise, type Completion } from './report.svelte';
import { jobStore, mergeReviewable, pendingReview } from './jobs.svelte';
import type { FolderRun } from './types';
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
    task: 'split',
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

/**
 * El informe de un libro de folios no tiene la forma del de resoluciones.
 *
 * Un trabajo de inventario no agrupa por número heredado ni escribe salidas, así
 * que su informe no trae `groups`, `review_queue`, `repairs` ni `quarantine`.
 * La pantalla las leía a pelo y moría al terminar el documento: sin modal de
 * cierre, y con la barra de navegación caída detrás. El resumen tiene que
 * sobrevivir a un informe al que le falte cualquiera de esas claves.
 */
describe('un informe de inventario', () => {
  function inventario(): Job {
    return job({
      task: 'inventory',
      report: {
        document: 'REGISTRO DE DIPLOMAS N°08 2013.pdf',
        page_count: 287,
        document_type: 'diploma',
        document_type_label: 'Registro de diplomas',
        type_confidence: 1,
        records: 287,
        task: 'inventory'
      } as Job['report']
    });
  }

  it('no rompe el resumen aunque no traiga ninguna de las listas', () => {
    expect(() => summarise('doc:libro', 'documento', 'libro.pdf', [inventario()])).not.toThrow();
  });

  it('cuenta sus páginas y deja en cero lo que ese informe no mide', () => {
    const resumen = summarise('doc:libro', 'documento', 'libro.pdf', [inventario()]);
    expect(resumen.pages).toBe(287);
    expect(resumen.resolutions).toBe(0);
    expect(resumen.reviewItems).toBe(0);
  });

  it('convive con un informe de división en el mismo lote', () => {
    const resumen = summarise('lote:1', 'lote', 'caja 3269', [inventario(), job({ id: 'job-2' })]);
    expect(resumen.pages).toBe(294);
    expect(resumen.resolutions).toBe(1);
  });
});


/**
 * Cerrar el informe deja la pantalla lista para el siguiente lote. Siempre.
 *
 * Es lo que pidió el operador: procesa caja tras caja y no quiere empezar la
 * siguiente con las fichas de la anterior debajo. Lo que no puede pasar es que
 * al limpiar se lleve por delante lo que todavía hay que mirar, y por eso lo
 * pendiente se conserva aparte.
 */
describe('limpiar la pantalla al cerrar el informe', () => {
  function done(overrides: Partial<Job> = {}): Job {
    return job({ state: 'done', ...overrides });
  }

  it('conserva el documento que dejó páginas por revisar', () => {
    const conRevision = done({
      id: 'j2',
      report: { ...job().report!, review_queue: [{ page: 4, reason: 'folio ilegible' }] }
    });
    expect(pendingReview([done(), conRevision]).map((j) => j.id)).toEqual(['j2']);
  });

  it('conserva el documento que falló, por su mensaje de error', () => {
    const fallido = done({ id: 'j3', state: 'failed', error: 'PDF ilegible' });
    expect(pendingReview([done(), fallido]).map((j) => j.id)).toEqual(['j3']);
  });

  it('no conserva lo que salió limpio', () => {
    expect(pendingReview([done()])).toEqual([]);
  });

  it('Revisión ve lo vivo y lo apartado, sin repetir', () => {
    const vivo = done({ id: 'a' });
    const apartado = done({ id: 'b' });
    expect(mergeReviewable([vivo], [apartado, vivo]).map((j) => j.id)).toEqual(['a', 'b']);
  });

  it('el informe sobrevive a la limpieza', () => {
    // Limpiar olvida los trabajos, no los informes: se vuelve a abrir desde el
    // archivo, que es lo que el operador pidió que no se perdiera.
    const reports = new Reports();
    const completion: Completion = summarise('doc:1', 'documento', 'a.pdf', [job()]);
    reports.register(completion);
    reports.close();
    expect(reports.history).toHaveLength(1);
    reports.open(completion.id);
    expect(reports.showing?.id).toBe(completion.id);
  });
});


/**
 * Cuándo se borran las rutas del formulario de carpeta.
 *
 * Al cerrar el informe la pantalla se limpia, y unas rutas escritas encima de
 * una pantalla vacía se leen como si esa carpeta siguiera procesándose. Pero no
 * siempre hay que borrarlas: una carpeta vigilada sigue esperando archivos, y
 * el operador la quiere ahí.
 *
 * La regla no mira la casilla "Vigilar la carpeta" sino el estado real de la
 * corrida, que además acierta cuando la vigilancia se detuvo a mano.
 */
describe('el reinicio de la mesa de trabajo', () => {
  function run(state: FolderRun['state'], id: string): FolderRun {
    return {
      kind: 'folder_run',
      id,
      source: 'C:/entrada',
      destination: 'C:/salida',
      disposition: 'leave',
      watch: state === 'watching',
      operator: null,
      state,
      started_at: '2026-09-01T12:00:00Z',
      finished_at: null,
      error: null,
      queue: [],
      current: null,
      current_job_id: null,
      job_ids: [],
      discovered: 2,
      processed: 2,
      bytes_total: 0,
      pages_total: 0,
      failed: 0,
      delivered: 0,
      resolutions: 0,
      deliveries: []
    };
  }

  it('una carpeta que terminó no deja nada activo, así que se reinicia', () => {
    jobStore.runs = [run('done', 'a')];
    expect(jobStore.activeRuns).toEqual([]);
  });

  it('una carpeta detenida a mano tampoco', () => {
    jobStore.runs = [run('stopped', 'a')];
    expect(jobStore.activeRuns).toEqual([]);
  });

  it('una carpeta vigilando sigue activa, y las rutas se quedan', () => {
    jobStore.runs = [run('watching', 'a')];
    expect(jobStore.activeRuns.map((r) => r.id)).toEqual(['a']);
  });

  it('la señal de reinicio avisa de cada reinicio, no del estado', () => {
    // Dos tandas seguidas son dos avisos. Un booleano ya puesto en true no
    // avisaría del segundo.
    const antes = jobStore.resetSignal;
    jobStore.resetWorkspace();
    jobStore.resetWorkspace();
    expect(jobStore.resetSignal).toBe(antes + 2);
  });
});
