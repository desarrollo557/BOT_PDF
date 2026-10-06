import { describe, expect, it } from 'vitest';
import {
  apply,
  byDay,
  EMPTY_FILTERS,
  fromHistory,
  fromJob,
  reunir,
  toggleMany,
  unidades
} from './archive.svelte';
import type { Entry } from './components/ProcessedCard.svelte';
import type { Job, Origen, ProcessedDocument } from './types';

/**
 * Lo que vino de una carpeta local o de un lote se ve como una sola tarjeta.
 *
 * Antes cada PDF de la carpeta era una tarjeta con forma de carpeta y el nombre
 * del archivo, y el operador no encontraba la carpeta raíz por ningún lado.
 */

const CARPETA: Origen = { id: 'run1', nombre: 'UPD3859771', tipo: 'carpeta' };

function entry(overrides: Partial<Entry> = {}): Entry {
  return {
    key: 'k',
    jobId: 'j',
    name: 'suelto.pdf',
    at: Date.now(),
    resolutions: 1,
    pages: 4,
    bytes: 100,
    review: 0,
    operator: 'Ana',
    codes: [],
    failed: false,
    error: null,
    live: false,
    origen: null,
    ...overrides
  };
}

const deLaCarpeta = (n: number, extra: Partial<Entry> = {}) =>
  entry({ key: `c${n}`, jobId: `c${n}`, name: `${n}N° acta.pdf`, origen: CARPETA, ...extra });

describe('reunir por carpeta', () => {
  it('los PDF de una carpeta forman una tarjeta con el nombre de la carpeta raíz', () => {
    const items = reunir([deLaCarpeta(1), deLaCarpeta(2), entry({ key: 's', jobId: 's' })]);

    const grupo = items.find((item) => item.kind === 'grupo');
    expect(items).toHaveLength(2);
    expect(grupo?.kind === 'grupo' && grupo.grupo.origen.nombre).toBe('UPD3859771');
  });

  it('suma lo de sus PDF y los ordena como en la carpeta', () => {
    const [item] = reunir([
      deLaCarpeta(10, { pages: 3, review: 1 }),
      deLaCarpeta(2, { pages: 5 }),
      deLaCarpeta(1, { pages: 2, failed: true })
    ]);

    if (item.kind !== 'grupo') throw new Error('debía ser una carpeta');
    expect(item.grupo.entries.map((e) => e.name)).toEqual([
      '1N° acta.pdf',
      '2N° acta.pdf',
      '10N° acta.pdf'
    ]);
    expect([item.grupo.pages, item.grupo.review, item.grupo.failed]).toEqual([10, 1, 1]);
  });

  it('una carpeta va entera en el día en que terminó', () => {
    const ayer = Date.now() - 86_400_000;
    const days = byDay([deLaCarpeta(1, { at: ayer }), deLaCarpeta(2)], 'reciente');

    expect(days).toHaveLength(1);
    expect(days[0].items).toHaveLength(1);
    expect(days[0].documents).toBe(2);
  });

  it('el buscador encuentra los PDF por el nombre de la carpeta', () => {
    const vivos = [deLaCarpeta(1, { live: true }), entry({ key: 's', live: true })];

    expect(apply(vivos, { ...EMPTY_FILTERS, text: 'upd3859771' })).toHaveLength(1);
  });
});

describe('de dónde sale el origen', () => {
  it('del trabajo en pantalla', () => {
    const job = { id: 'j1', filename: '1N°22.pdf', origen: CARPETA, state: 'done' } as Job;

    expect(fromJob(job).origen?.nombre).toBe('UPD3859771');
  });

  it('del inventario', () => {
    const fila = {
      job_id: 'j1',
      source_document: '1N°22.pdf',
      processed_at: '2026-10-05T10:00:00Z',
      resolutions: 1,
      pages: 4,
      codes: [],
      operator: null,
      source_pages: 4,
      bytes: 0,
      review: 0,
      origen_id: 'run1',
      origen: 'UPD3859771',
      origen_tipo: 'carpeta'
    } as ProcessedDocument;

    expect(fromHistory(fila).origen).toMatchObject({ id: 'run1', nombre: 'UPD3859771' });
    expect(fromHistory({ ...fila, origen_id: null }).origen).toBeNull();
  });
});

describe('marcar una carpeta entera', () => {
  it('marca los que faltan y, si ya estaban todos, los quita', () => {
    const una = toggleMany(new Set(['a']), ['a', 'b']);
    expect([...una].sort()).toEqual(['a', 'b']);
    expect([...toggleMany(una, ['a', 'b'])]).toEqual([]);
  });
});

describe('cómo se llaman las unidades', () => {
  it('según el papel', () => {
    expect(unidades(['ACTA DE CONSEJO'], true)).toBe('Actas');
    expect(unidades(['Resolución rectoral'])).toBe('Resoluciones');
    expect(unidades([])).toBe('Resoluciones');
    expect(unidades(['FACTURA', 'RECLAMO'])).toBe('Documentos');
  });
});
