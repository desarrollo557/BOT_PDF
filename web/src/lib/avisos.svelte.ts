import { ApiError } from './api';
import { consoleLog } from './console.svelte';

export type Tono = 'error' | 'aviso' | 'ok';

export interface Aviso {
  id: number;
  tono: Tono;
  titulo: string;
  detalle: string | null;
}

/** Cuánto se queda un aviso que nadie cierra. Los errores esperan más: hay que leerlos. */
const DURACION_MS: Record<Tono, number> = { ok: 4_000, aviso: 7_000, error: 12_000 };
/** Más que esto apilado tapa la pantalla; se van los más viejos. */
const MAXIMO_A_LA_VEZ = 4;

/**
 * Lo que dice un error a quien lo lee, sea lo que sea lo que se lanzó.
 *
 * Un `ApiError` ya trae la frase del servicio. Lo demás es un fallo de la
 * pantalla misma -- un `TypeError` de JavaScript, una promesa rechazada con un
 * texto -- y su mensaje técnico va al detalle, no al título.
 */
export function explicar(problema: unknown): string {
  if (problema instanceof ApiError) return problema.message;
  if (problema instanceof Error && problema.message) return problema.message;
  if (typeof problema === 'string' && problema) return problema;
  return 'Ocurrió un error inesperado.';
}

/**
 * Los avisos flotantes de la pantalla: errores que nadie atrapó y resultados
 * de acciones que no tienen otro sitio donde verse.
 *
 * Cada aviso queda además en la consola, para que el que se cerró solo antes
 * de que alguien lo leyera no se pierda.
 */
class Avisos {
  lista = $state<Aviso[]>([]);
  #siguiente = 1;
  #relojes = new Map<number, ReturnType<typeof setTimeout>>();

  mostrar(tono: Tono, titulo: string, detalle: string | null = null): number {
    // El mismo error repetido -- un sondeo que falla cada dos segundos -- no
    // apila veinte copias: renueva la que ya está.
    const igual = this.lista.find(
      (aviso) => aviso.tono === tono && aviso.titulo === titulo && aviso.detalle === detalle
    );
    if (igual) {
      this.#programar(igual.id, tono);
      return igual.id;
    }
    const id = this.#siguiente++;
    this.lista = [...this.lista, { id, tono, titulo, detalle }].slice(-MAXIMO_A_LA_VEZ);
    this.#programar(id, tono);
    consoleLog.push(
      tono === 'error' ? 'ERROR' : tono === 'aviso' ? 'AVISO' : 'OK',
      detalle ? `${titulo} · ${detalle}` : titulo,
      tono === 'error' ? 'fail' : tono === 'aviso' ? 'warn' : 'ok'
    );
    return id;
  }

  /** Un error, con el contexto de qué se estaba haciendo cuando ocurrió. */
  error(problema: unknown, contexto = 'Algo salió mal'): number {
    return this.mostrar('error', contexto, explicar(problema));
  }

  quitar(id: number): void {
    clearTimeout(this.#relojes.get(id));
    this.#relojes.delete(id);
    this.lista = this.lista.filter((aviso) => aviso.id !== id);
  }

  #programar(id: number, tono: Tono): void {
    clearTimeout(this.#relojes.get(id));
    this.#relojes.set(
      id,
      setTimeout(() => this.quitar(id), DURACION_MS[tono])
    );
  }
}

export const avisos = new Avisos();

/**
 * Los errores que se escapan de cualquier manejador -- un `onclick` que lanza,
 * una promesa sin `catch` -- terminan en un aviso en vez de en la nada.
 *
 * Devuelve con qué soltarlos, para el `onMount` que los engancha.
 */
export function atraparErroresSueltos(destino: Window = window): () => void {
  const alFallar = (evento: ErrorEvent) => {
    // Un recurso que no cargó (una imagen) también dispara `error`, sin
    // mensaje: no es un fallo del programa.
    if (!evento.error && !evento.message) return;
    avisos.error(evento.error ?? evento.message, 'Error en la pantalla');
  };
  const alRechazar = (evento: PromiseRejectionEvent) => {
    const motivo = evento.reason;
    if (motivo instanceof DOMException && motivo.name === 'AbortError') return;
    avisos.error(motivo, 'Una operación no se pudo completar');
  };
  destino.addEventListener('error', alFallar);
  destino.addEventListener('unhandledrejection', alRechazar);
  return () => {
    destino.removeEventListener('error', alFallar);
    destino.removeEventListener('unhandledrejection', alRechazar);
  };
}
