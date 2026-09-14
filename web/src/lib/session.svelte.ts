/**
 * Quién está operando el separador, con qué perfil, y desde cuándo.
 *
 * Se entra con dos datos: la cédula y el correo. No hay contraseña, y la
 * pantalla lo dice con todas sus letras, porque **esto identifica y no
 * autentica**: quien sepa la cédula y el correo de un compañero entra como él.
 *
 * Lo que compra de todos modos es real. Cada documento lleva quién lo procesó
 * hasta el libro mayor, un turno tiene principio y final, y el perfil impide el
 * descuido de descargar una planilla que no toca firmar. Esa última puerta está
 * además cerrada en el servicio: aquí se esconde el botón, y allá se rechaza la
 * petición, porque esconder un botón no impide nada a quien escriba la
 * dirección a mano.
 *
 * La diferencia con la sesión anterior es que el perfil **no lo decide esta
 * pantalla**: lo contesta el servicio a partir del alta que hizo el
 * administrador. Un navegador que se invente un perfil en su almacenamiento no
 * gana ningún permiso, porque cada petición se vuelve a juzgar allá.
 */

import { ApiError, entrar as entrarEnElServicio } from '$lib/api';

export type SessionState = 'anonymous' | 'active' | 'idle';

export type Perfil = 'administrador' | 'tecnico' | 'calidad';

export interface Operator {
  cedula: string;
  correo: string;
  /** Cómo se llama. Puede faltar: una cédula ya identifica. */
  nombre: string;
  perfil: Perfil;
  /** El perfil como se lee en pantalla, tal como lo nombra el servicio. */
  perfilLabel: string;
  startedAt: number;
}

const STORAGE_KEY = 'resolutions.session';

/**
 * Inactividad antes de que la sesión se aparque.
 *
 * No es un candado -- un clic la reanuda, porque no hay nada que destrabar --
 * sino un corte: una consola que quedó abierta toda la noche no debe seguir
 * atribuyéndole el trabajo de la mañana siguiente a quien se fue.
 */
export const IDLE_AFTER_MS = 60 * 60 * 1000;

/** Cada cuánto se mira el reloj. Barato: una comparación. */
const TICK_MS = 30_000;

interface Stored {
  operator: Operator;
  lastSeen: number;
}

function read(): Stored | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Stored;
    // La cédula y el perfil son lo mínimo para que la sesión signifique algo.
    // Una guardada por una versión anterior -- que llevaba `name` y `station`
    // -- no los tiene, y vale más mandarla a la pantalla de entrada que
    // arrancar con media sesión.
    if (!parsed?.operator?.cedula || !parsed?.operator?.perfil) return null;
    return parsed;
  } catch {
    // Una ventana privada, los datos del sitio borrados, un navegador que
    // bloquea el almacenamiento: todo eso significa «no hay sesión», nunca un
    // error camino de la pantalla de entrada.
    return null;
  }
}

function write(value: Stored | null): void {
  try {
    if (value === null) localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // El almacenamiento aquí es una comodidad. Perderlo cuesta volver a teclear
    // una cédula y un correo.
  }
}

/**
 * La sesión, como una máquina explícita.
 *
 *   anonymous --open()-->  active
 *   active    --idle-->    idle        (una hora sin un clic)
 *   idle      --resume()-> active      (un clic; no hay nada que destrabar)
 *   idle      --close()--> anonymous
 *   active    --close()--> anonymous
 *
 * Cada transición es un método. Nada fuera de este archivo escribe el estado,
 * que es lo que mantiene «quién entró» contestable desde un solo sitio.
 */
export class Session {
  state = $state<SessionState>('anonymous');
  operator = $state<Operator | null>(null);
  lastSeen = $state(Date.now());
  /** Tic para que el tiempo transcurrido se repinte sin que cada pantalla tenga reloj. */
  now = $state(Date.now());
  /** Lo que falló al entrar, para que la pantalla lo diga con las palabras del servicio. */
  error = $state<string | null>(null);
  /** Verdadero mientras se espera al servicio, para que el botón no se pulse dos veces. */
  entrando = $state(false);
  /**
   * Verdadero sólo cuando esta entrada acaba de fundar el archivo.
   *
   * Sobre un almacén de usuarios vacío, el primero que entra queda como
   * administrador. La pantalla lo dice: un permiso que se concede en silencio
   * es el que nadie revisa después.
   */
  primerAdministrador = $state(false);

  #timer: ReturnType<typeof setInterval> | null = null;
  #detach: (() => void) | null = null;

  get cedula(): string | null {
    return this.operator?.cedula ?? null;
  }

  /** Cómo se le nombra en pantalla: su nombre, y si no lo dio, su cédula. */
  get name(): string | null {
    if (!this.operator) return null;
    return this.operator.nombre || this.operator.cedula;
  }

  get perfil(): Perfil | null {
    return this.operator?.perfil ?? null;
  }

  get esAdministrador(): boolean {
    return this.operator?.perfil === 'administrador';
  }

  /**
   * Si a este perfil se le deja bajar el archivo de Excel del FUID.
   *
   * Escrito como «quién sí» y no como «quién no» a propósito: una lista de
   * excluidos deja al perfil nuevo dentro sin que nadie lo decida, y el día que
   * se añada un cuarto perfil eso sería concederle un permiso por olvido.
   */
  get descargaPlanillas(): boolean {
    return this.operator?.perfil === 'administrador';
  }

  get elapsedSeconds(): number {
    if (!this.operator) return 0;
    return Math.max(0, (this.now - this.operator.startedAt) / 1000);
  }

  get idleSeconds(): number {
    return Math.max(0, (this.now - this.lastSeen) / 1000);
  }

  /** Restaurar la sesión guardada y empezar a vigilar la inactividad. */
  start(): () => void {
    const stored = read();
    if (stored) {
      this.operator = stored.operator;
      this.lastSeen = stored.lastSeen;
      this.state = Date.now() - stored.lastSeen > IDLE_AFTER_MS ? 'idle' : 'active';
      // El perfil guardado es de la última vez que se entró, y entre medias el
      // administrador puede haberlo cambiado o haber dado de baja a esta
      // persona. Se vuelve a preguntar, sin bloquear la pantalla: lo que hay
      // guardado sirve para pintar, y la respuesta lo corrige o cierra.
      void this.#revalidar();
    }

    const touch = () => this.touch();
    const events: (keyof WindowEventMap)[] = ['pointerdown', 'keydown', 'wheel', 'focus'];
    for (const event of events) window.addEventListener(event, touch, { passive: true });

    this.#timer = setInterval(() => {
      this.now = Date.now();
      if (this.state === 'active' && this.now - this.lastSeen > IDLE_AFTER_MS) {
        this.state = 'idle';
      }
    }, TICK_MS);

    this.#detach = () => {
      for (const event of events) window.removeEventListener(event, touch);
      if (this.#timer) clearInterval(this.#timer);
      this.#timer = null;
    };
    return () => this.stop();
  }

  stop(): void {
    this.#detach?.();
    this.#detach = null;
  }

  // -- transiciones -----------------------------------------------------------

  /**
   * Entrar con una cédula y un correo.
   *
   * El perfil lo contesta el servicio. Devuelve si se entró, y deja en `error`
   * la frase con que el servicio lo explicó cuando no.
   */
  async open(cedula: string, correo: string): Promise<boolean> {
    const limpia = cedula.trim();
    const buzon = correo.trim();
    if (!limpia || !buzon) {
      this.error = 'Hacen falta la cédula y el correo.';
      return false;
    }

    this.entrando = true;
    this.error = null;
    try {
      const quien = await entrarEnElServicio(limpia, buzon);
      this.operator = {
        cedula: quien.cedula,
        correo: quien.correo,
        nombre: quien.nombre ?? '',
        perfil: quien.perfil,
        perfilLabel: quien.perfil_label ?? quien.perfil,
        startedAt: Date.now()
      };
      this.primerAdministrador = Boolean(quien.primer_administrador);
      this.state = 'active';
      this.#persist();
      return true;
    } catch (problema) {
      this.error =
        problema instanceof ApiError
          ? problema.message
          : 'No se pudo hablar con el servicio. ¿Está encendido?';
      return false;
    } finally {
      this.entrando = false;
    }
  }

  resume(): void {
    if (this.state !== 'idle') return;
    this.state = 'active';
    this.#persist();
    void this.#revalidar();
  }

  close(): void {
    this.operator = null;
    this.state = 'anonymous';
    this.error = null;
    this.primerAdministrador = false;
    write(null);
  }

  /** Cualquier interacción mantiene viva la sesión; desde inactiva no la reanuda. */
  touch(): void {
    this.now = Date.now();
    this.lastSeen = this.now;
    if (this.state === 'active') this.#persist();
  }

  /**
   * Volver a preguntarle al servicio quién es esta persona.
   *
   * Un fallo de red no cierra la sesión: dejaría al operador fuera cada vez que
   * el servicio se reinicia, y lo guardado sigue siendo lo último que el
   * servicio dijo. Sólo un rechazo del servicio -- ya no está dado de alta, o
   * le cambiaron el correo -- la cierra, porque eso sí es una respuesta.
   */
  async #revalidar(): Promise<void> {
    const guardado = this.operator;
    if (!guardado) return;
    try {
      const quien = await entrarEnElServicio(guardado.cedula, guardado.correo);
      this.operator = {
        ...guardado,
        nombre: quien.nombre ?? '',
        perfil: quien.perfil,
        perfilLabel: quien.perfil_label ?? quien.perfil
      };
      this.#persist();
    } catch (problema) {
      if (problema instanceof ApiError) {
        this.error = problema.message;
        this.close();
      }
    }
  }

  #persist(): void {
    this.lastSeen = Date.now();
    this.now = this.lastSeen;
    if (this.operator) write({ operator: this.operator, lastSeen: this.lastSeen });
  }
}

export const session = new Session();
