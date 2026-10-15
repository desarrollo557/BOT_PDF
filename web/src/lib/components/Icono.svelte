<script lang="ts" module>
  /**
   * Los íconos de la interfaz, dibujados una sola vez.
   *
   * El de descarga estaba copiado en siete componentes, con dos trazos
   * distintos; el de cerrar era a veces un SVG y a veces el carácter «✕». Aquí
   * vive cada uno con su trazo, y se pintan con el color del texto que los
   * rodea, así que un botón no tiene que saber nada de ellos.
   */
  export type NombreDeIcono = 'descargar' | 'cerrar' | 'chevron' | 'editar' | 'borrar';

  const TRAZOS: Record<NombreDeIcono, string[]> = {
    descargar: [
      'M8 2.5v7m0 0 3-3m-3 3-3-3',
      'M3 11.5v1A1.5 1.5 0 0 0 4.5 14h7a1.5 1.5 0 0 0 1.5-1.5v-1'
    ],
    cerrar: ['M4 4l8 8M12 4l-8 8'],
    chevron: ['M6 4l4 4-4 4'],
    editar: ['M10.5 3.5l2 2L6 12H4v-2z'],
    borrar: ['M3.5 4.5h9', 'M6.5 4.5V3h3v1.5', 'M5 4.5l.6 8h4.8l.6-8']
  };
</script>

<script lang="ts">
  let { nombre, titulo }: { nombre: NombreDeIcono; titulo?: string } = $props();
</script>

<svg
  class="icono"
  viewBox="0 0 16 16"
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
    width: 0.95rem;
    height: 0.95rem;
    flex: none;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.6;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
</style>
