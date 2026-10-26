<script lang="ts">
  interface Props {
    label: string;
    value: string | number;
    note?: string;
    tone?: 'neutral' | 'good' | 'warning';
  }

  let { label, value, note, tone = 'neutral' }: Props = $props();

  // El tono de la cifra común (`.stat`) que corresponde al de la prop.
  const TONO = { neutral: '', good: 'good', warning: 'warn' } as const;
</script>

<!-- La cifra común `.stat` de app.css, en su tamaño grande (`.stat-lg`): es la
     cifra protagonista de un trabajo. Rótulo en versalitas, valor y nota, con
     un filete a la izquierda en vez de una caja. El tono va en el filete (y en
     la tinta del valor si es aviso), y la nota lo dice en palabras, así que
     nada depende sólo del color. -->
<div class="stat stat-lg {TONO[tone]}">
  <span class="stat-label">{label}</span>
  <span class="stat-value">{value}</span>
  {#if note}<span class="stat-note">{note}</span>{/if}
</div>
