import type { FilaDeActa, Job } from './types';

/**
 * Dónde acabó archivada una página que hay que revisar.
 *
 * Es la mitad que le faltaba a la pantalla de revisión. Saber que la página 111
 * de un expediente de 222 tiene un problema no sirve de nada si para verla hay
 * que adivinar cuál de los veintinueve PDF se la llevó. Con el archivo delante,
 * abrirla es un clic.
 *
 * Se busca en tres sitios, de más preciso a menos. El inventario del trabajo es
 * el único que sabe cómo se llama el archivo en el disco, así que manda. Si el
 * documento no llegó a inventariarse queda el grupo, que al menos dice a qué
 * unidad documental pertenece la página. Y una página en cuarentena no está en
 * ninguna de las dos: tiene su propio archivo, con un nombre fijo.
 */
export interface Landing {
  /** El PDF que contiene la página, tal como se llama en el disco. */
  file: string | null;
  /** El número de la unidad documental que se llevó la página. */
  code: string | null;
}

export const QUARANTINE_FILE = '_quarantine.pdf';

export function whereItLanded(job: Job, page: number): Landing {
  const report = job.report;
  if (!report) return { file: null, code: null };

  if (report.quarantine?.includes(page)) {
    return { file: QUARANTINE_FILE, code: null };
  }

  const entry = report.inventory?.items?.find((item) => item.page_numbers.includes(page));
  if (entry) return { file: entry.file_name, code: entry.code };

  // Las historias académicas: el PDF del estudiante cuyas páginas la traen. Sus
  // grupos no dicen páginas, y buscarlas en ellos rompía la pantalla (2026-11-17).
  const fila = report.inventario_actas?.find(
    (candidata) =>
      candidata.pagina_inicial !== undefined &&
      candidata.pagina_inicial <= page &&
      page <= (candidata.pagina_final ?? candidata.pagina_inicial)
  );
  if (fila?.archivo_generado) {
    const salida = report.outputs?.find((ruta) => ruta.split('/').pop() === fila.archivo_generado) ?? null;
    return { file: salida, code: fila.archivo_generado };
  }

  const group = report.groups?.find((candidate) => candidate.pages?.includes(page));
  return { file: null, code: group?.code ?? null };
}

/** Los estados de un nombre que la Revisión enseña: los que no aseguró la máquina. */
const POR_MIRAR = new Set(['duda', 'corregido']);

/** Un estudiante cuyo nombre conviene mirar, con su trabajo. */
export interface NombrePorMirar {
  job: Job;
  fila: FilaDeActa;
}

/**
 * Los estudiantes de historias académicas cuyo nombre la máquina no aseguró:
 * los que las lecturas no confirmaron («duda») y los que cambió la IA
 * («corregido»). Los dudosos primero, y luego en el orden del PDF.
 *
 * El operador (2026-11-17): «la idea es tener los nombres de manera correcta».
 */
export function nombresPorMirar(jobs: Job[]): NombrePorMirar[] {
  const salida: NombrePorMirar[] = [];
  for (const job of jobs) {
    for (const fila of job.report?.inventario_actas ?? []) {
      const estado = fila.revision_del_nombre?.estado;
      if (estado && POR_MIRAR.has(estado) && fila.pagina_inicial !== undefined) salida.push({ job, fila });
    }
  }
  return salida.sort(
    (a, b) =>
      Number(b.fila.revision_del_nombre?.estado === 'duda') - Number(a.fila.revision_del_nombre?.estado === 'duda') ||
      a.job.filename.localeCompare(b.job.filename) ||
      (a.fila.pagina_inicial ?? 0) - (b.fila.pagina_inicial ?? 0)
  );
}
