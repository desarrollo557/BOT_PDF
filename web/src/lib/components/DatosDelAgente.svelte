<script lang="ts">
  /**
   * Lo que el agente revisó en los datos de cada documento (lo pidió el
   * operador el 2026-11-06: que los agentes «se aseguren de que lo que
   * esperemos sea íntegro» -- el nombre, la cédula o TI o libreta, el código,
   * las fechas extremas --).
   *
   * Una barra por dato: en cuántos documentos está bien, para mirar o con
   * error; y, si se dan, los hallazgos con su documento. Sirve a la ficha de un
   * PDF y al agente de la corrida.
   */
  import { filasDeLosDatos } from '$lib/agente';
  import type { CuentasDeLosDatos, HallazgoDeDatos } from '$lib/types';

  interface Props {
    datos: CuentasDeLosDatos;
    hallazgos?: HallazgoDeDatos[];
    /** Cuántos hallazgos se enseñan antes de «y N más». */
    tope?: number;
  }

  let { datos, hallazgos = [], tope = 12 }: Props = $props();

  const filas = $derived(filasDeLosDatos(datos));
  /** Los errores primero, luego lo que hay que mirar, y al final lo verificado en blanco. */
  const PESO: Record<HallazgoDeDatos['gravedad'], number> = { error: 0, duda: 1, 'en blanco': 2 };
  const TONO: Record<HallazgoDeDatos['gravedad'], string> = { error: 'bad', duda: 'warn', 'en blanco': 'neutral' };
  const ordenados = $derived([...hallazgos].sort((a, b) => PESO[a.gravedad] - PESO[b.gravedad]));
</script>

<div class="datos">
  <p class="cabeza">
    <span class="caps">Datos de cada documento</span>
    <span class="cuenta">
      <b class="tabular">{datos.completos}</b> de {datos.documentos} completos{#if datos.con_errores}{' · '}<b
          class="tabular malo">{datos.con_errores}</b> con error{/if}{#if datos.con_dudas}{' · '}<b
          class="tabular mirar">{datos.con_dudas}</b> para mirar{/if}{#if datos.con_en_blanco}{' · '}<b
          class="tabular">{datos.con_en_blanco}</b> con casillas en blanco en el papel{/if}
    </span>
  </p>

  <ul class="campos">
    {#each filas as fila (fila.campo)}
      <li class="campo">
        <span class="etiqueta">{fila.etiqueta}</span>
        <span
          class="barra"
          role="img"
          aria-label={`${fila.etiqueta}: ${fila.bien} bien, ${fila.dudas} para mirar, ${fila.errores} con error, ${fila.enBlanco} en blanco en el papel`}
        >
          {#if fila.bien}<span class="tramo" data-tono="good" style:flex-grow={fila.bien}></span>{/if}
          {#if fila.enBlanco}<span class="tramo" data-tono="neutral" style:flex-grow={fila.enBlanco}></span>{/if}
          {#if fila.dudas}<span class="tramo" data-tono="warn" style:flex-grow={fila.dudas}></span>{/if}
          {#if fila.errores}<span class="tramo" data-tono="bad" style:flex-grow={fila.errores}></span>{/if}
        </span>
        <span class="cifra tabular" title="Bien o en blanco en el papel (verificado), de cuántos"
          >{fila.bien + fila.enBlanco}/{fila.total}</span
        >
      </li>
    {/each}
  </ul>

  {#if ordenados.length}
    <ol class="hallazgos">
      {#each ordenados.slice(0, tope) as hallazgo, i (i)}
        <li class="hallazgo" data-tono={TONO[hallazgo.gravedad] ?? 'warn'}>
          <span class="status-dot" aria-hidden="true"></span>
          <span class="pdf">{hallazgo.documento}</span>
          <span class="texto">{hallazgo.texto}</span>
        </li>
      {/each}
      {#if ordenados.length > tope}
        <li class="mas">… y {ordenados.length - tope} más, en la cola de revisión.</li>
      {/if}
    </ol>
  {/if}
</div>

<style>
  [data-tono='good'] {
    --tono: var(--good);
  }
  [data-tono='neutral'] {
    --tono: var(--axis);
  }
  [data-tono='warn'] {
    --tono: var(--warning);
  }
  [data-tono='bad'] {
    --tono: var(--critical);
  }

  .datos {
    margin-top: var(--space-4);
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--hairline);
    border-radius: var(--radius-md);
    background: var(--surface-2);
  }
  .cabeza {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-1) var(--space-3);
    margin: 0 0 var(--space-3);
  }
  .cuenta {
    font-size: var(--text-sm);
    color: var(--ink-2);
  }
  .cuenta b {
    color: var(--ink);
  }
  .cuenta .malo {
    color: var(--critical);
  }
  .cuenta .mirar {
    color: color-mix(in srgb, var(--warning) 75%, var(--ink));
  }

  .campos {
    display: grid;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .campo {
    display: grid;
    grid-template-columns: minmax(7rem, 11rem) 1fr auto;
    align-items: center;
    gap: var(--space-3);
    font-size: var(--text-sm);
  }
  .etiqueta {
    color: var(--ink);
  }
  .barra {
    display: flex;
    gap: 2px;
    height: 8px;
    overflow: hidden;
    border-radius: var(--radius-pill);
    background: var(--grid);
  }
  .tramo {
    min-width: 3px;
    background: var(--tono);
    animation: entrada var(--duration-slow) var(--ease-out) both;
  }
  .cifra {
    font-size: var(--text-xs);
    color: var(--ink-2);
  }

  .hallazgos {
    display: grid;
    gap: 4px;
    margin: var(--space-3) 0 0;
    padding: 0;
    list-style: none;
    font-size: var(--text-xs);
  }
  .hallazgo {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 2px var(--space-2);
    padding: 4px var(--space-2);
    border-left: 2px solid var(--tono);
    border-radius: 0 var(--radius) var(--radius) 0;
    background: color-mix(in srgb, var(--tono) 6%, transparent);
  }
  .hallazgo .status-dot {
    background: var(--tono);
  }
  .pdf {
    font-family: var(--font-mono);
    color: var(--ink);
    overflow-wrap: anywhere;
  }
  .texto {
    color: var(--ink-2);
  }
  .mas {
    color: var(--muted);
  }

  @media (max-width: 30rem) {
    .campo {
      grid-template-columns: 1fr auto;
    }
    .barra {
      grid-column: 1 / -1;
      order: 3;
    }
  }
</style>
