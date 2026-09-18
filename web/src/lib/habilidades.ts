import type { Health } from './api';
import type { LecturaChoice } from './lectura';
import type { TaskKind } from './types';

/**
 * Las habilidades del separador, descritas por el papel que sabe cortar.
 *
 * Existe porque la pantalla preguntaba primero **qué hacer** y dejaba para
 * después **qué es el documento**, que es justo el orden contrario al que sabe
 * contestar quien tiene la caja delante. Un archivista sabe que lo suyo es un
 * libro de diplomas; no tiene por qué saber si eso se resuelve con "dividir en
 * documentos" o con "separar por documento", y elegir mal no se nota hasta que
 * la carpeta de salida ya está escrita. Ocurrió tres veces seguidas sobre el
 * mismo libro: 199 documentos con el tipo equivocado y numerados 001, 002, 003
 * en vez de por su graduado.
 *
 * De modo que se elige el papel y el sistema deduce la ruta. Cada habilidad
 * declara por dónde corta y cómo nombra lo que produce, que es lo que permite
 * reconocer la propia caja en la descripción.
 */
export interface Habilidad {
  id: string;
  /** Cómo llama el archivo a este material. */
  titulo: string;
  /** En qué se reconoce, para que alguien identifique su caja. */
  papel: string;
  /** Por dónde decide los cortes. */
  corta: string;
  /**
   * Cómo se llamará cada archivo, leyendo sólo con el motor local.
   *
   * Ninguna habilidad depende de la ayuda de pago para hacer su trabajo: el
   * corte sale de lo que se puede medir o leer sin ella. Lo que cambia al
   * encenderla son los nombres y las columnas del inventario, nunca dónde se
   * parte el documento.
   */
  nombra: string;
  /** Y cómo se llamará cuando además se lea con el motor de pago. */
  nombraConIa?: string;
  /** Qué aporta encender la ayuda de pago en esta habilidad. */
  aportaIa?: string;
  /** El tipo que se declara al servicio. */
  tipo: string;
  /**
   * La acción, cuando esta habilidad sólo admite una. `null` cuando el
   * operador puede elegir entre quedarse los PDF, el inventario o los dos.
   */
  task: TaskKind | null;
  /** Si necesita que el servicio declare su tipo para poder ofrecerse. */
  requiereTipo?: string;
  /**
   * El motor de lectura sin el cual esta habilidad no puede hacer su trabajo,
   * si hay alguno.
   *
   * No lo impone: lo advierte. Un libro de registro con todo manuscrito leído
   * sólo con Tesseract sale cortado igual -- el folio se mide contando tinta,
   * sin leer -- pero sin una sola cédula, así que los archivos se nombran por
   * su página y el FUID va vacío. Eso no se nota hasta el final, y para
   * entonces se han gastado treinta minutos de proceso.
   */
  pideLectura?: { id: LecturaChoice; porque: string };
}

export const HABILIDADES: Habilidad[] = [
  {
    id: 'diplomas',
    titulo: 'Libro de diplomas',
    papel: 'Libro de registro encuadernado. Cada cara es el diploma de un graduado.',
    corta: 'Por el folio escrito a mano en la esquina de cada hoja, contando tinta.',
    nombra: 'Por su orden en el libro: 001_DIPLOMA.pdf',
    nombraConIa: 'Con la cédula del graduado: 7882907_DIPLOMA.pdf',
    aportaIa:
      'La cédula, el nombre del graduando y la fecha, que en estos libros están escritos a mano. El corte es el mismo con ella y sin ella.',
    tipo: 'diploma',
    task: null,
    requiereTipo: 'diploma',
    pideLectura: {
      id: 'mistral',
      porque:
        'En estos libros el folio, el nombre y la cédula están escritos a mano, y Tesseract no lee manuscrito. Sin Mistral OCR el libro se corta igual, pero los archivos salen nombrados por su página y el inventario, sin datos.'
    }
  },
  {
    id: 'resoluciones',
    titulo: 'Legajo de resoluciones',
    papel: 'Actos administrativos, cada uno con su número impreso en el encabezado.',
    corta: 'Por ese número, que manda hasta que aparece otro.',
    nombra: 'Por el número: RESOLUCION_00412.pdf',
    aportaIa:
      'Los números de encabezado que el escaneo dejó ilegibles. Con el texto impreso limpio no hace falta.',
    tipo: 'auto',
    task: null
  },
  {
    id: 'correspondencia',
    titulo: 'Caja de correspondencia',
    papel: 'Expediente revuelto: facturas, actas, reclamos y sus respuestas, mezclados.',
    corta: 'Hoja contra hoja, por continuidad. No hay ningún número que mande.',
    nombra: 'Por su puesto en la caja y su tipo documental.',
    aportaIa:
      'El texto de las hojas que llegaron sin capa de texto, para que las reglas de continuidad tengan con qué decidir.',
    tipo: 'auto',
    task: 'segment'
  },
  {
    id: 'archivo',
    titulo: 'Archivos ya separados',
    papel: 'PDF que ya son un documento cada uno y sólo hay que anotar.',
    corta: 'No se corta nada. El original queda intacto.',
    nombra: 'Conservan su nombre.',
    aportaIa: 'El asunto y las fechas extremas cuando la portada no se deja leer.',
    tipo: 'auto',
    task: 'inventory_file'
  },
  {
    id: 'auto',
    titulo: 'No estoy seguro',
    papel: 'Cuando la caja trae de todo o no se sabe qué hay dentro.',
    corta: 'Lo decide el sistema leyendo una muestra de doce páginas.',
    nombra: 'Según lo que reconozca.',
    aportaIa: 'Lo que corresponda a la habilidad que acabe atendiendo la caja.',
    tipo: 'auto',
    task: null
  }
];

/** Qué puede pedirse de vuelta cuando la habilidad admite elegirlo. */
export interface Resultado {
  id: TaskKind;
  label: string;
  hint: string;
}

export const RESULTADOS: Resultado[] = [
  {
    id: 'split',
    label: 'Los documentos',
    hint: 'un PDF por unidad documental'
  },
  {
    id: 'both',
    label: 'Documentos e inventario',
    hint: 'las dos cosas, sobre una sola lectura'
  },
  {
    id: 'inventory',
    label: 'Solo el inventario',
    hint: 'el original queda entero; útil en libros empastados'
  }
];

/**
 * Si el servicio puede atender esta habilidad, y por qué no cuando no puede.
 *
 * Una habilidad que el servicio no declara se enseña apagada y con el motivo,
 * en vez de desaparecer: que exista y no se pueda pedir es información, y
 * esconderla deja al operador buscando algo que vio ayer.
 */
export function motivoNoDisponible(habilidad: Habilidad, health: Health | null): string | null {
  if (!habilidad.requiereTipo) return null;
  const declarados = health?.document_types;
  if (!declarados) {
    return 'El servicio no informó qué tipos sabe atender. Puede usarse «No estoy seguro».';
  }
  const existe = declarados.some((tipo) => tipo.id === habilidad.requiereTipo);
  return existe ? null : 'Este servicio no atiende todavía este tipo de documento.';
}
