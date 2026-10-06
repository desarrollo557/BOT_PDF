import type { FilaDeActa, Report } from './types';

/**
 * Las actas de un informe, cada una con el PDF en que quedó si se dividió.
 *
 * El servicio escribe un PDF por sesión con el orden del libro delante
 * («03_ACTA-EXTRAORDINARIA-NO-017-16-08-2012.pdf»), y la fila del acta va en el
 * mismo orden: la tercera fila es el tercer PDF. Se empareja por ese número y
 * no por la posición en la lista de salidas, porque un PDF que no se pudo
 * escribir faltaría y correría a todos los de detrás.
 */
export function actasDelInforme(
  report: Report | null | undefined
): { fila: FilaDeActa; pdf: string | null }[] {
  const filas = report?.inventario_actas ?? [];
  const salidas = report?.dividido ? (report.outputs ?? []) : [];
  return filas.map((fila, indice) => {
    const prefijo = `${String(indice + 1).padStart(2, '0')}_`;
    const pdf = salidas.find((ruta) => (ruta.split('/').pop() ?? '').startsWith(prefijo)) ?? null;
    return { fila, pdf };
  });
}

/**
 * Lo que dice el nombre de un PDF generado, para leerlo como un humano.
 *
 * «03_ACTA-EXTRAORDINARIA-NO-017-16-08-2012.pdf» es el orden en el libro, el
 * acta y su fecha escritos para el disco. En la tarjeta se leen como lo que
 * son: «03 · ACTA EXTRAORDINARIA No. 017 · 16-08-2012». Un nombre que no siga
 * esa forma se enseña tal cual, sin la extensión.
 */
export function describirArchivo(nombre: string): {
  orden: string | null;
  titulo: string;
  fecha: string | null;
} {
  const base = nombre.replace(/\.pdf$/i, '');
  const conOrden = /^(\d{1,3})_(.+)$/.exec(base);
  const orden = conOrden ? conOrden[1] : null;
  let resto = conOrden ? conOrden[2] : base;
  const conFecha = /-(\d{2}-\d{2}-\d{4})$/.exec(resto);
  const fecha = conFecha ? conFecha[1] : null;
  if (conFecha) resto = resto.slice(0, conFecha.index);
  const titulo = resto
    .replace(/-/g, ' ')
    .replace(/\bNO (\d)/, 'No. $1')
    .trim();
  return { orden, titulo: titulo || base, fecha };
}
