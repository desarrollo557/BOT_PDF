import type { ReviewItem } from './types';

/**
 * Lo que de verdad espera a una persona en la Revisión: los avisos que el agente
 * no resolvió. Desde el 2026-11-23 el bot resuelve solo cada aviso y anota lo
 * que hizo (`resuelto`); el operador: «yo no voy a darle en confirmar a todos
 * esos… el bot haga absolutamente todo».
 */
export function pendientes(report?: { review_queue?: ReviewItem[] } | null): ReviewItem[] {
  return (report?.review_queue ?? []).filter((aviso) => !aviso.resuelto);
}

/** Los avisos que el agente resolvió por su cuenta, con lo que hizo. */
export function resueltos(report?: { review_queue?: ReviewItem[] } | null): ReviewItem[] {
  return (report?.review_queue ?? []).filter((aviso) => Boolean(aviso.resuelto));
}
