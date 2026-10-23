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
/** Con qué señal del papel se parte un libro, cuando hay más de una manera. */
export type CorteChoice =
  | 'pagina'
  | 'folio'
  | 'cedula'
  | 'nombre-cedula'
  | 'encabezado';

export interface Corte {
  id: CorteChoice;
  /** Cómo se llama la señal, en el lenguaje de quien tiene el libro delante. */
  label: string;
  /** Qué agrupa, dicho con el papel en la mano. */
  agrupa: string;
  /** Qué cuesta leerlo así. Se dice siempre: el operador paga por página. */
  cuesta: string;
}

/**
 * Qué va en cada archivo de una caja de correspondencia, una vez cortada.
 *
 * No es otro criterio de corte: el corte es el mismo en las dos. Lo que cambia
 * es qué se entrega después -- cada documento por separado, o todos los de un
 * mismo mes juntos --, y por eso viaja aparte del corte de los diplomas.
 */
export type AgruparChoice = 'documento' | 'mes' | 'tramite';

export interface Agrupar {
  id: AgruparChoice;
  /** Cómo se llama la elección, en el lenguaje de quien tiene la caja delante. */
  label: string;
  /** Qué junta en cada archivo, dicho con el papel en la mano. */
  agrupa: string;
  /** Lo que conviene saber antes de elegirla. */
  cuesta: string;
  /** Cómo se llamará cada archivo, cuando cambia respecto de la habilidad. */
  nombra?: string;
  /** Qué deja en la carpeta, cuando cambia respecto de la habilidad. */
  entrega?: string;
  /**
   * La capacidad que el servicio tiene que anunciar para poder pedirla.
   *
   * Un servicio anterior ignoraría el parámetro sin avisar y la caja saldría
   * como siempre, así que la pantalla no la ofrece contra uno que no la trae.
   */
  requiere?: string;
  /** Se muestra, pero todavía no se puede elegir. */
  proximamente?: boolean;
}

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
   * Las maneras de partir este papel, cuando hay más de una.
   *
   * Es una decisión **dentro** de la habilidad y no otra habilidad aparte: el
   * papel es el mismo libro de registro, y lo que cambia es qué se considera
   * una unidad documental en él. Un empaste foliado hoja a hoja y otro donde un
   * mismo graduado ocupa varias caras se leen igual y se parten distinto, y eso
   * lo sabe quien lo tiene delante.
   */
  cortes?: { pregunta: string; opciones: Corte[] };
  /**
   * Qué va en cada archivo una vez cortado el papel, cuando se puede elegir.
   *
   * Sólo la caja de correspondencia lo ofrece: un archivo por documento, que
   * es lo de siempre, o uno por mes, que junta las páginas de un mismo mes.
   */
  agrupar?: { pregunta: string; opciones: Agrupar[] };
  /**
   * Las acciones que admite, cuando no son las de siempre.
   *
   * Con `task: null` el operador elige qué quiere de vuelta. Las tres de
   * `RESULTADOS` hablan de unidades documentales; un libro de actas se
   * inventaría o se divide en sesiones y piezas, y eso se dice con sus
   * palabras.
   */
  acciones?: Resultado[];
  /**
   * El motor de lectura sin el cual esta habilidad no puede hacer su trabajo,
   * si hay alguno.
   *
   * No lo impone: lo advierte. Un libro de registro con todo manuscrito leído
   * sólo con OCR sale cortado igual -- el folio se mide contando tinta, sin
   * leer -- pero sin una sola cédula, así que los archivos se nombran por su
   * orden y el FUID va vacío. Eso no se nota hasta el final, y para entonces
   * se han gastado treinta minutos de proceso.
   */
  pideLectura?: { id: LecturaChoice; porque: string };
}

export const HABILIDADES: Habilidad[] = [
  {
    id: 'diplomas',
    titulo: 'Libro de diplomas',
    papel: 'Libro de registro encuadernado. Cada cara es el diploma de un graduado.',
    corta:
      'Cara a cara, por omisión: cada página es un diploma y el trabajo está en nombrarla por la cédula o el nombre. También por folio, por cédula o por encabezado, si el libro lo pide.',
    nombra: 'Requiere OCR + IA para guardar cédula o nombre.',
    nombraConIa: 'Con cédula o nombre: 7882907_juan-perez_DIPLOMA.pdf',
    aportaIa:
      'La cédula, el nombre del graduando y la fecha, que en estos libros están escritos a mano. El escaneo de cada cara viaja tal cual, en tandas de doce y varias tandas a la vez; sólo se paga la esquina del folio en las caras que no tienen con qué nombrarse.',
    tipo: 'diploma',
    task: null,
    requiereTipo: 'diploma',
    cortes: {
      pregunta: '¿Por dónde se parte este libro?',
      opciones: [
        {
          id: 'pagina',
          label: 'Cada cara es un diploma',
          agrupa:
            'Cada encabezado del libro abre un diploma: una página, un archivo. Sirve para las tres plantillas (mecanografiada, posgrados antigua y manuscrita). La cara sin encabezado ni leyenda del formulario se une a la anterior y se avisa. El archivo se nombra por la cédula si se lee bien y si no por el nombre.',
          cuesta:
            'Se lee cada cara en tanda y después se repesca en franjas ampliadas lo que quedó sin cédula o sin nombre (diez caras por página facturada). Con «OCR + IA (ahorro)» va sólo la franja, nunca la hoja entera.'
        },
        {
          id: 'folio',
          label: 'Por folio',
          agrupa:
            'Una hoja de papel es un documento. La cara con folio escrito en la esquina abre; la que llega limpia es su vuelta y va en el mismo archivo.',
          cuesta:
            'Lo más barato: la esquina se decide contando tinta, sin leer, y sólo se paga por las caras que abren — la mitad del libro.'
        },
        {
          id: 'cedula',
          label: 'Por cédula',
          agrupa:
            'Una persona es un documento. Mientras la cédula no cambie, las caras son del mismo; cuando aparece otra, empieza uno nuevo.',
          cuesta:
            'Hay que leer todas las caras, porque la cédula no se adivina. A cambio basta ese número: la cara cuya cédula saque la OCR no llega a la IA.'
        },
        {
          id: 'encabezado',
          label: 'Por encabezado (sólo OCR)',
          agrupa:
            'Abre diploma toda cara que arranque con «UNIVERSIDAD DE CARTAGENA», y también la que traiga otro graduando aunque el escáner se comiera la cabecera.',
          cuesta:
            'Nada: no usa la IA. Es el de los libros mecanografiados de 2011 en adelante, donde el formulario va impreso y el PDF ya trae capa de texto.'
        },
        {
          id: 'nombre-cedula',
          label: 'Por nombre y cédula',
          agrupa:
            'Igual que por cédula, pero sólo parte cuando el nombre TAMBIÉN es otro. Si la cédula cambia y el nombre no, lo que cambió fue el OCR y la cara se queda.',
          cuesta:
            'Lo mismo que por cédula: el nombre viene en la misma lectura, no en una petición aparte. Es el más prudente de los tres contra un dígito mal leído.'
        }
      ]
    },
    pideLectura: {
      id: 'mistral',
      porque:
        'En estos libros el folio, el nombre y la cédula están escritos a mano, y el OCR a secas no lee manuscrito. Con «Solo OCR» el libro se corta igual — la tinta de la esquina se mide sin leer — pero los archivos salen nombrados por su orden y el inventario, sin datos.'
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
    titulo: 'Caja de correspondencia (Afinia)',
    papel: 'Expediente revuelto: facturas, actas, reclamos y sus respuestas, mezclados. Inventario Índice Electrónico (Afinia).',
    corta: 'Hoja contra hoja, por continuidad. No hay ningún número que mande.',
    nombra: 'Por su puesto en la caja y su tipo documental.',
    aportaIa:
      'El texto de las hojas que llegaron sin capa de texto, para que las reglas de continuidad tengan con qué decidir.',
    tipo: 'auto',
    task: 'segment',
    agrupar: {
      pregunta: '¿Qué va en cada archivo?',
      opciones: [
        {
          // La primera y la que viene elegida: estas cajas se dividen e
          // inventarían por trámite, como lo dictó el operador.
          id: 'tramite',
          label: 'Por trámite: un archivo por número RE',
          agrupa:
            'Cada sello de radicación y cada carta con la etiqueta de envío de LECTA abren su propio PDF; la respuesta o la notificación que citan el mismo número RE van con su escrito. Un RE nuevo corta. La cédula y la factura van siempre con la hoja anterior, y lo que el escrito enumera en «ANEXOS» va con él.',
          cuesta:
            'Las páginas escaneadas se leen con OCR para encontrarles el número RE y la fecha. Con «Solo OCR» no cuesta nada. Si ninguna página trae un RE legible, la caja sale un archivo por documento.',
          nombra: 'Por su puesto, su RE y su fecha: 01-RE3110202138312-02-09-2021_RECLAMO.pdf',
          entrega: 'Deja un PDF por trámite.',
          requiere: 'agrupar-por-tramite'
        },
        {
          id: 'documento',
          label: 'Un archivo por documento',
          agrupa:
            'Cada documento que sale del corte es un PDF, numerado por su puesto en la caja. La cédula y la factura van siempre dentro del documento anterior.',
          cuesta: 'No lee con OCR: usa la capa de texto del PDF.'
        },
        {
          id: 'mes',
          label: 'Por fecha: un archivo por mes',
          agrupa:
            'Se busca la fecha de cada página y se juntan en un solo PDF todas las del mismo mes, aunque sean de días distintos y estén separadas en la caja. Una página sin fecha se une a la anterior.',
          cuesta:
            'Las páginas escaneadas se leen con OCR para encontrarles la fecha. Con «Solo OCR» no cuesta nada; con «OCR + IA» sólo se paga la página que el OCR local no logró leer. La que queda sin fecha entre dos meses distintos, o al principio de la caja, va a revisión.',
          nombra: 'Por su mes y su tipo documental: 2023-05_OFICIO.pdf',
          entrega: 'Deja un PDF por mes.',
          requiere: 'agrupar-por-mes'
        }
      ]
    }
  },
  {
    id: 'kingspan',
    titulo: 'Caja de correspondencia (Kingspan)',
    papel: 'Expediente de Kingspan: cada documento es único y se inventaría con campos No. DOCUMENTO, DESDE, HASTA, PDF_ORIGEN, ORDEN.',
    corta: 'Hoja contra hoja, por continuidad. Cada documento tiene su número en el encabezado.',
    nombra: 'Por número de documento (DESDE-HASTA) y orden en la caja.',
    aportaIa:
      'El OCR local lee el número de documento del encabezado de cada página. Con «OCR + IA» se re-lee la primera hoja si el OCR falla.',
    tipo: 'auto',
    task: null,
    acciones: [
      {
        id: 'inventory',
        label: 'Solo inventariar',
        hint: 'Genera el inventario Kingspan (No. DOCUMENTO / DESDE / HASTA). El PDF queda intacto.'
      },
      {
        id: 'both',
        label: 'Dividir e inventariar',
        hint: 'PDFs por documento + inventario Kingspan.'
      }
    ],
    pideLectura: {
      id: 'local',
      porque:
        'El inventario Kingspan lee el número de documento del encabezado con OCR local. No requiere IA.'
    }
  },
  {
    id: 'actas',
    titulo: 'Actas de consejo',
    papel:
      'Actas de sesión de un consejo de facultad, académico o superior. Cada PDF es un acta con su citación y sus anexos.',
    corta:
      'Si lo pides, por sesión: la portada que separa cada sesión abre un PDF nuevo, con su citación, su asistencia, su acta y sus anexos dentro. Sin IA.',
    nombra:
      'Cada PDF lleva el orden en el libro, el acta y su fecha, leídos del papel. La fila del inventario lleva el acta, su fecha, los folios contados y qué piezas trae con sus páginas.',
    nombraConIa: 'Y además el folio inicial y final escritos a mano, y un resumen del acta.',
    aportaIa:
      'El folio manuscrito de la esquina, leído sólo en la primera y la última hoja: una página facturada por acta. Y el resumen, que la IA escribe a partir del texto que ya sacó el OCR, nunca de la imagen: se paga por ese texto, no por página.',
    tipo: 'acta-consejo',
    task: null,
    acciones: [
      {
        id: 'inventory_file',
        label: 'Solo inventariar',
        hint: 'Una fila por acta en el Excel, con sus piezas y páginas. El PDF queda entero.'
      },
      {
        id: 'both',
        label: 'Dividir e inventariar',
        hint: 'Un PDF por sesión, con su portada, citación, asistencia, acta y anexos dentro. Y el Excel.'
      }
    ],
    requiereTipo: 'acta-consejo',
    pideLectura: {
      id: 'mistral',
      porque:
        'El folio está escrito a mano y el resumen lo escribe la IA. Con «Solo OCR» el acta se inventaría igual —número, fecha y cuántos folios tiene—, pero sin el folio inicial y final ni el resumen.'
    }
  },
  {
    id: 'actas-grado',
    titulo: 'Actas de grado',
    papel:
      'Libros de actas de grado: una hoja por graduado, con el número del acta, su nombre, su título y su cédula.',
    corta:
      'Si lo pides, un PDF por graduado: cada hoja que abre un acta es un graduado, con su reverso. El listado de graduandos, la resolución y la portada de cada ceremonia salen en su propio PDF. Sin IA.',
    nombra:
      'El inventario es el FUID oficial (FO-GD-008): una fila por graduado con «ACTA DE GRADO No. … - NOMBRE - TÍTULO», la cédula como consecutivo, la fecha, la caja y la carpeta. Lo que no se pudo leer va en NOTAS.',
    nombraConIa: 'Y lo que el OCR de casa no supo leer del graduado —nombre, cédula, número—, leído por la IA.',
    aportaIa:
      'Relee con la IA sólo las hojas a las que, después de Tesseract, les falta el nombre, la cédula o el número: una página facturada por cada una. El folio de la esquina no se lee: el FUID sólo pide cuántos folios.',
    tipo: 'acta',
    task: null,
    acciones: [
      {
        id: 'inventory_file',
        label: 'Solo inventariar',
        hint: 'Una fila por graduado en el FUID. El PDF queda entero.'
      },
      {
        id: 'both',
        label: 'Dividir e inventariar',
        hint: 'Un PDF por graduado, la ceremonia aparte, y el FUID.'
      }
    ],
    requiereTipo: 'acta',
    pideLectura: {
      id: 'mistral',
      porque:
        'En los libros antiguos el texto del escáner sale roto: con «OCR + IA» se relee lo que falte del graduado. Con «Solo OCR» la fila sale igual y dice en NOTAS qué no se pudo leer.'
    }
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
 * Por qué no se puede pedir esta forma de agrupar, o `null` si se puede.
 *
 * Se mira la capacidad que anuncia el servicio y no su revisión: es lo único
 * que dice si el parámetro se va a respetar o a ignorar en silencio.
 */
export function motivoSinAgrupar(opcion: Agrupar, health: Health | null): string | null {
  if (!opcion.requiere) return null;
  // Sin respuesta no se sabe qué versión corre: puede estar arrancando. Decir
  // «reinícielo» ahí mandaba a reiniciar un servicio que ya era el bueno.
  if (health === null) return 'Esperando al servicio para saber si admite esta opción.';
  if (health.features?.includes(opcion.requiere)) return null;
  return 'El servicio en marcha es anterior a esta opción: hay que reiniciarlo para poder elegirla.';
}

/**
 * Si el servicio puede atender esta habilidad, y por qué no cuando no puede.
 *
 * Una habilidad que el servicio no declara se enseña apagada y con el motivo,
 * en vez de desaparecer: que exista y no se pueda pedir es información, y
 * esconderla deja al operador buscando algo que vio ayer.
 */
/**
 * La habilidad que atiende un tipo de documento reconocido, si hay una.
 *
 * La matrícula no tiene tarjeta propia: la reconoce y la parte «No estoy
 * seguro». Lo que no tiene habilidad no se sugiere cambiar.
 */
const HABILIDAD_DEL_TIPO: Record<string, string> = {
  diploma: 'diplomas',
  resolucion: 'resoluciones',
  'acta-consejo': 'actas',
  acta: 'actas-grado',
  matricula: 'auto'
};

export function habilidadDelTipo(tipo: string): Habilidad | null {
  const id = HABILIDAD_DEL_TIPO[tipo];
  return id ? (HABILIDADES.find((habilidad) => habilidad.id === id) ?? null) : null;
}

export function motivoNoDisponible(habilidad: Habilidad, health: Health | null): string | null {
  if (!habilidad.requiereTipo) return null;
  const declarados = health?.document_types;
  if (!declarados) {
    return 'El servicio no informó qué tipos sabe atender. Puede usarse «No estoy seguro».';
  }
  const existe = declarados.some((tipo) => tipo.id === habilidad.requiereTipo);
  return existe ? null : 'Este servicio no atiende todavía este tipo de documento.';
}