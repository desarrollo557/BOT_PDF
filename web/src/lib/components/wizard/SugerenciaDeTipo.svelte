<script lang="ts">
  /**
   * Lo que el bot reconoce en lo que se va a cargar, antes de procesarlo.
   *
   * Lee sólo la capa de texto y el nombre -- no gasta nada -- y lo compara con
   * la habilidad elegida. Si no coinciden, lo dice y ofrece cambiarla sin
   * perder los archivos ya elegidos. Es una sugerencia: el trabajo vuelve a
   * comprobar cada PDF y manda a su habilidad lo que no es lo declarado.
   */
  import type { Sugerencia, SugerenciaDeCarpeta } from '$lib/api';
  import { HABILIDADES, habilidadDelTipo } from '$lib/habilidades';
  import type { LecturaChoice } from '$lib/lectura';
  import Callout from './Callout.svelte';

  interface Props {
    habilidadId: string;
    /** De archivos sueltos, uno por archivo, con su nombre. */
    archivos?: (Sugerencia & { nombre: string })[];
    /** O de una carpeta local entera. */
    carpeta?: SugerenciaDeCarpeta | null;
    cargando?: boolean;
    error?: string | null;
    /** La lectura elegida: si lo detectado pide la IA y va «Solo OCR», se dice. */
    lectura?: LecturaChoice;
    onusar: (habilidadId: string) => void;
  }

  let {
    habilidadId,
    archivos = [],
    carpeta = null,
    cargando = false,
    error = null,
    lectura,
    onusar
  }: Props = $props();

  const DESCONOCIDO = 'desconocido';

  const conteo = $derived.by(() => {
    if (carpeta) return carpeta.por_tipo;
    const cuenta = new Map<string, { tipo: string; etiqueta: string; cantidad: number }>();
    for (const archivo of archivos) {
      const previo = cuenta.get(archivo.tipo);
      if (previo) previo.cantidad += 1;
      else cuenta.set(archivo.tipo, { tipo: archivo.tipo, etiqueta: archivo.etiqueta, cantidad: 1 });
    }
    return [...cuenta.values()].sort((a, b) => b.cantidad - a.cantidad);
  });

  const total = $derived(conteo.reduce((suma, fila) => suma + fila.cantidad, 0));
  const reconocidos = $derived(conteo.filter((fila) => fila.tipo !== DESCONOCIDO));
  const dominante = $derived(reconocidos[0] ?? null);
  const mezcla = $derived(reconocidos.length > 1);

  const actual = $derived(HABILIDADES.find((habilidad) => habilidad.id === habilidadId) ?? null);
  const sugerida = $derived(dominante ? habilidadDelTipo(dominante.tipo) : null);
  /**
   * «Detectar automáticamente»: no hay nada que cambiar, el bot manda cada PDF a
   * su habilidad. Se dice cuál detectó (el operador, 2026-11-03: «que sepa
   * detectar la habilidad automáticamente»).
   */
  const automatico = $derived(habilidadId === 'auto');
  /** Lo elegido ya atiende lo que hay: su tipo es el reconocido, o decide solo. */
  const coincide = $derived(
    automatico || !sugerida || sugerida.id === habilidadId || actual?.tipo === dominante?.tipo
  );
  const porNombre = $derived(
    carpeta
      ? carpeta.archivos.filter((archivo) => archivo.por === 'nombre').length
      : archivos.filter((archivo) => archivo.por === 'nombre').length
  );
  /** Lo detectado lee mejor con la IA -- los nombres de las historias -- y va «Solo OCR». */
  const conviene = $derived(
    automatico && lectura === 'local' && sugerida?.pideLectura ? sugerida.pideLectura : null
  );
</script>

{#if cargando}
  <div class="estado" aria-live="polite">
    <span class="status-dot live" aria-hidden="true"></span>
    Reconociendo qué documentos son…
  </div>
{:else if error}
  <p class="inline-error">No se pudo reconocer: {error}</p>
{:else if total}
  <Callout tone={coincide ? 'info' : 'warning'}>
    <div class="cuerpo">
      <p class="titulo">
        {#if !dominante}
          El bot no reconoce de qué tipo {total === 1 ? 'es este documento' : 'son estos documentos'}.
          {#if automatico}Al procesarlo leerá cada PDF y lo mandará a la habilidad que le toque.{/if}
        {:else if automatico && sugerida}
          Habilidad detectada: <b>{sugerida.titulo}</b>
          ({dominante.cantidad === total
            ? total === 1
              ? 'el documento es'
              : `los ${total} son`
            : `${dominante.cantidad} de ${total} son`}
          {dominante.etiqueta}).
        {:else if coincide}
          Coincide con lo elegido: {dominante.cantidad === total ? (total === 1 ? 'es' : 'todos son') : `${dominante.cantidad} de ${total} son`}
          <b>{dominante.etiqueta}</b>.
        {:else}
          {total === 1 ? 'Parece' : 'Parecen'} <b>{dominante.etiqueta}</b>, no
          <b>{actual?.titulo ?? 'lo elegido'}</b>.
        {/if}
      </p>

      {#if mezcla || conteo.some((fila) => fila.tipo === DESCONOCIDO)}
        <ul class="tipos" aria-label="Documentos por tipo">
          {#each conteo as fila (fila.tipo)}
            <li class="pill pill-neutral" class:sin={fila.tipo === DESCONOCIDO}>
              <b class="tabular">{fila.cantidad}</b>
              {fila.etiqueta}
            </li>
          {/each}
        </ul>
      {/if}

      {#if mezcla}
        <p class="nota">
          {#if automatico}
            Mezcla tipos: al procesar, cada PDF va a la habilidad que le toca.
          {:else}
            Mezcla tipos. Cada PDF se comprueba al procesarlo, y el que no sea lo declarado va a la
            habilidad que le toca, con un aviso en el informe.
          {/if}
        </p>
      {/if}
      {#if conviene}
        <p class="nota">
          Va con «Solo OCR»: {conviene.porque} Para eso conviene volver al paso de lectura y elegir
          la IA.
        </p>
      {/if}
      {#if porNombre}
        <p class="nota">
          {porNombre === 1 ? 'Uno se reconoce' : `${porNombre} se reconocen`} sólo por el nombre del
          archivo: su contenido no trae texto que lo diga.
        </p>
      {/if}

      {#if !coincide && sugerida}
        <button type="button" class="btn btn-primary usar" onclick={() => onusar(sugerida.id)}>
          Usar «{sugerida.titulo}»
        </button>
      {/if}
    </div>
  </Callout>
{/if}

<style>
  .estado {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    color: var(--muted);
  }
  .cuerpo {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .titulo,
  .nota {
    margin: 0;
  }
  .nota {
    font-size: var(--text-xs);
    color: var(--ink-2);
  }
  .tipos {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  /* Cada tipo es una `.pill` neutra; lo reconocido en la tinta secundaria y lo
     que no se reconoce, apagado. */
  .tipos li {
    color: var(--ink-2);
  }
  .tipos li.sin {
    color: var(--muted);
  }
  .usar {
    align-self: flex-start;
  }
</style>
