<script lang="ts">
  import Icono from '../Icono.svelte';
  import ChoiceCard from './ChoiceCard.svelte';
  import StepFrame from './StepFrame.svelte';

  /**
   * El número de acta de transferencia del inventario de Kingspan.
   *
   * No está en el papel: lo sabe quien entrega la caja. Se elige una vez y va a
   * la columna «No. ACTA DE TRANSFERENCIA» de todas las filas del FUID. Es una
   * lista cerrada -- las actas del inventario oficial -- porque un número mal
   * escrito sería una transferencia que no existe.
   *
   * Tarjetas y no un desplegable: son seis, caben de un vistazo, y se eligen
   * igual que todo lo demás del asistente.
   */
  interface Props {
    actas: string[];
    acta: string;
    onElegir: (acta: string) => void;
    numero?: number;
  }

  let { actas, acta, onElegir, numero = 3 }: Props = $props();
</script>

<StepFrame
  number={numero}
  title="Acta de transferencia"
  description="Elige el acta con que se entrega esta caja. Va en todas las filas del inventario."
  note="Sólo se ofrecen las actas del inventario oficial de Kingspan."
>
  <div class="grid" role="radiogroup" aria-label="Acta de transferencia">
    {#each actas as opcion (opcion)}
      <ChoiceCard
        title={`Acta ${opcion}`}
        selected={acta === opcion}
        compact
        onselect={() => onElegir(opcion)}
      >
        {#snippet icon()}
          <Icono nombre="portapapeles" />
        {/snippet}
      </ChoiceCard>
    {/each}
  </div>
</StepFrame>

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 10rem), 1fr));
    gap: var(--space-3);
    max-width: 36rem;
  }
</style>
