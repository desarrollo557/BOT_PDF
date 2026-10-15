<script lang="ts">
  import type { LecturaChoice } from '$lib/lectura';
  import Callout from './Callout.svelte';
  import ChoiceCard from './ChoiceCard.svelte';
  import StepFrame from './StepFrame.svelte';

  interface Props {
    lectura: LecturaChoice;
    onElegir: (l: LecturaChoice) => void;
    lecturas: Array<{
      id: LecturaChoice;
      label: string;
      hint: string;
      available: boolean;
      reason: string | null;
    }>;
    faltaLectura: { id: LecturaChoice; porque: string } | null;
    conIa: boolean;
    blockedLectura: string | null;
    numero?: number;
  }

  let { lectura, onElegir, lecturas, faltaLectura, conIa, blockedLectura, numero = 2 }: Props =
    $props();

  /** What each reader costs, said on the card itself. */
  const BADGES: Record<string, { text: string; tone: 'good' | 'accent' | 'warning' }> = {
    local: { text: 'Gratis', tone: 'good' },
    mistral: { text: 'Usa IA, pago por página', tone: 'accent' },
    'mistral-nombres': { text: 'Usa IA, modo ahorro', tone: 'accent' }
  };

  /** The label of the reader a skill asks for, as the screen names it. */
  const etiquetaDe = (id: LecturaChoice) =>
    lecturas.find((item) => item.id === id)?.label ?? 'OCR + IA';
</script>

<StepFrame
  number={numero}
  title="Cómo se lee el papel"
  description="«Solo OCR» es gratis y lee lo impreso y mecanografiado. «OCR + IA» se paga y además lee lo escrito a mano: folio, nombre, cédula y fecha."
  note={conIa
    ? 'La IA no cambia dónde se corta el documento: sólo cómo se nombran los archivos y qué datos trae el inventario.'
    : 'Lo que esté escrito a mano no aparecerá en los nombres de archivo ni en el inventario.'}
>
  <div class="grid" role="radiogroup" aria-label="Motor de lectura">
    {#each lecturas as option (option.id)}
      {@const badge = BADGES[option.id]}
      <ChoiceCard
        title={option.label}
        description={option.hint}
        selected={lectura === option.id}
        disabled={!option.available}
        disabledReason={option.reason ?? 'Falta la llave en el servicio.'}
        badge={badge?.text ?? null}
        badgeTone={badge?.tone ?? 'neutral'}
        onselect={() => onElegir(option.id)}
      />
    {/each}
  </div>

  {#if blockedLectura}
    <Callout tone="warning">{blockedLectura}</Callout>
  {/if}

  {#if faltaLectura}
    <Callout tone="info">
      <span>{faltaLectura.porque}</span>
      <button type="button" onclick={() => onElegir(faltaLectura.id)}>
        Usar {etiquetaDe(faltaLectura.id)}
      </button>
    </Callout>
  {/if}
</StepFrame>

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 15rem), 1fr));
    gap: var(--space-3);
  }
</style>
