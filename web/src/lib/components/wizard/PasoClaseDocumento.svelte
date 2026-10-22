<script lang="ts">
  import type { TipoDocumento, TipoDocumentoChoice } from '$lib/habilidades';
  import ChoiceCard from './ChoiceCard.svelte';
  import StepFrame from './StepFrame.svelte';

  interface Props {
    tipoDocumento: TipoDocumentoChoice;
    onElegir: (tipo: TipoDocumentoChoice) => void;
    opciones: TipoDocumento[];
    pregunta?: string;
    disabled?: boolean;
    numero?: number;
  }

  let {
    tipoDocumento,
    onElegir,
    opciones,
    pregunta,
    disabled = false,
    numero = 2
  }: Props = $props();
</script>

<StepFrame
  number={numero}
  title={pregunta?.replace(/^¿|\?$/g, '') ?? 'Empresa de la caja'}
  description="De esto depende el inventario que se entrega y cómo se agrupan las páginas."
  note="El papel es el mismo: lo que cambia es la empresa que lo pide y el formato de su inventario."
>
  <div class="grid" role="radiogroup" aria-label="Empresa de la caja">
    {#each opciones as opcion (opcion.id)}
      <ChoiceCard
        title={opcion.label}
        description={opcion.descripcion}
        selected={tipoDocumento === opcion.id}
        {disabled}
        onselect={() => onElegir(opcion.id)}
      />
    {/each}
  </div>
</StepFrame>

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 16rem), 1fr));
    gap: var(--space-3);
  }
</style>
