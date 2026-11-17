import type { FilaConPersona, Job, NombreGuardado } from './types';

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

/** Una persona cuyo nombre conviene mirar, con su trabajo. */
export interface NombrePorMirar {
  jobId: string;
  /** El documento del trabajo, como lo reconoce el operador. */
  documento: string;
  fila: FilaConPersona;
  /** Su número en las filas del informe, de 1 en adelante: con él se pide su renglón y se corrige. */
  numero: number;
  /** Si viene de lo guardado en disco y no de un trabajo en memoria (2026-11-17). */
  guardado?: boolean;
}

/**
 * Las filas del informe en que puede haber una persona, numeradas como las
 * numera el servidor (`filas_de_personas` en `routers/nombres.py`): primero las
 * de actas (historias, nóminas, certificados, actas de grado) y después las del
 * FUID ya hecho (libros de diplomas, legajos de matrículas).
 */
function filasDePersonas(job: Job): FilaConPersona[] {
  return [...(job.report?.inventario_actas ?? []), ...(job.report?.filas_del_fuid ?? [])];
}

/**
 * Las personas, de cualquier habilidad, cuyo nombre la máquina no aseguró:
 * los que las lecturas no confirmaron («duda») y los que cambió la IA
 * («corregido»). Los dudosos primero, y luego en el orden del PDF.
 *
 * El operador (2026-11-17): «la idea es tener los nombres de manera correcta».
 */
export function nombresPorMirar(jobs: Job[], guardados: NombreGuardado[] = []): NombrePorMirar[] {
  const salida: NombrePorMirar[] = [];
  const enMemoria = new Set<string>();
  for (const job of jobs) {
    if (job.report) enMemoria.add(job.id);
    filasDePersonas(job).forEach((fila, indice) => {
      const estado = fila.revision_del_nombre?.estado;
      if (estado && POR_MIRAR.has(estado)) {
        salida.push({ jobId: job.id, documento: job.filename, fila, numero: indice + 1 });
      }
    });
  }
  // Los de los trabajos que ya no están en memoria, como se guardaron (2026-11-17):
  // el que vuelve a estar en memoria se ve en vivo, no dos veces.
  for (const guardado of guardados) {
    const estado = guardado.fila.revision_del_nombre?.estado;
    if (enMemoria.has(guardado.job_id) || !estado || !POR_MIRAR.has(estado)) continue;
    salida.push({
      jobId: guardado.job_id,
      documento: guardado.documento,
      fila: guardado.fila,
      numero: guardado.numero,
      guardado: true
    });
  }
  return salida.sort(
    (a, b) =>
      Number(b.fila.revision_del_nombre?.estado === 'duda') - Number(a.fila.revision_del_nombre?.estado === 'duda') ||
      a.documento.localeCompare(b.documento) ||
      (a.fila.pagina_inicial ?? 0) - (b.fila.pagina_inicial ?? 0)
  );
}
