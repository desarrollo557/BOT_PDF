import type { Job } from './types';

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

  const group = report.groups?.find((candidate) => candidate.pages.includes(page));
  return { file: null, code: group?.code ?? null };
}
