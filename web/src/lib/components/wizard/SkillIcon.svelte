<script lang="ts">
  /**
   * El ícono de cada habilidad, sacado del juego común de [Icono].
   *
   * Replaces the emoji the cards used to carry: an emoji renders differently on
   * every system and sets a tone this console does not have. Unknown ids get
   * the generic document outline rather than nothing, so the grid stays even.
   */
  import Icono, { type NombreDeIcono } from '../Icono.svelte';

  interface Props {
    id: string;
  }

  let { id }: Props = $props();

  const ICONO_DE: Record<string, NombreDeIcono> = {
    diplomas: 'libro',
    correspondencia: 'bandeja',
    actas: 'portapapeles',
    'actas-grado': 'birrete',
    archivo: 'carpeta',
    auto: 'buscar'
  };
</script>

<Icono nombre={ICONO_DE[id] ?? 'hoja'} />
