import { describe, expect, it } from 'vitest';
import { pendientes, resueltos } from './pendientes';

describe('la Revisión que el agente ya resolvió (2026-11-23)', () => {
  const report = {
    review_queue: [
      { page: 1, reason: 'RE por confirmar: RE2310202408877', resuelto: { accion: 'decidido por el agente', conclusion: 'puso RE2310202408877' } },
      { page: 3, reason: 'la fecha del documento no se pudo leer' }
    ]
  };

  it('sólo espera a una persona lo que el agente no resolvió', () => {
    expect(pendientes(report).map((a) => a.page)).toEqual([3]);
    expect(resueltos(report).map((a) => a.page)).toEqual([1]);
  });

  it('un informe sin cola no tiene nada pendiente', () => {
    expect(pendientes(null)).toEqual([]);
    expect(pendientes({})).toEqual([]);
  });
});

describe('los RE decididos con confianza baja, para auditar (2026-11-23)', () => {
  it('salen los de confianza baja y los revertidos, no los confirmados ni los de confianza media', async () => {
    const { reDecididosPorAuditar } = await import('./revision');
    const decision = (pagina: number, extra: Record<string, unknown>) => ({
      page: pagina, valor: 'RE2310202408877', regla: 'el más votado', confianza: 'baja', por_que: 'leído', auditor: 'verificada por el auditor',
      opciones: ['RE2310202408877', 'RE2310202408897'], ...extra
    });
    const job = {
      id: 'j1', filename: 'UPD1.pdf',
      report: {
        decisiones_del_agente: [
          decision(1, {}),
          decision(2, { confianza: 'media' }),
          decision(3, { valor: null }),
          decision(4, { auditor: 'confirmado por el operador' })
        ]
      }
    } as never;
    const guardado = { job_id: 'j2', documento: 'UPD2.pdf', pagina: 5, motivo: 'm', candidatos: [], valor: null, archivo: null };
    const salida = reDecididosPorAuditar([job], [guardado]);
    expect(salida.map((r) => `${r.jobId}:${r.pagina}`)).toEqual(['j1:1', 'j1:3', 'j2:5']);
    expect(salida[0].candidatos.map((c) => c.valor)).toEqual(['RE2310202408877', 'RE2310202408897']);
  });
});
