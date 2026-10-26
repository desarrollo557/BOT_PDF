<script lang="ts" module>
  /**
   * Los íconos de la interfaz, dibujados una sola vez.
   *
   * El de descarga estaba copiado en siete componentes, con dos trazos
   * distintos; el de cerrar era a veces un SVG y a veces el carácter «✕». Aquí
   * vive cada uno con su trazo, y se pintan con el color del texto que los
   * rodea, así que un botón no tiene que saber nada de ellos.
   *
   * Casi todos están en una rejilla de 16. Los pictogramas de las habilidades
   * vienen de una de 24 y se dibujan con el trazo escalado (1,6 × 24/16), así
   * que al mismo tamaño pesan lo mismo que los demás. El tamaño lo decide quien
   * lo usa con `--icono` (por omisión, 0,95rem).
   */
  export type NombreDeIcono =
    | 'descargar'
    | 'cerrar'
    | 'chevron'
    | 'atras'
    | 'abajo'
    | 'subir'
    | 'editar'
    | 'borrar'
    | 'hecho'
    | 'mas'
    | 'carpeta'
    | 'documento'
    | 'documentos'
    | 'aviso'
    | 'info'
    | 'candado'
    | 'libro'
    | 'bandeja'
    | 'portapapeles'
    | 'birrete'
    | 'buscar'
    | 'hoja';

  const TRAZOS: Record<NombreDeIcono, string[]> = {
    descargar: [
      'M8 2.5v7m0 0 3-3m-3 3-3-3',
      'M3 11.5v1A1.5 1.5 0 0 0 4.5 14h7a1.5 1.5 0 0 0 1.5-1.5v-1'
    ],
    cerrar: ['M4 4l8 8M12 4l-8 8'],
    chevron: ['M6 4l4 4-4 4'],
    atras: ['M10 4 6 8l4 4'],
    abajo: ['M4 6l4 4 4-4'],
    subir: ['M6.5 3.5 3.5 6.5l3 3', 'M3.5 6.5H9a3.5 3.5 0 0 1 3.5 3.5v2.5'],
    editar: ['M10.5 3.5l2 2L6 12H4v-2z'],
    borrar: ['M3.5 4.5h9', 'M6.5 4.5V3h3v1.5', 'M5 4.5l.6 8h4.8l.6-8'],
    hecho: ['m3.5 8.5 3 3 6-7'],
    mas: ['M8 3v10M3 8h10'],
    carpeta: [
      'M2 4.2A1.2 1.2 0 0 1 3.2 3h3l1.4 1.6h5.2A1.2 1.2 0 0 1 14 5.8v6A1.2 1.2 0 0 1 12.8 13H3.2A1.2 1.2 0 0 1 2 11.8V4.2Z'
    ],
    documento: [
      'M4 2h8a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 12 14H4a1.5 1.5 0 0 1-1.5-1.5v-9A1.5 1.5 0 0 1 4 2Z',
      'M5 6h6M5 8.5h6M5 11h3.5'
    ],
    documentos: [
      'M4.8 2.4h6.4a1.2 1.2 0 0 1 1.2 1.2v8.8a1.2 1.2 0 0 1-1.2 1.2H4.8a1.2 1.2 0 0 1-1.2-1.2V3.6a1.2 1.2 0 0 1 1.2-1.2Z',
      'M2 4.8v7.6a1.2 1.2 0 0 0 1.2 1.2',
      'M6 5.6h4M6 8h4M6 10.4h2.4'
    ],
    aviso: ['M8 2.2 14.3 13H1.7Z', 'M8 6.5v3M8 11.2v.1'],
    info: ['M8 1.75a6.25 6.25 0 1 0 0 12.5 6.25 6.25 0 0 0 0-12.5Z', 'M8 7.25v4M8 4.9v.1'],
    candado: [
      'M5 7h6a1.5 1.5 0 0 1 1.5 1.5V12a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 12V8.5A1.5 1.5 0 0 1 5 7Z',
      'M5.5 7V5a2.5 2.5 0 0 1 5 0v2'
    ],
    // Rejilla de 24: los pictogramas de las habilidades (ver SkillIcon).
    libro: ['M2 4.5h6a4 4 0 0 1 4 4V20a3 3 0 0 0-3-3H2z', 'M22 4.5h-6a4 4 0 0 0-4 4V20a3 3 0 0 1 3-3h7z'],
    bandeja: [
      'M22 12h-6l-2 3h-4l-2-3H2',
      'M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z'
    ],
    portapapeles: [
      'M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2',
      'M9 2h6a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1Z',
      'M9 12h6M9 16h4'
    ],
    birrete: ['M22 10 12 5 2 10l10 5z', 'M6 12v5c3 2 9 2 12 0v-5'],
    buscar: ['M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14Z', 'm21 21-4.3-4.3'],
    hoja: ['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z', 'M14 2v6h6M16 13H8M16 17H8M10 9H8']
  };

  const REJILLA_24 = new Set<NombreDeIcono>(['libro', 'bandeja', 'portapapeles', 'birrete', 'buscar', 'hoja']);
</script>

<script lang="ts">
  let { nombre, titulo }: { nombre: NombreDeIcono; titulo?: string } = $props();

  const rejilla = $derived(REJILLA_24.has(nombre) ? 24 : 16);
</script>

<svg
  class="icono"
  viewBox="0 0 {rejilla} {rejilla}"
  style:stroke-width={(1.6 * rejilla) / 16}
  role={titulo ? 'img' : undefined}
  aria-hidden={titulo ? undefined : 'true'}
  aria-label={titulo}
>
  {#each TRAZOS[nombre] as trazo (trazo)}
    <path d={trazo} />
  {/each}
</svg>

<style>
  .icono {
    width: var(--icono, 0.95rem);
    height: var(--icono, 0.95rem);
    flex: none;
    fill: none;
    stroke: currentColor;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
</style>
