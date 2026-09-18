import type { Health } from './api';

/**
 * Qué clase de documento declara el operador que está cargando.
 *
 * Es la decisión que elige **qué habilidad** procesa el archivo. Hasta ahora la
 * tomaba el servicio leyendo una muestra de doce páginas, y eso falla justo
 * donde más caro sale: una muestra equivocada condena el archivo entero. Un
 * libro de registro de diplomas que acabe en la ruta de continuidad vuelve
 * partido por donde la estructura alcanzó, porque esa ruta no lee el papel y no
 * puede saber de quién es cada hoja.
 *
 * Quien tiene el libro delante sabe lo que es antes de subirlo, así que puede
 * decirlo. El automático sigue estando para las cajas de las que nadie sabe qué
 * traen, que es para lo que se hizo.
 */
export type TipoPedido = string;

export interface TipoOption {
  id: TipoPedido;
  label: string;
}

/** Lo que se ofrece cuando el servicio no contestó o es anterior a esta revisión. */
const SOLO_AUTO: TipoOption[] = [{ id: 'auto', label: 'Detectar automáticamente' }];

/**
 * Los tipos que la pantalla ofrece, tal como los declara el servicio.
 *
 * No están escritos aquí a propósito: los enumera el backend en `/api/health`,
 * de modo que añadir un tipo nuevo sea una línea en un solo archivo y no dos en
 * dos idiomas que alguien tiene que acordarse de mantener iguales.
 */
export function tipoOptions(health: Health | null): TipoOption[] {
  const declarados = health?.document_types;
  if (!declarados || declarados.length === 0) return SOLO_AUTO;
  return declarados;
}
