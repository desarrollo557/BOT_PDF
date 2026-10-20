<script lang="ts">
  import type { Health } from '$lib/api';
  import { motivoSinAgrupar, type Agrupar, type AgruparChoice } from '$lib/habilidades';
  import Callout from './Callout.svelte';
  import ChoiceCard from './ChoiceCard.svelte';
  import StepFrame from './StepFrame.svelte';

  interface Props {
    agrupar: AgruparChoice;
    onElegir: (a: AgruparChoice) => void;
    agruparElegido: AgruparChoice;
    agrupaciones: Agrupar[];
    health: Health | null;
    pregunta?: string;
    numero?: number;
    /** La territorial de la caja, que va al encabezado de su Índice Electrónico. */
    territorial: string;
    onTerritorial: (valor: string) => void;
    /** Enter en el campo: seguir al paso siguiente si ya se puede. */
    onListo?: () => void;
  }

  let {
    onElegir,
    agruparElegido,
    agrupaciones,
    health,
    pregunta,
    numero = 4,
    territorial,
    onTerritorial,
    onListo
  }: Props = $props();

  const elegida = $derived(agrupaciones.find((opcion) => opcion.id === agruparElegido));
</script>

<StepFrame
  number={numero}
  title={pregunta?.replace(/^¿|\?$/g, '') ?? 'Qué va en cada archivo'}
  description="Elige cómo se agrupan las páginas en los archivos de salida."
  note="Esto no cambia el corte: sólo qué páginas van juntas en cada PDF entregado."
>
  <div class="grid" role="radiogroup" aria-label="Agrupación">
    {#each agrupaciones as opcion (opcion.id)}
      {@const motivo = motivoSinAgrupar(opcion, health)}
      <ChoiceCard
        title={opcion.label}
        description={opcion.agrupa}
        selected={agruparElegido === opcion.id}
        disabled={motivo !== null}
        disabledReason={motivo}
        onselect={() => onElegir(opcion.id)}
      />
    {/each}
  </div>

  {#if elegida?.cuesta}
    <Callout tone="info">{elegida.cuesta}</Callout>
  {/if}

  <!-- Debajo de las opciones y no encima: al elegir una, el aviso de que falta
       la territorial sale abajo, y el campo tiene que estar a la vista. -->
  <label class="territorial">
    <span>Territorial de la caja <em>(obligatoria al subir archivos)</em></span>
    <input
      class="input"
      id="territorial-de-la-caja"
      type="text"
      value={territorial}
      oninput={(evento) => onTerritorial(evento.currentTarget.value)}
      onkeydown={(evento) => {
        if (evento.key === 'Enter') {
          evento.preventDefault();
          onListo?.();
        }
      }}
      placeholder="Ej.: CESAR"
      maxlength="60"
      autocomplete="off"
    />
    <small>
      Va en el encabezado del Índice Electrónico; el papel no la trae. Al procesar una carpeta del
      repositorio (…\AFINIA\BOLIVAR SUR\COMERCIAL\…) se lee de la ruta y no hace falta escribirla.
    </small>
  </label>
</StepFrame>

<style>
  .territorial {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    margin-top: var(--space-2);
    max-width: 22rem;
    font-size: var(--text-sm);
  }

  .territorial span {
    font-weight: 600;
  }

  /* El campo es el `.input` común (borde, foco con anillo); sólo se le
     añaden las mayúsculas, que es como se escribe una territorial. */
  .territorial input {
    text-transform: uppercase;
  }

  .territorial em {
    font-style: normal;
    font-weight: 400;
    color: var(--muted);
  }

  .territorial small {
    color: var(--muted);
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 15rem), 1fr));
    gap: var(--space-3);
  }
</style>
