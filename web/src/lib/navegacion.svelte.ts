/**
 * La jerarquía de las vistas: qué está dentro de qué, y adónde lleva «Volver».
 *
 * Nivel 1 son las secciones de la barra -- Procesar, Archivo, Revisión --. Nivel 2, lo que se abre desde una de ellas: un documento, que
 * cuelga de la sección desde la que se abrió y, si vino de una carpeta del
 * archivo, de esa carpeta. «Volver» sube un nivel; nunca salta a otra sección.
 *
 * El origen viaja en el enlace (`?desde=revision&carpeta=…`) y no en una
 * variable de la pantalla, para que un enlace copiado o una recarga sigan
 * sabiendo dónde está el documento.
 */

export type Seccion = 'procesar' | 'archivo' | 'revision';

export const SECCIONES: Record<Seccion, { etiqueta: string; href: string }> = {
  procesar: { etiqueta: 'Procesar', href: '/' },
  archivo: { etiqueta: 'Archivo', href: '/archivo' },
  revision: { etiqueta: 'Revisión', href: '/revision' }
};

export interface Miga {
  etiqueta: string;
  /** `null` en la última: es donde se está. */
  href: string | null;
}

function esSeccion(valor: string | null): valor is Seccion {
  return valor !== null && valor in SECCIONES;
}

/** El enlace a un documento, con de dónde se abre. */
export function enlaceAlDocumento(
  jobId: string,
  desde: Seccion,
  carpeta?: string | null
): string {
  const parametros = new URLSearchParams({ desde });
  if (carpeta) parametros.set('carpeta', carpeta);
  return `/documento/${jobId}?${parametros}`;
}

/** El archivo buscando una carpeta: el nivel intermedio entre el archivo y un documento suyo. */
export function enlaceALaCarpeta(carpeta: string): string {
  return `/archivo?${new URLSearchParams({ q: carpeta })}`;
}

/**
 * Las migas de una vista. Vacías en una sección: la barra de arriba ya dice
 * dónde se está, y repetirlo debajo sólo ocupa sitio.
 */
export function migasDe(url: URL, titulo: string | null = null): Miga[] {
  if (!url.pathname.startsWith('/documento/')) return [];
  const desde = url.searchParams.get('desde');
  const seccion = SECCIONES[esSeccion(desde) ? desde : 'archivo'];
  const migas: Miga[] = [{ etiqueta: seccion.etiqueta, href: seccion.href }];
  const carpeta = url.searchParams.get('carpeta');
  if (carpeta && seccion === SECCIONES.archivo) {
    migas.push({ etiqueta: `Carpeta ${carpeta}`, href: enlaceALaCarpeta(carpeta) });
  }
  migas.push({ etiqueta: titulo || 'Documento', href: null });
  return migas;
}

/** Adónde sube «Volver» desde esta vista, o `null` en una sección. */
export function padreDe(url: URL): string | null {
  const migas = migasDe(url);
  return migas.length > 1 ? (migas[migas.length - 2].href ?? null) : null;
}

/**
 * El título de la vista abierta, que pone la página que lo conoce -- el nombre
 * del documento sólo lo sabe la del documento -- y lee la barra de migas.
 */
class Vista {
  titulo = $state<string | null>(null);
}

export const vista = new Vista();
