import type { HandleClientError } from '@sveltejs/kit';
import { avisos, explicar } from '$lib/avisos.svelte';
import { almacenDeLaSesion, esDeVersionVieja, recargarUnaVez } from '$lib/version-nueva';

/** Recarga la pestaña de la versión anterior, una vez (ver `version-nueva.ts`). */
function aLaVersionNueva(error: unknown): boolean {
  return esDeVersionVieja(error) && recargarUnaVez(almacenDeLaSesion(), () => location.reload());
}

// Vite avisa antes de que el error llegue a una pantalla: un archivo que no
// se pudo precargar al navegar.
if (typeof window !== 'undefined') {
  window.addEventListener('vite:preloadError', (evento) => {
    const detalle = (evento as Event & { payload?: unknown }).payload;
    if (aLaVersionNueva(detalle ?? 'Failed to fetch dynamically imported module')) {
      evento.preventDefault();
    }
  });
}

/**
 * Un error al cargar o pintar una pantalla. SvelteKit enseña `+error.svelte`
 * con lo que esto devuelva; además queda un aviso y una línea en la consola.
 */
export const handleError: HandleClientError = ({ error, status }) => {
  if (status === 404) return { message: 'Esta pantalla no existe.' };
  if (aLaVersionNueva(error)) return { message: 'Cargando la versión nueva de la pantalla…' };
  const message = explicar(error);
  avisos.error(error, 'No se pudo abrir la pantalla');
  console.error(error);
  return { message };
};
