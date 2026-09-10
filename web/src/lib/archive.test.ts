import { describe, expect, it } from 'vitest';
import {
  apply,
  byDay,
  EMPTY_FILTERS,
  merge,
  operators,
  order,
  selectionTotals,
  toggle,
  toggleAll,
  visibleSelection
} from './archive.svelte';
import type { Entry } from './components/ProcessedCard.svelte';

/**
 * Filtering and ordering the archive.
 *
 * Pinned because this is what an operator uses to find one document among a few
 * thousand, and a filter that quietly drops a row is worse than no filter.
 */

const DAY = 86_400_000;

function entry(overrides: Partial<Entry> = {}): Entry {
  return {
    key: 'k',
    jobId: 'j',
    name: 'expediente.pdf',
    at: Date.now(),
    resolutions: 3,
    pages: 7,
    bytes: 1024,
    review: 0,
    operator: 'Ana',
    codes: ['00086'],
    failed: false,
    error: null,
    live: true,
    ...overrides
  };
}

describe('filtros', () => {
  it('sin filtros no quita nada', () => {
    expect(apply([entry(), entry({ key: 'b' })], EMPTY_FILTERS)).toHaveLength(2);
  });

  it('busca por nombre sin importar mayúsculas', () => {
    const entries = [
      entry({ name: 'RESOLUCIONES 00072.pdf', codes: [] }),
      entry({ key: 'b', name: 'otro.pdf', codes: [] })
    ];
    expect(apply(entries, { ...EMPTY_FILTERS, text: 'resoluciones' })).toHaveLength(1);
  });

  it('busca por número de resolución, no sólo por nombre', () => {
    // "00086" is at least as likely a search as a file name: it is the number
    // printed on the document. Searching it used to return nothing.
    const entries = [
      entry({ name: 'expediente.pdf', codes: ['00086', '00072'] }),
      entry({ key: 'b', name: 'otro.pdf', codes: ['00999'] })
    ];
    const found = apply(entries, { ...EMPTY_FILTERS, text: '00086' });
    expect(found).toHaveLength(1);
    expect(found[0].key).toBe('k');
  });

  it('busca también por operador', () => {
    // "Cualquier parámetro relacionado", que es como lo pidió el operador: el
    // nombre del PDF, los números que produjo y quién lo procesó.
    const entries = [
      entry({ operator: 'Eduver Andrés' }),
      entry({ key: 'b', operator: 'Ana', codes: [] })
    ];
    const found = apply(entries, { ...EMPTY_FILTERS, text: 'eduver' });
    expect(found).toHaveLength(1);
    expect(found[0].key).toBe('k');
  });

  it('varias palabras se exigen todas, en cualquier dato', () => {
    // Es lo que permite acotar con una sola caja de texto: "eduver 00086"
    // encuentra lo que procesó esa persona con ese número, sin que los dos
    // términos tengan que estar en el mismo campo.
    const entries = [
      entry({ name: 'caja 12.pdf', operator: 'Eduver', codes: ['00086'] }),
      entry({ key: 'b', name: 'caja 12.pdf', operator: 'Ana', codes: ['00086'] })
    ];
    const found = apply(entries, { ...EMPTY_FILTERS, text: 'eduver 00086' });
    expect(found).toHaveLength(1);
    expect(found[0].key).toBe('k');
  });

  it('las tildes no hacen falta para encontrar algo', () => {
    // El OCR las pone y las quita a su antojo, y quien busca no va a
    // escribirlas dos veces.
    const acentuado = entry({ name: 'NOTIFICACIÓN.pdf', codes: [] });
    expect(apply([acentuado], { ...EMPTY_FILTERS, text: 'notificacion' })).toHaveLength(1);
    expect(apply([acentuado], { ...EMPTY_FILTERS, text: 'NOTIFICACIÓN' })).toHaveLength(1);
  });

  it('lo archivado no se vuelve a filtrar por texto', () => {
    // The service already searched the whole ledger for it -- every code and
    // title, not the few a card carries. Filtering again here would drop rows
    // the search legitimately found.
    const archived = entry({ live: false, name: 'expediente.pdf', codes: [] });
    expect(apply([archived], { ...EMPTY_FILTERS, text: 'algo que no está' })).toHaveLength(1);
  });

  it('pero un documento vivo que no coincide sí se descarta', () => {
    const live = entry({ live: true, name: 'expediente.pdf', codes: ['00086'] });
    expect(apply([live], { ...EMPTY_FILTERS, text: 'zzz' })).toHaveLength(0);
  });

  it('el período recorta por fecha', () => {
    const entries = [entry(), entry({ key: 'b', at: Date.now() - 10 * DAY })];
    expect(apply(entries, { ...EMPTY_FILTERS, period: 'hoy' })).toHaveLength(1);
    expect(apply(entries, { ...EMPTY_FILTERS, period: 'mes' })).toHaveLength(2);
  });

  it('filtra por operador', () => {
    const entries = [entry(), entry({ key: 'b', operator: 'Beto' })];
    expect(apply(entries, { ...EMPTY_FILTERS, operator: 'Beto' })[0].operator).toBe('Beto');
  });

  it('aísla lo que necesita revisión', () => {
    const entries = [entry(), entry({ key: 'b', review: 4 })];
    expect(apply(entries, { ...EMPTY_FILTERS, status: 'revision' })).toHaveLength(1);
    expect(apply(entries, { ...EMPTY_FILTERS, status: 'limpios' })).toHaveLength(1);
  });

  it('aísla los que fallaron', () => {
    const entries = [entry(), entry({ key: 'b', failed: true })];
    expect(apply(entries, { ...EMPTY_FILTERS, status: 'fallidos' })).toHaveLength(1);
  });

  it('un documento fallido no cuenta como limpio', () => {
    expect(apply([entry({ failed: true })], { ...EMPTY_FILTERS, status: 'limpios' })).toHaveLength(
      0
    );
  });

  it('los filtros se combinan', () => {
    const entries = [
      entry({ name: 'marzo.pdf', operator: 'Ana', review: 2 }),
      entry({ key: 'b', name: 'marzo.pdf', operator: 'Beto', review: 2 }),
      entry({ key: 'c', name: 'abril.pdf', operator: 'Ana', review: 2 })
    ];
    const found = apply(entries, {
      ...EMPTY_FILTERS,
      text: 'marzo',
      operator: 'Ana',
      status: 'revision'
    });
    expect(found).toHaveLength(1);
    expect(found[0].key).toBe('k');
  });
});

describe('orden', () => {
  const older = entry({
    key: 'viejo',
    at: Date.now() - DAY,
    resolutions: 40,
    pages: 300,
    name: 'z.pdf'
  });
  const newer = entry({ key: 'nuevo', at: Date.now(), resolutions: 2, pages: 5, name: 'a.pdf' });

  it('reciente primero por defecto', () => {
    expect(order([older, newer], 'reciente')[0].key).toBe('nuevo');
  });

  it('antiguo primero cuando se pide', () => {
    expect(order([older, newer], 'antiguo')[0].key).toBe('viejo');
  });

  it('por cantidad de resoluciones', () => {
    expect(order([newer, older], 'resoluciones')[0].key).toBe('viejo');
  });

  it('por cantidad de páginas', () => {
    expect(order([newer, older], 'paginas')[0].key).toBe('viejo');
  });

  it('por nombre, en español', () => {
    expect(order([older, newer], 'nombre')[0].name).toBe('a.pdf');
  });
});

describe('agrupación por día', () => {
  it('cada día lleva sus propios totales', () => {
    const days = byDay(
      [
        entry({ resolutions: 3, pages: 7, bytes: 100, review: 1 }),
        entry({ key: 'b', resolutions: 5, pages: 9, bytes: 200 })
      ],
      'reciente'
    );
    expect(days).toHaveLength(1);
    expect(days[0].documents).toBe(2);
    expect(days[0].resolutions).toBe(8);
    expect(days[0].pages).toBe(16);
    expect(days[0].bytes).toBe(300);
    expect(days[0].review).toBe(1);
  });

  it('hoy y ayer se nombran así', () => {
    const days = byDay([entry(), entry({ key: 'b', at: Date.now() - DAY })], 'reciente');
    expect(days.map((day) => day.label)).toEqual(['Hoy', 'Ayer']);
  });

  it('los días van de más nuevo a más viejo', () => {
    const days = byDay([entry({ at: Date.now() - 2 * DAY }), entry({ key: 'b' })], 'reciente');
    expect(days[0].label).toBe('Hoy');
  });

  it('pedir lo antiguo primero también invierte los días', () => {
    // Otherwise "oldest first" would still put today at the top, which is not
    // what anybody means by it.
    const days = byDay([entry({ at: Date.now() - 2 * DAY }), entry({ key: 'b' })], 'antiguo');
    expect(days[0].label).not.toBe('Hoy');
  });
});

describe('mezcla de lo vivo y lo archivado', () => {
  const job = {
    id: 'job-1',
    filename: 'a.pdf',
    bytes: 10,
    operator: 'Ana',
    state: 'done',
    created_at: '2026-08-31T12:00:00Z',
    finished_at: '2026-08-31T12:00:05Z',
    error: null,
    batch_id: null,
    report: {
      page_count: 7,
      groups: [{ code: '1', title: null, pages: [1], size: 1 }],
      review_queue: [],
      quarantine: [],
      repairs: [],
      outputs: [],
      document: 'a.pdf',
      stats: {} as never,
      inventory: null
    },
    progress: {} as never
  } as never;

  const history = {
    job_id: 'job-1',
    source_document: 'a.pdf',
    processed_at: '2026-08-31T12:00:05Z',
    resolutions: 1,
    pages: 7,
    codes: ['00086'],
    operator: 'Ana',
    source_pages: 7,
    bytes: 10,
    review: 0
  };

  it('un documento que está en los dos lados aparece una sola vez', () => {
    expect(merge([job], [history])).toHaveLength(1);
  });

  it('gana la versión viva, que es la que se puede abrir', () => {
    expect(merge([job], [history])[0].live).toBe(true);
  });

  it('lo que ya no está en memoria sigue apareciendo', () => {
    expect(merge([], [history])[0].live).toBe(false);
  });
});

describe('operadores', () => {
  it('se listan sin repetir y ordenados', () => {
    const found = operators([
      entry({ operator: 'Beto' }),
      entry({ key: 'b', operator: 'Ana' }),
      entry({ key: 'c', operator: 'Ana' }),
      entry({ key: 'd', operator: null })
    ]);
    expect(found).toEqual(['Ana', 'Beto']);
  });
});


/**
 * Seleccionar varios documentos para borrarlos de una vez.
 *
 * Borrar de a uno está bien para corregir un error; no lo está para vaciar una
 * caja mal procesada. Lo que se fija aquí son las reglas que evitan el
 * accidente, porque este botón no tiene deshacer.
 */
describe('la selección múltiple', () => {
  const uno = entry({ key: 'a', jobId: 'a', name: 'uno.pdf', resolutions: 3, pages: 7 });
  const dos = entry({ key: 'b', jobId: 'b', name: 'dos.pdf', resolutions: 5, pages: 11 });
  const tres = entry({ key: 'c', jobId: 'c', name: 'tres.pdf', resolutions: 1, pages: 2 });

  it('marca y desmarca uno', () => {
    const marcado = toggle(new Set<string>(), 'a');
    expect([...marcado]).toEqual(['a']);
    expect([...toggle(marcado, 'a')]).toEqual([]);
  });

  it('no muta la selección que recibe', () => {
    const antes = new Set(['a']);
    toggle(antes, 'b');
    expect([...antes]).toEqual(['a']);
  });

  it('marca todo lo visible de una vez', () => {
    const marcado = toggleAll(new Set<string>(), [uno, dos, tres]);
    expect([...marcado].sort()).toEqual(['a', 'b', 'c']);
  });

  it('vuelve a pulsar y lo desmarca todo', () => {
    const marcado = toggleAll(new Set<string>(), [uno, dos]);
    expect([...toggleAll(marcado, [uno, dos])]).toEqual([]);
  });

  it('marcar todo no toca lo que no se está viendo', () => {
    // "Todo" es siempre lo visible. Marcar por error los ochocientos documentos
    // del archivo es justamente el accidente que esto no debe permitir.
    const conFiltro = toggleAll(new Set(['z']), [uno]);
    expect([...conFiltro].sort()).toEqual(['a', 'z']);
  });

  it('sólo se borra lo que sigue a la vista', () => {
    // El operador marca tres, cambia el filtro, y pulsa eliminar. Una selección
    // que sobrevive a su propia lista es una forma de borrar a ciegas.
    const marcado = new Set(['a', 'b', 'c']);
    expect(visibleSelection(marcado, [uno, tres])).toEqual(['a', 'c']);
  });

  it('devuelve lo visible en el orden de la lista', () => {
    expect(visibleSelection(new Set(['c', 'a']), [uno, dos, tres])).toEqual(['a', 'c']);
  });

  it('cuenta lo que se va a borrar antes de borrarlo', () => {
    const totales = selectionTotals(new Set(['a', 'b']), [uno, dos, tres]);
    expect(totales).toEqual({ documents: 2, resolutions: 8, pages: 18 });
  });

  it('no cuenta lo que ya no está en la lista', () => {
    expect(selectionTotals(new Set(['a', 'z']), [uno]).documents).toBe(1);
  });
});
