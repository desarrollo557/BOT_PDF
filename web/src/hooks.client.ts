import type { HandleClientError } from '@sveltejs/kit';
import { avisos, explicar } from '$lib/avisos.svelte';

/**
 * Un error al cargar o pintar una pantalla. SvelteKit enseña `+error.svelte`
 * con lo que esto devuelva; además queda un aviso y una línea en la consola.
 */
export const handleError: HandleClientError = ({ error, status }) => {
  if (status === 404) return { message: 'Esta pantalla no existe.' };
  const message = explicar(error);
  avisos.error(error, 'No se pudo abrir la pantalla');
  console.error(error);
  return { message };
};
