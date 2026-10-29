/**
 * La pregunta de usuario y clave de una carpeta de red.
 *
 * Cuando el servicio contesta que «\\servidor\recurso» pide credenciales, el
 * cliente de la API (`pedir` en `api.ts`) llama a `pedirCredenciales`, que abre
 * el cuadro de `CredencialesDeRed.svelte` y espera la respuesta. Lo que se
 * escribe va al servicio y no se guarda en el navegador.
 */

export interface CuentaDeRed {
  usuario: string;
  clave: string;
}

interface Pregunta {
  recurso: string;
  mensaje: string;
  /** La cuenta con permiso en el recurso, si el servicio la sabe: se propone. */
  usuario?: string;
  responder: (cuenta: CuentaDeRed | null) => void;
}

class PreguntaDeRed {
  actual = $state<Pregunta | null>(null);
  #espera: Promise<CuentaDeRed | null> | null = null;

  /**
   * Abre el cuadro y devuelve lo que se escriba, o `null` si se cancela. Si
   * ya hay uno abierto -- dos peticiones a la vez contra el mismo servidor --,
   * las dos esperan la misma respuesta.
   */
  pedir(recurso: string, mensaje: string, usuario?: string): Promise<CuentaDeRed | null> {
    if (this.actual && this.#espera) {
      this.actual = { ...this.actual, mensaje, usuario: usuario ?? this.actual.usuario };
      return this.#espera;
    }
    this.#espera = new Promise((resolver) => {
      this.actual = {
        recurso,
        mensaje,
        usuario,
        responder: (cuenta) => {
          this.actual = null;
          this.#espera = null;
          resolver(cuenta);
        }
      };
    });
    return this.#espera;
  }

  responder(cuenta: CuentaDeRed | null): void {
    this.actual?.responder(cuenta);
  }
}

export const preguntaDeRed = new PreguntaDeRed();
