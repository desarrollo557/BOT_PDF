export interface Pregunta {
  /** Lo que se va a hacer, como pregunta: «¿Cancelar el procesamiento?». */
  titulo: string;
  /** Qué pasa si se acepta, y sobre todo qué no se puede deshacer. */
  mensaje?: string;
  /** El botón que acepta, con el verbo de la acción: «Cancelar», «Eliminar». */
  aceptar?: string;
  /** El que se arrepiente. */
  volver?: string;
  /** Si la acción destruye algo: el botón sale en rojo. */
  peligro?: boolean;
}

interface Pendiente extends Pregunta {
  responder: (si: boolean) => void;
}

/**
 * La pregunta que se le hace al operador antes de eliminar o cancelar.
 *
 * Una sola a la vez y montada una sola vez, en el layout: así cualquier botón
 * de cualquier pantalla pregunta igual, con `await confirmar({...})`, sin
 * traer su propio diálogo.
 */
class Confirmacion {
  actual = $state<Pendiente | null>(null);

  preguntar(pregunta: Pregunta): Promise<boolean> {
    // Una pregunta nueva sobre otra sin contestar cuenta la anterior como un no.
    this.actual?.responder(false);
    return new Promise((resolver) => {
      this.actual = {
        ...pregunta,
        responder: (si) => {
          this.actual = null;
          resolver(si);
        }
      };
    });
  }

  responder(si: boolean): void {
    this.actual?.responder(si);
  }
}

export const confirmacion = new Confirmacion();

/** `true` si el operador aceptó. */
export function confirmar(pregunta: Pregunta): Promise<boolean> {
  return confirmacion.preguntar(pregunta);
}
