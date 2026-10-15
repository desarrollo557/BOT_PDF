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
export type LecturaChoice = 'local' | 'mistral' | 'mistral-nombres';

export interface LecturaOption {
  id: LecturaChoice;
  label: string;
  hint: string;
  /** Si el servicio declara tener llave para pedirlo. */
  available: boolean;
  /** Por qué no se puede pedir, o `null` cuando sí. */
  reason: string | null;
}

/**
 * Las dos formas de leer, dichas como las dice quien tiene la caja delante.
 *
 * Los nombres de producto -- Tesseract, Mistral -- se quedaron fuera a
 * propósito: no le dicen nada al operador, y elegir mal aquí no se nota hasta
 * que la carpeta de salida ya está escrita y sin una sola cédula. Lo que sí
 * sabe contestar es si su papel está mecanografiado o escrito a mano, y eso es
 * lo único que hace falta para elegir.
 */
const CATALOG: { id: LecturaChoice; label: string; hint: string }[] = [
  {
    id: 'local',
    label: 'Solo OCR',
    hint: 'gratis: ninguna IA. Lee lo impreso y lo mecanografiado; lo dudoso va a revisión'
  },
  {
    id: 'mistral',
    label: 'OCR + IA',
    hint: 'la IA sólo donde el OCR no alcanza, y se paga por página: lo escrito a mano, las costuras dudosas'
  },
  {
    id: 'mistral-nombres',
    label: 'OCR + IA (ahorro)',
    hint: 'diez caras por página facturada. Lee sólo el nombre, no el folio ni la fecha'
  }
];

const SIN_LLAVE =
  'La ayuda de IA no está configurada en el servicio: falta su llave. Se puede leer con «Solo OCR».';

const SIN_SERVICIO =
  'El servicio no informó con qué puede leer. Puede pedirse «Solo OCR», que siempre está.';

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
    // Un servicio anterior a esta revisión no declara la lectura de ahorro, y no
    // declararla es no tenerla: pedirla ahí devolvería un 422 con el archivo ya
    // subido. Se apaga y se dice por qué, como con cualquier otra.
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
