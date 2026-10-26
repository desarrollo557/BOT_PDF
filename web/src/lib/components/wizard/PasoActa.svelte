<script lang="ts">
  import StepFrame from './StepFrame.svelte';

  /**
   * El número de acta de transferencia del inventario de Kingspan.
   *
   * No está en el papel: lo sabe quien entrega la caja. Se elige una vez y va a
   * la columna «No. ACTA DE TRANSFERENCIA» de todas las filas del FUID. Es una
   * lista cerrada -- las actas del inventario oficial -- porque un número mal
   * escrito sería una transferencia que no existe.
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
  description="Elige el número de acta con que se entrega esta caja. Va en todas las filas del inventario."
  note="Sólo se ofrecen las actas del inventario oficial de Kingspan."
>
  <label class="campo">
    <span class="caps">No. de acta de transferencia</span>
    <select
      class="input"
      value={acta}
      onchange={(evento) => onElegir((evento.currentTarget as HTMLSelectElement).value)}
    >
      <option value="" disabled>Selecciona el acta</option>
      {#each actas as opcion (opcion)}
        <option value={opcion}>{opcion}</option>
      {/each}
    </select>
  </label>
</StepFrame>

<style>
  .campo {
    display: grid;
    gap: var(--space-2);
    max-width: 20rem;
  }
</style>
