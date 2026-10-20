/**
 * La pestaña que quedó abierta de la versión anterior de la pantalla.
 *
 * Al reconstruir la imagen cambian los nombres de los archivos de la pantalla
 * («3.DhUHgjH6.js»). Una pestaña abierta antes -- o un navegador que guardó la
 * página vieja -- los pide, el servicio contesta 404 y salía «No se pudo abrir
 * la pantalla · Failed to fetch dynamically imported module» (2026-10-20, en
 * otro escritorio Windows). No es un fallo: es una versión vieja, y se arregla
 * recargando. Se recarga sola, una vez: si en medio minuto vuelve a fallar, ya
 * no es la versión y el error se enseña.
 */

const CLAVE = 'botpdf:recargada-por-version';
/** Cuánto tiempo una recarga cuenta como «la de hace un momento». */
export const ESPERA_ENTRE_RECARGAS_MS = 30_000;

/** Lo que dice cada navegador cuando falta un archivo de la pantalla. */
const DE_VERSION_VIEJA =
  /dynamically imported module|Importing a module script failed|error loading dynamically imported module|Unable to preload CSS|Failed to load module script/i;

export function esDeVersionVieja(error: unknown): boolean {
  const texto = error instanceof Error ? error.message : String(error ?? '');
  return DE_VERSION_VIEJA.test(texto);
}

interface Almacen {
  getItem(clave: string): string | null;
  setItem(clave: string, valor: string): void;
}

/**
 * Recarga la página si no se recargó hace un momento por lo mismo. Devuelve
 * si recargó. Sin almacenamiento (ventana privada, bloqueado) no recarga: sin
 * memoria de la vez anterior no hay cómo evitar un bucle.
 */
export function recargarUnaVez(
  almacen: Almacen | null,
  recargar: () => void,
  ahora: number = Date.now()
): boolean {
  if (!almacen) return false;
  try {
    const antes = Number(almacen.getItem(CLAVE) || 0);
    if (ahora - antes < ESPERA_ENTRE_RECARGAS_MS) return false;
    almacen.setItem(CLAVE, String(ahora));
  } catch {
    return false;
  }
  recargar();
  return true;
}

/** El almacenamiento de la sesión, si el navegador lo deja usar. */
export function almacenDeLaSesion(): Almacen | null {
  try {
    return typeof sessionStorage === 'undefined' ? null : sessionStorage;
  } catch {
    return null;
  }
}
