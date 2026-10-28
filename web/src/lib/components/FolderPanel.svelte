<script lang="ts">
  import FolderPicker from '$lib/components/FolderPicker.svelte';
  import Icono from '$lib/components/Icono.svelte';
  import SugerenciaDeTipo from '$lib/components/wizard/SugerenciaDeTipo.svelte';
  import { reconocerCarpeta, type SugerenciaDeCarpeta } from '$lib/api';
  import { confirmar } from '$lib/confirmar.svelte';
  import { jobStore } from '$lib/jobs.svelte';
  import type { AgruparChoice, CorteChoice } from '$lib/habilidades';
  import type { LecturaChoice } from '$lib/lectura';
  import type { TipoPedido } from '$lib/tipos';
  import type { OracleChoice } from '$lib/oracles';
  import type { RetomarChoice, SourceDisposition, TaskKind } from '$lib/types';

  interface Props {
    /**
     * Qué hacer con cada documento de la carpeta.
     *
     * Es la misma decisión que se toma al subir un archivo a mano, y la elige el
     * mismo control: una carpeta que sólo supiera dividir dejaba a un libro de
     * diplomas sin más salida que volver a subirlo uno por uno.
     */
    task?: TaskKind;
    /**
     * Y a qué modelo preguntarle por los bordes dudosos. Viaja desde el
     * mismo control que en una subida a mano: una carpeta que siempre
     * usara el automático no serviría para comparar dos modelos.
     */
    oracle?: OracleChoice;
    /**
     * Y con qué motor leer el papel. Una corrida entera comparte motor porque
     * una carpeta suele traer un mismo tipo de material: la caja de libros
     * manuscritos se lee con ayuda y la de expedientes mecanografiados no la
     * necesita.
     */
    lectura?: LecturaChoice;
    /**
     * Y por dónde partir cada libro de diplomas que traiga: por el folio de
     * la esquina o por el número de cédula. Como el motor, vale para toda la
     * corrida porque una estantería suele ser homogénea.
     */
    corte?: CorteChoice;
    /**
     * Y qué va en cada archivo cuando la carpeta trae cajas de correspondencia:
     * cada documento, o todos los de un mismo mes juntos. Vale para toda la
     * corrida, como el corte.
     */
    agrupar?: AgruparChoice;
    /** El tipo de documento de la caja (Afinia / Kingspan / mixto). */
    tipoDocumento?: string;
    /** El acta de transferencia del inventario de Kingspan, para toda la carpeta. */
    acta?: string;
    /**
     * Y qué clase de documento trae la carpeta. Una estantería suele ser
     * homogénea -- veinte libros de diplomas --, así que declararlo una vez
     * vale para todos sus archivos.
     */
    tipo?: TipoPedido;
    /** La habilidad elegida, para decir si lo que trae la carpeta coincide. */
    habilidadId?: string;
    /** Cambiar a la habilidad que sugiere lo reconocido. */
    onusarHabilidad?: (id: string) => void;
    /** Cuántos PDF a la vez; sin él, el automático del servicio. */
    paralelo?: number;
  }

  let {
    task = 'split',
    oracle = 'auto',
    lectura = 'local',
    tipo = 'auto',
    corte = 'pagina',
    agrupar = 'documento',
    tipoDocumento,
    acta,
    habilidadId = 'auto',
    onusarHabilidad,
    paralelo
  }: Props = $props();

  /**
   * Clean a pasted path in the field itself.
   *
   * Windows Explorer's "Copiar como ruta" wraps the path in double quotes, and
   * that is how most people get a path onto the clipboard. The service strips
   * them too, but doing it here as well means the operator sees the path that
   * is actually going to be used instead of wondering why it worked anyway.
   */
  const QUOTES = `"'“”‘’«»`;

  function cleanPath(raw: string): string {
    let value = raw.trim();
    while (value.length >= 2 && QUOTES.includes(value[0]) && QUOTES.includes(value.at(-1)!)) {
      value = value.slice(1, -1).trim();
    }
    return value;
  }

  let source = $state('');

  /* -- qué trae la carpeta ----------------------------------------------------
     En cuanto la ruta de origen se asienta, el bot recorre la carpeta y sus
     subcarpetas y dice qué parece cada PDF: sólo su capa de texto y su nombre,
     sin gastar nada. Una caja grande tarda unos segundos; se avisa mientras. */
  let analisis = $state<SugerenciaDeCarpeta | null>(null);
  let analizando = $state(false);
  let errorDeAnalisis = $state<string | null>(null);
  let pedidoDeAnalisis: AbortController | null = null;

  $effect(() => {
    const ruta = cleanPath(source);
    pedidoDeAnalisis?.abort();
    analisis = null;
    errorDeAnalisis = null;
    if (!ruta) return;
    const pedido = new AbortController();
    pedidoDeAnalisis = pedido;
    const espera = setTimeout(async () => {
      analizando = true;
      try {
        const respuesta = await reconocerCarpeta(ruta, pedido.signal);
        if (!pedido.signal.aborted) analisis = respuesta;
      } catch (problema) {
        if (!pedido.signal.aborted) errorDeAnalisis = (problema as Error).message;
      } finally {
        if (pedidoDeAnalisis === pedido) analizando = false;
      }
    }, 600);
    return () => {
      clearTimeout(espera);
      pedido.abort();
    };
  });
  let destination = $state('');
  let disposition = $state<SourceDisposition>('leave');
  let watch = $state(false);
  const RETOMAR: { id: RetomarChoice; label: string; hint: string }[] = [
    {
      id: 'no',
      label: 'Saltar lo ya entregado',
      hint:
        'Procesa lo nuevo; lo entregado entero no se vuelve a leer. Lo que quedó a medias, o cuyo ' +
        'original cambió, se rehace y lo anterior se aparta en _reemplazados (no se borra)'
    },
    {
      id: 'faltantes',
      label: 'Retomar lo que falta',
      hint: 'Salta lo que ya está completo en el destino y lee sólo las páginas que faltan'
    },
    {
      id: 'revisar',
      label: 'Sólo revisar',
      hint: 'No procesa nada: dice qué está entregado y qué falta'
    },
    {
      id: 'todo',
      label: 'Procesar todo otra vez',
      hint: 'Vuelve a procesar cada PDF; lo entregado antes se aparta en _reemplazados'
    }
  ];

  /**
   * Qué hacer con lo que ya está en el destino. Para cualquier tipo: saltar lo
   * entregado entero (lo normal) o volver a procesarlo todo. Los libros de
   * diplomas además se pueden retomar página a página o sólo revisar.
   */
  let retomar = $state<RetomarChoice>('no');
  const opcionesDeRetomar = $derived(
    tipo === 'diploma' ? RETOMAR : RETOMAR.filter((option) => option.id === 'no' || option.id === 'todo')
  );
  const modoRetomar = $derived<RetomarChoice>(
    opcionesDeRetomar.some((option) => option.id === retomar) ? retomar : 'no'
  );
  /** Vigilar sólo tiene sentido cuando se procesa: no al retomar ni al revisar. */
  const puedeVigilar = $derived(modoRetomar === 'no' || modoRetomar === 'todo');
  let starting = $state(false);
  let error = $state<string | null>(null);

  /** Which field the folder browser is filling, or null when it is closed. */
  let picking = $state<'origen' | 'destino' | null>(null);

  /**
   * Vaciar el formulario cuando la mesa de trabajo vuelve a cero.
   *
   * Al cerrar el informe de una tanda terminada, la pantalla se limpia; si las
   * rutas se quedaran escritas, quedarían flotando sobre una pantalla vacía y
   * el operador no sabría si esa carpeta sigue procesándose o no.
   *
   * Sólo reacciona al cambio, nunca al montarse: el valor inicial es el estado
   * de partida, no un reinicio.
   */
  let lastReset = $state(jobStore.resetSignal);
  $effect(() => {
    const signal = jobStore.resetSignal;
    if (signal === lastReset) return;
    lastReset = signal;
    source = '';
    destination = '';
    disposition = 'leave';
    watch = false;
    retomar = 'no';
    error = null;
    picking = null;
  });

  /**
   * Abre el explorador de la aplicación, no el de Windows.
   *
   * El de Windows no se puede vestir: es una ventana del sistema, dibujada por
   * Windows con la apariencia de Windows, y aparecía como un cuerpo extraño en
   * medio de la pantalla. Éste recorre el mismo disco -- las carpetas las lista
   * el servicio, que corre en esta máquina -- y devuelve la misma ruta
   * absoluta, con los estilos de la página. El de Windows sigue a un clic,
   * dentro, para quien lo prefiera.
   */
  function choose(which: 'origen' | 'destino') {
    error = null;
    picking = which;
  }

  /**
   * Lo que el bot hace con cada original, dicho exactamente: es lo único que
   * hace en el origen (lo pidió el operador el 2026-10-20: «que actúe
   * estrictamente según lo seleccionado»). Apartar y borrar sólo ocurren
   * cuando ese PDF se entregó completo; uno que falla se queda donde estaba.
   */
  const DISPOSITIONS: { id: SourceDisposition; label: string; hint: string }[] = [
    { id: 'leave', label: 'Dejarlo', hint: 'El original no se toca ni se mueve' },
    {
      id: 'move',
      label: 'Apartarlo',
      hint: 'Ya entregado completo, se mueve a _procesados en el origen'
    },
    {
      id: 'delete',
      label: 'Borrarlo',
      hint: 'Ya entregado completo, se elimina del origen (se pide confirmación)'
    }
  ];

  /**
   * Una carpeta de red -- «\\servidor\recurso\…», o una unidad que el servicio
   * lee por la red, como «Z:\…»: eso lo dice el reconocimiento --. Su original
   * no se toca: es el repositorio de donde se lee, así que sólo cabe «Dejarlo».
   */
  const origenDeRed = $derived(
    /^(\\\\|\/\/)[^\\/]+[\\/]+[^\\/]+/.test(cleanPath(source)) || analisis?.de_red === true
  );
  const disposicion = $derived<SourceDisposition>(origenDeRed ? 'leave' : disposition);

  const ready = $derived(cleanPath(source).length > 0 && cleanPath(destination).length > 0);

  async function start() {
    error = null;
    // Borrar originales no se hace sin preguntar: es lo único irreversible.
    if (
      disposicion === 'delete' &&
      !(await confirmar({
        titulo: '¿Borrar los originales?',
        mensaje:
          'Cada PDF del origen se eliminará después de entregarse completo en el destino. ' +
          'Los que fallen se quedan donde están. Esto no se puede deshacer.',
        aceptar: 'Sí, borrarlos al entregar',
        volver: 'Volver',
        peligro: true
      }))
    ) {
      return;
    }
    starting = true;
    try {
      await jobStore.startFolder({
        source: cleanPath(source),
        destination: cleanPath(destination),
        disposition: disposicion,
        watch: puedeVigilar && watch,
        task,
        oracle,
        lectura,
        tipo,
        corte,
        agrupar,
        ...(tipoDocumento ? { tipoDocumento } : {}),
        ...(acta ? { acta } : {}),
        ...(modoRetomar !== 'no' ? { retomar: modoRetomar } : {}),
        ...(paralelo ? { paralelo } : {})
      });
    } catch (problem) {
      error = (problem as Error).message;
    } finally {
      starting = false;
    }
  }
</script>

<div class="panel panel-inset carpeta">
  <p class="lead">
    El servicio lee carpetas de <b>esta máquina</b> o de la <b>red</b> y escribe en esta máquina.
    No se sube nada: toma los PDF
    de la carpeta —tantos a la vez como diga <b>Archivos en paralelo</b>—, los procesa y deja
    lo que sale de cada uno en el destino.
  </p>

  <div class="field">
    <span class="caps">Carpeta de origen</span>
    <div class="control">
      <input
        class="input mono"
        type="text"
        spellcheck="false"
        placeholder={String.raw`C:\Users\usuario\Desktop\ENTRADA`}
        bind:value={source}
        onpaste={(event) => {
          event.preventDefault();
          source = cleanPath(event.clipboardData?.getData('text') ?? '');
        }}
        onblur={() => (source = cleanPath(source))}
      />
      <button
        type="button"
        class="btn btn-icon pick"
        onclick={() => choose('origen')}
        title="Elegir la carpeta de origen"
        aria-label="Elegir la carpeta de origen"
      >
        <Icono nombre="carpeta" />
      </button>
    </div>
    <small>
      Elíjala con el icono, o pegue la ruta. Si trae comillas, se quitan solas. También vale
      una carpeta de red (<span class="mono">\\servidor\recurso\…</span>): si pide usuario y
      clave, se le preguntarán.
    </small>
  </div>

  {#if analizando || analisis || errorDeAnalisis}
    <div class="analisis">
      <SugerenciaDeTipo
        {habilidadId}
        carpeta={analisis}
        cargando={analizando}
        error={errorDeAnalisis}
        onusar={(id) => onusarHabilidad?.(id)}
      />
      {#if analisis && analisis.total_exacto === false}
        <!-- Una carpeta enorme no se cuenta entera para sugerir: la corrida sí
             la recorre, por lotes, y empieza sin esperar a terminar de contar. -->
        <small>
          Se miraron {analisis.mirados} de más de {analisis.total.toLocaleString('es-CO')} PDF. Al
          procesar se recorren todos, por lotes, sin esperar a contarlos.
        </small>
      {:else if analisis && analisis.mirados < analisis.total}
        <small>Se miraron {analisis.mirados} de {analisis.total} PDF.</small>
      {/if}
    </div>
  {/if}

  <div class="field">
    <span class="caps">Carpeta de destino</span>
    <div class="control">
      <input
        class="input mono"
        type="text"
        spellcheck="false"
        placeholder={String.raw`C:\Users\usuario\Desktop\SALIDA`}
        bind:value={destination}
        onpaste={(event) => {
          event.preventDefault();
          destination = cleanPath(event.clipboardData?.getData('text') ?? '');
        }}
        onblur={() => (destination = cleanPath(destination))}
      />
      <button
        type="button"
        class="btn btn-icon pick"
        onclick={() => choose('destino')}
        title="Elegir la carpeta de destino"
        aria-label="Elegir la carpeta de destino"
      >
        <Icono nombre="carpeta" />
      </button>
    </div>
    <small>Se crea si no existe. No puede estar dentro del origen.</small>
  </div>

  <fieldset>
    <legend class="caps">Al terminar cada original</legend>
    <div class="choices">
      {#each DISPOSITIONS as option (option.id)}
        <button
          type="button"
          class="panel panel-interactive opcion"
          aria-pressed={disposicion === option.id}
          disabled={origenDeRed && option.id !== 'leave'}
          onclick={() => (disposition = option.id)}
        >
          <b>{option.label}</b>
          <small>{option.hint}</small>
        </button>
      {/each}
    </div>
    {#if origenDeRed}
      <small>En una carpeta de red el original no se toca: sólo se lee.</small>
    {/if}
  </fieldset>

  <fieldset>
    <legend class="caps">Lo que ya está en el destino</legend>
    <div class="choices">
      {#each opcionesDeRetomar as option (option.id)}
        <button
          type="button"
          class="panel panel-interactive opcion"
          aria-pressed={modoRetomar === option.id}
          onclick={() => (retomar = option.id)}
        >
          <b>{option.label}</b>
          <small>{option.hint}</small>
        </button>
      {/each}
    </div>
    {#if modoRetomar === 'faltantes' || modoRetomar === 'revisar'}
      <small>
        Se compara cada página del origen con los PDF del destino. Queda un
        <b>00.CONTROL DE ENTREGA.xlsx</b> en la raíz del destino.
      </small>
    {/if}
  </fieldset>

  {#if puedeVigilar}
    <label class="toggle">
      <input type="checkbox" bind:checked={watch} />
      <span>
        <b>Vigilar la carpeta</b>
        <small>Seguir esperando archivos nuevos en vez de terminar al vaciarla.</small>
      </span>
    </label>
  {/if}

  {#if error}
    <p class="inline-error">{error}</p>
  {/if}

  <button class="btn btn-primary btn-block" onclick={start} disabled={!ready || starting}>
    {starting
      ? 'Iniciando…'
      : modoRetomar === 'faltantes'
        ? 'Retomar carpeta'
        : modoRetomar === 'revisar'
          ? 'Revisar destino'
          : modoRetomar === 'todo'
            ? 'Procesar todo otra vez'
            : watch
            ? 'Vigilar carpeta'
            : 'Procesar carpeta'}
  </button>
</div>

{#if picking}
  <FolderPicker
    title={picking === 'origen' ? 'Elegir la carpeta de origen' : 'Elegir la carpeta de destino'}
    start={picking === 'origen' ? cleanPath(source) : cleanPath(destination)}
    onpick={(path) => {
      if (picking === 'origen') source = path;
      else destination = path;
      picking = null;
    }}
    onclose={() => (picking = null)}
  />
{/if}

<style>
  /* El `.panel-inset` común: un escalón por debajo de la tarjeta del asistente
     que lo contiene. El borde es el de siempre; antes llevaba el amarillo de
     una serie, y las series son sólo para datos. */
  .carpeta {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  .lead {
    margin: 0;
    font-size: var(--text-sm);
    line-height: 1.5;
    color: var(--muted);
  }
  .lead b {
    color: var(--ink-2);
  }

  label,
  .field {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }

  /* El icono va dentro del recuadro, no al lado: la ruta y el botón que la
     elige son un solo control, y así se lee como uno. El campo es el `.input`
     común sin su borde; el borde (`--control`) y el foco -- el mismo de
     `.input`: borde y 1 px más del anillo -- los lleva el recuadro. */
  .control {
    display: flex;
    align-items: stretch;
    border: 1px solid var(--control);
    border-radius: var(--radius);
    background: var(--surface-2);
    overflow: hidden;
    transition:
      border-color var(--duration-fast) var(--ease-out),
      box-shadow var(--duration-fast) var(--ease-out);
  }
  .control:focus-within {
    border-color: var(--ring);
    box-shadow: 0 0 0 1px var(--ring);
  }
  .control .input {
    flex: 1;
    min-width: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
    box-shadow: none;
  }
  /* El `.btn-icon` común, encajado en el recuadro: sin radio propio, alto del
     campo y un filete que lo separa de la ruta. */
  .pick {
    --icono: 16px;
    width: 34px;
    height: auto;
    border-radius: 0;
    border-left-color: var(--hairline);
    background: var(--plane);
  }
  /* El fondo propio de arriba tapa el de `.btn-icon` al pasar (lo local gana a
     la capa de componentes), así que se repite aquí. */
  .pick:hover:not(:disabled) {
    background: var(--accent-soft);
  }
  .pick:disabled {
    cursor: progress;
  }

  small {
    font-size: var(--text-xs);
    color: var(--muted);
  }
  /* La ruta de ejemplo, en la letra de los códigos. */
  small .mono {
    font-family: var(--font-mono);
  }

  fieldset {
    margin: 0;
    border: 0;
    padding: 0;
  }
  legend {
    margin-bottom: var(--space-1);
    padding: 0;
  }

  .choices {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 4px;
  }
  /* Cada opción es una tarjeta-control (`.panel-interactive`): la elegida
     lleva `aria-pressed` y el estado elegido común. Aquí sólo un relleno más
     apretado, para que tres quepan en fila. */
  .opcion {
    display: flex;
    flex-direction: column;
    gap: 1px;
    padding: var(--space-2) var(--space-3);
    text-align: left;
    color: var(--muted);
  }
  .opcion b {
    font-size: var(--text-sm);
    font-weight: 600;
  }
  /* Lo que no cabe con este origen -- apartar o borrar un original de la red --. */
  .opcion:disabled > * {
    opacity: 0.55;
  }

  .toggle {
    flex-direction: row;
    align-items: flex-start;
    gap: 0.55rem;
    cursor: pointer;
  }
  .toggle input {
    margin-top: 0.2rem;
    accent-color: var(--accent);
  }
  .toggle span {
    display: flex;
    flex-direction: column;
  }
  .toggle b {
    font-size: var(--text-sm);
    font-weight: 600;
  }

  .carpeta > .inline-error {
    margin: 0;
  }

  .analisis {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    margin: -0.25rem 0 0.5rem;
  }
  .analisis small {
    font-size: var(--text-xs);
    color: var(--muted);
  }
</style>
