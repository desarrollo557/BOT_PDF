import type { TaskKind } from './types';
import type { CorteChoice } from './habilidades';
import type { AgruparChoice } from './habilidades';
import type { OracleChoice } from './oracles';
import type { LecturaChoice } from './lectura';

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

// Re-export types for convenience
export type {
  TaskKind,
  CorteChoice,
  AgruparChoice,
  OracleChoice,
  LecturaChoice,
};
