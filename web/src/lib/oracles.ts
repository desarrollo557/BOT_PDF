import type { Health } from './api';

/**
 * A qué modelo se le pide juzgar los bordes que la estructura no pudo decidir.
 *
 * Una caja de correspondencia se corta por continuidad, y las costuras que la
 * estructura no puede resolver sola son las que valen una llamada a un modelo.
 * Cuál modelo dejó de ser una consecuencia de qué llave hay puesta en el
 * servidor: es una decisión del operador, porque comparar dos modelos sobre la
 * misma caja es lo único que dice en cuál confiar.
 */
export type OracleChoice = 'auto' | 'claude' | 'gemini' | 'mistral';

export interface OracleOption {
  id: OracleChoice;
  label: string;
  hint: string;
  /** Si el servicio declara tener llave para pedirlo. */
  available: boolean;
  /**
   * Por qué no se puede pedir, para decirlo en vez de apagar el botón sin
   * explicación. `null` cuando sí se puede.
   */
  reason: string | null;
}

/** El orden en que se ofrecen, que es el de la cascada del servicio. */
const CATALOG: { id: OracleChoice; label: string; hint: string }[] = [
  {
    id: 'auto',
    label: 'Automático',
    hint: 'el que el servicio tenga configurado'
  },
  {
    id: 'claude',
    label: 'Claude Haiku',
    hint: 'cachea las instrucciones; la caja las paga una vez'
  },
  {
    id: 'gemini',
    label: 'Gemini Flash',
    hint: 'capa gratuita que aguanta una caja entera'
  },
  {
    id: 'mistral',
    label: 'Mistral Small',
    hint: 'tercera opinión sobre las mismas costuras'
  }
];

const SIN_LLAVE = 'No hay llave configurada para este modelo en el servicio.';

const SIN_SERVICIO =
  'El servicio no informó qué modelos tiene disponibles. Puede pedirse el automático.';

/**
 * Los modelos que la pantalla puede ofrecer, con el motivo de los que no.
 *
 * `null` es el servicio que no contestó, y un servicio anterior a la revisión 17
 * no declara `oracles`. Los dos casos son el mismo: no se sabe qué llaves hay, y
 * no saber no es lo mismo que no haber. Se ofrece el automático -- que siempre se
 * puede pedir, porque sin ninguna llave la caja se separa igual por todo lo que
 * la estructura decide sola -- y se dice por qué los demás están apagados.
 *
 * Nunca se adivina disponibilidad: ofrecer un modelo que no se puede pedir gasta
 * la decisión del operador y la contesta con un 422 cuando ya eligió el archivo.
 */
export function oracleOptions(health: Health | null): OracleOption[] {
  const declared = health?.oracles ?? null;
  return CATALOG.map((entry) => {
    if (entry.id === 'auto') {
      return { ...entry, available: true, reason: null };
    }
    if (!declared) {
      return { ...entry, available: false, reason: SIN_SERVICIO };
    }
    const available = declared[entry.id] === true;
    return { ...entry, available, reason: available ? null : SIN_LLAVE };
  });
}

/**
 * Por qué no se puede pedir lo que está elegido, o `null` si sí se puede.
 *
 * Lo usa el panel para negarse a subir en vez de mandar una elección imposible.
 * El servicio la rechazaría con 422 igual, pero después de recibir el archivo:
 * una caja escaneada son cientos de megabytes y el operador ya había decidido.
 */
export function reasonFor(choice: OracleChoice, options: OracleOption[]): string | null {
  const option = options.find((candidate) => candidate.id === choice);
  if (!option) return SIN_SERVICIO;
  return option.available ? null : option.reason;
}
