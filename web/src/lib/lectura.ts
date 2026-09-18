import type { Health } from './api';

/**
 * Con qué se transcribe el papel de este trabajo.
 *
 * No es lo mismo que elegir modelo en `oracles.ts`, y la diferencia importa al
 * elegir. Allí se decide quién juzga una costura que la estructura no pudo
 * resolver; acá, con qué se lee la imagen, que es el paso anterior a todo lo
 * demás. Un expediente mal leído no lo arregla ningún juez de costuras porque no
 * queda nada sobre lo que juzgar.
 *
 * Es opcional porque cuesta dinero y no siempre hace falta. Lo impreso lo lee
 * gratis el motor local; lo escrito a mano no lo lee, y en los libros de
 * registro antiguos todo lo que identifica al documento -- el folio, el nombre,
 * la cédula, el título, la fecha -- está escrito a mano sobre un formulario
 * impreso. Quién tiene delante cuál de los dos casos lo sabe el operador.
 */
export type LecturaChoice = 'local' | 'mistral';

export interface LecturaOption {
  id: LecturaChoice;
  label: string;
  hint: string;
  /** Si el servicio declara tener llave para pedirlo. */
  available: boolean;
  /** Por qué no se puede pedir, o `null` cuando sí. */
  reason: string | null;
}

const CATALOG: { id: LecturaChoice; label: string; hint: string }[] = [
  {
    id: 'local',
    label: 'Tesseract',
    hint: 'lo de siempre: gratis y suficiente para lo impreso'
  },
  {
    id: 'mistral',
    label: '+ Mistral OCR',
    hint: 'lee lo escrito a mano; se paga sólo lo que Tesseract no supo leer'
  }
];

const SIN_LLAVE = 'No hay llave de Mistral configurada en el servicio.';

const SIN_SERVICIO =
  'El servicio no informó con qué puede leer. Puede pedirse el motor local.';

/**
 * Los motores que la pantalla puede ofrecer, con el motivo de los que no.
 *
 * Mismo criterio que con los modelos: nunca se adivina disponibilidad. Ofrecer
 * un motor que no se puede pedir gasta la decisión del operador y la contesta
 * con un 422 cuando ya había elegido el archivo.
 */
export function lecturaOptions(health: Health | null): LecturaOption[] {
  const declared = health?.readers ?? null;
  return CATALOG.map((entry) => {
    if (entry.id === 'local') {
      return { ...entry, available: true, reason: null };
    }
    if (!declared) {
      return { ...entry, available: false, reason: SIN_SERVICIO };
    }
    const available = declared[entry.id] === true;
    return { ...entry, available, reason: available ? null : SIN_LLAVE };
  });
}

/** Por qué no se puede pedir lo que está elegido, o `null` si sí se puede. */
export function reasonForLectura(
  choice: LecturaChoice,
  options: LecturaOption[]
): string | null {
  const option = options.find((candidate) => candidate.id === choice);
  if (!option) return SIN_SERVICIO;
  return option.available ? null : option.reason;
}
