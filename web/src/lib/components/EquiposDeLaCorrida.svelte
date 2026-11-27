<script lang="ts">
  /**
   * Los equipos de una corrida compartida, en vivo, y la orden de pararlos (lo
   * pidió el operador el 2026-11-26: «un monitoreo para ver los que están
   * conectados y poder desconectarlos»). Son 6 o 7 PC sobre el mismo destino;
   * con «Parar todos con calma» quedan quietos antes de actualizarlos juntos.
   *
   * La lista la arma el servicio con lo que ya miró, sin salir a la red
   * (`GET /api/folder-runs/{id}/equipos`): se pide al montarse y cada 5 s
   * mientras la corrida sigue y la pestaña se ve, nunca dos a la vez ni
   * mientras va una orden. Con la corrida terminada es la foto de cuando este
   * equipo se retiró, y se dice así. Las palabras, el orden y a quién se le
   * ofrece cada botón están en `$lib/equipos`.
   *
   * Desde el 2026-11-27 dice también quién es el principal -- el primero en
   * lanzar, o quien lo releva si cae, que escribe los Excel generales y cierra
   * la corrida --, la velocidad en PDF por minuto -- la de ahora y la
   * acumulada, en total y por PC -- y los recursos de cada PC, con el aviso del
   * servicio si el principal no es el que más tiene. El operador: «llevar un
   * promedio de velocidad de procesamiento de archivos por minuto contando los
   * PC activos». Con la foto no se pinta nada de «ahora»: ya no lo hay.
   */
  import { onMount, untrack } from 'svelte';

  import { equiposDeLaCorrida, pararEquipo } from '$lib/api';
  import { explicar } from '$lib/avisos.svelte';
  import { confirmar } from '$lib/confirmar.svelte';
  import {
    accionesDe,
    alertaDeRecursos,
    cifra,
    estadoDe,
    falloDeLaOrden,
    FOTO_AL_RETIRARSE,
    haceCuanto,
    idCorto,
    lineasDeVelocidad,
    objetivosDePararTodos,
    partesDeRecursos,
    porMinuto,
    porQueAparte,
    preguntaDeParar,
    preguntaDePararTodos,
    promedioDe,
    recursosEnAlerta,
    resumen,
    rotuloDe,
    separar
  } from '$lib/equipos';
  import type { EquipoDeLaCorrida, EquiposDeLaCorrida, FolderRun, OrdenDeParar } from '$lib/types';

  interface Props {
    run: FolderRun;
  }

  let { run }: Props = $props();

  /** Cada cuánto se pregunta: los equipos laten cada 10 s y el servicio contesta sin tocar la red. */
  const CADA_MS = 5_000;
  const EN_MARCHA = ['scanning', 'processing', 'watching', 'recovering'];

  let datos = $state<EquiposDeLaCorrida | null>(null);
  let errorDeLaLista = $state<string | null>(null);
  let errorDeLaOrden = $state<string | null>(null);
  /** La orden que se está mandando: «<id>:<modo>», o «todos». */
  let ordenando = $state<string | null>(null);
  let visible = $state(true);

  const activa = $derived(EN_MARCHA.includes(run.state));
  const sondear = $derived(activa && Boolean(run.compartida) && visible);
  /** Parar sólo se ofrece con la corrida en marcha, aquí y en lo que contestó el servicio. */
  const sePuedeOrdenar = $derived(activa && Boolean(datos?.compartida && datos.activa));
  /**
   * Con la corrida terminada -- aquí o en lo que contestó el servicio -- la
   * lista es la foto de cuando este equipo se retiró: el servicio ya no mira a
   * los demás. Ni resumen de vivos ni puntos que laten.
   */
  const foto = $derived(datos !== null && !(activa && datos.activa));
  const grupos = $derived(separar(datos?.equipos ?? []));
  const frase = $derived(!foto && grupos.deEsta.length ? resumen(grupos.deEsta) : null);
  /** La velocidad y el principal; con la foto, sin las de ahora. */
  const lineas = $derived(datos ? lineasDeVelocidad(datos, !foto) : []);
  const objetivos = $derived(objetivosDePararTodos(grupos.deEsta, sePuedeOrdenar));

  /** El espacio que no parte la línea. */
  const NO_PARTE = '\u00a0';

  /**
   * Los recursos de un PC en una casilla que puede ir en dos líneas, partidas
   * sólo entre un trozo y otro: dentro de cada trozo los espacios no parten, y
   * el punto se queda al final de la línea («RAM 12,4 / 15,5 GB ·»).
   */
  function enTrozos(partes: readonly string[]): string {
    return partes.map((parte) => parte.replace(/ /g, NO_PARTE)).join(`${NO_PARTE}· `);
  }

  /*
   * Mientras va una orden no se pregunta, y la lista que devuelve la orden --
   * que ya la trae puesta -- se pinta siempre. Cada pregunta lleva su turno:
   * una lista pedida antes de la orden, si llega después, ya no pinta.
   */
  let turno = 0;
  let pidiendo = false;
  let controlador: AbortController | null = null;

  async function traer(): Promise<void> {
    if (pidiendo || ordenando !== null) return;
    pidiendo = true;
    const mio = ++turno;
    controlador = new AbortController();
    try {
      const lista = await equiposDeLaCorrida(run.id, controlador.signal);
      if (mio === turno) datos = lista;
      errorDeLaLista = null;
    } catch (problema) {
      if (problema instanceof DOMException && problema.name === 'AbortError') return;
      // Se dice y la última lista se queda: un tropiezo de la red no borra a nadie.
      errorDeLaLista = `La lista de equipos no se pudo actualizar. ${explicar(problema)}`;
    } finally {
      pidiendo = false;
      controlador = null;
    }
  }

  onMount(() => {
    const alCambiar = () => {
      visible = document.visibilityState === 'visible';
      // Al volver a verse, la lista de ahora, sin esperar al reloj.
      if (visible && activa) void traer();
    };
    visible = document.visibilityState === 'visible';
    document.addEventListener('visibilitychange', alCambiar);
    void traer();
    return () => {
      document.removeEventListener('visibilitychange', alCambiar);
      controlador?.abort();
    };
  });

  // Cada 5 s mientras la corrida sigue, es compartida y la pestaña se ve.
  $effect(() => {
    if (!sondear) return;
    const reloj = setInterval(() => void traer(), CADA_MS);
    return () => clearInterval(reloj);
  });

  // Al terminar la corrida, una vez más: la lista con la que se quedó.
  let estabaActiva = false;
  $effect(() => {
    const ahora = activa;
    if (estabaActiva && !ahora) untrack(() => void traer());
    estabaActiva = ahora;
  });

  /** La lista que devolvió una orden: se pinta siempre, y la pedida antes ya no pisa. */
  function pintarLaDeLaOrden(lista: EquiposDeLaCorrida): void {
    turno++;
    datos = lista;
  }

  /** Al soltar la orden: si la corrida terminó mientras iba, la lista con la que se quedó. */
  function alTerminarLaOrden(): void {
    ordenando = null;
    if (!activa) void traer();
  }

  async function ordenar(equipo: EquipoDeLaCorrida, modo: OrdenDeParar['modo']): Promise<void> {
    if (!(await confirmar(preguntaDeParar(equipo, modo, grupos.deEsta)))) return;
    ordenando = `${equipo.id}:${modo}`;
    errorDeLaOrden = null;
    try {
      pintarLaDeLaOrden(await pararEquipo(run.id, equipo.id, modo));
    } catch (problema) {
      errorDeLaOrden = falloDeLaOrden(equipo, explicar(problema));
    } finally {
      alTerminarLaOrden();
    }
  }

  /**
   * Uno tras otro, con este equipo al final (`objetivosDePararTodos`). Lo que
   * falle con uno no frena a los demás: se dice todo junto al terminar.
   */
  async function pararTodos(): Promise<void> {
    const aQuienes = objetivos;
    if (!aQuienes.length || !(await confirmar(preguntaDePararTodos(aQuienes)))) return;
    ordenando = 'todos';
    errorDeLaOrden = null;
    const fallos = new Set<string>();
    try {
      for (const equipo of aQuienes) {
        try {
          pintarLaDeLaOrden(await pararEquipo(run.id, equipo.id, 'calma'));
        } catch (problema) {
          fallos.add(falloDeLaOrden(equipo, explicar(problema)));
        }
      }
      errorDeLaOrden = fallos.size ? [...fallos].join(' ') : null;
    } finally {
      alTerminarLaOrden();
    }
  }
</script>

{#snippet quien(equipo: EquipoDeLaCorrida, aparte: string | null)}
  <span class="quien">
    <span class="nombre">{equipo.equipo}</span>
    {#if idCorto(equipo)}
      <span class="arranque">{idCorto(equipo)}</span>
    {/if}
    {#if equipo.principal}
      <span
        class="pill pill-good pill-sm"
        title="Escribe los Excel generales y cierra la corrida. Es el primero que lanzó o, si ese ya no puede, el que lleva más tiempo en la corrida."
      >
        Principal
      </span>
    {/if}
    {#if equipo.este}
      <span class="pill pill-sm">este equipo</span>
    {/if}
    {#if aparte}
      <span class="pill pill-sm pill-neutral">{aparte}</span>
    {/if}
  </span>
{/snippet}

{#snippet comoEsta(equipo: EquipoDeLaCorrida, siCae: string)}
  {@const estado = estadoDe(equipo, !foto)}
  <span class="estado">
    <span
      class="status-dot status-dot-sm {estado.tono}"
      class:pulse-slow={estado.latiendo}
      aria-hidden="true"
    ></span>
    {estado.etiqueta}
  </span>
  {#if estado.caido}
    <small class="explica">{siCae}</small>
  {/if}
{/snippet}

{#snippet recursos(equipo: EquipoDeLaCorrida)}
  {@const partes = partesDeRecursos(equipo.recursos)}
  {@const alerta = alertaDeRecursos(equipo.recursos)}
  {#if partes.length}
    <!-- Justo de RAM o de disco: el tono de aviso y el ⚠, que no dependa sólo
         del color, y el porqué al pasar y para quien lee la pantalla. El ⚠ va
         pegado al primer trozo: la línea no se parte detrás de él. -->
    <span class="recursos" class:alerta={recursosEnAlerta(equipo.recursos)} title={alerta ?? undefined}>
      {#if alerta}<span aria-hidden="true">⚠&nbsp;</span>{/if}{enTrozos(partes)}
      {#if alerta}
        <span class="sr-only">. {alerta}</span>
      {/if}
    </span>
  {:else}
    —
  {/if}
{/snippet}

<section class="equipos" aria-label="Equipos conectados a la corrida">
  <header class="cabeza">
    <span class="caps">Equipos conectados</span>
    {#if foto}
      <span class="foto">{FOTO_AL_RETIRARSE}</span>
    {:else if frase}
      <span class="resumen tabular">{frase}</span>
    {/if}
    {#if objetivos.length}
      <button type="button" class="btn btn-sm todos" onclick={pararTodos} disabled={ordenando !== null}>
        {ordenando === 'todos' ? 'Ordenando…' : 'Parar todos con calma'}
      </button>
    {/if}
  </header>

  {#if lineas.length}
    <!-- La velocidad de la corrida y quién es el principal (2026-11-27): cifras
         con su filete, no cajas. Los totales los suma el servicio. -->
    <dl class="cifras">
      {#each lineas as linea (linea.clave)}
        <div class="stat">
          <dt class="stat-label">{linea.rotulo}</dt>
          <dd class="stat-value tabular">{linea.valor}</dd>
          {#if linea.nota}
            <dd class="stat-note">{linea.nota}</dd>
          {/if}
        </div>
      {/each}
    </dl>
  {/if}
  {#if datos?.aviso_de_recursos}
    <!-- «El principal … tiene menos RAM … que …: conviene lanzar primero en el
         PC con más recursos.» No cambia quién es el principal: lo es el
         primero en lanzar. -->
    <p class="nota warn" role="status">{datos.aviso_de_recursos}</p>
  {/if}

  {#if errorDeLaOrden}
    <p class="inline-error" role="alert">{errorDeLaOrden}</p>
  {/if}
  {#if errorDeLaLista}
    <p class="inline-error">{errorDeLaLista}</p>
  {/if}

  {#if !datos}
    {#if !errorDeLaLista}
      <p class="vacio">Mirando quién está conectado…</p>
    {/if}
  {:else if !grupos.deEsta.length && !grupos.otros.length}
    <p class="vacio">Ningún equipo late ahora en este destino.</p>
  {:else}
    {#if grupos.deEsta.length}
      <div class="caja">
        <table class="tabla">
          <caption class="sr-only">Equipos de esta corrida</caption>
          <thead>
            <tr>
              <th scope="col">Equipo</th>
              <th scope="col">Estado</th>
              <th scope="col" class="cifra">Hechos</th>
              <th scope="col" class="cifra">En curso</th>
              {#if !foto}
                <th scope="col" class="cifra" title="PDF por minuto en sus últimos 10 minutos">Ahora</th>
              {/if}
              <th scope="col" class="cifra" title="PDF por minuto desde que se unió a la corrida">Desde que se unió</th>
              <th scope="col">Recursos</th>
              <th scope="col">Latido</th>
              <th scope="col" class="derecha">Acciones</th>
            </tr>
          </thead>
          <tbody>
            {#each grupos.deEsta as equipo (equipo.id)}
              {@const acciones = accionesDe(equipo, sePuedeOrdenar)}
              <tr>
                <th scope="row">{@render quien(equipo, null)}</th>
                <td>
                  {@render comoEsta(
                    equipo,
                    'Sus PDF los toman los demás solos y su latido se borra solo a los 3 minutos.'
                  )}
                </td>
                <td class="cifra tabular">{cifra(equipo.hechos)}</td>
                <td class="cifra tabular">{cifra(equipo.en_curso)}</td>
                {#if !foto}
                  <td class="cifra tabular">{porMinuto(equipo.pdf_por_minuto)}</td>
                {/if}
                <td class="cifra tabular">{porMinuto(promedioDe(equipo))}</td>
                <td class="tabular">{@render recursos(equipo)}</td>
                <td class="tabular">{haceCuanto(equipo.quieto_hace)}</td>
                <td class="derecha">
                  {#if acciones.calma || acciones.ya}
                    <span class="acciones">
                      {#if acciones.calma}
                        <button
                          type="button"
                          class="btn btn-sm"
                          disabled={ordenando !== null}
                          aria-label={`Parar con calma ${rotuloDe(equipo)}`}
                          onclick={() => ordenar(equipo, 'calma')}
                        >
                          {ordenando === `${equipo.id}:calma` ? 'Ordenando…' : 'Parar con calma'}
                        </button>
                      {/if}
                      {#if acciones.ya}
                        <button
                          type="button"
                          class="btn btn-sm btn-danger"
                          disabled={ordenando !== null}
                          aria-label={`Parar ya ${rotuloDe(equipo)}`}
                          onclick={() => ordenar(equipo, 'ya')}
                        >
                          {ordenando === `${equipo.id}:ya` ? 'Ordenando…' : 'Parar ya'}
                        </button>
                      {/if}
                    </span>
                  {:else}
                    <!-- Sin botones: el porqué del servicio, al pasar y para quien
                         lee la pantalla. -->
                    <span class="sin-acciones" title={acciones.porQueNo ?? undefined}>
                      <span aria-hidden="true">—</span>
                      {#if acciones.porQueNo}
                        <span class="sr-only">{acciones.porQueNo}</span>
                      {/if}
                    </span>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}

    {#if grupos.otros.length}
      <!-- Latidos de otra corrida o de otra versión sobre este destino: no
           reparten esta corrida, así que van aparte y sin botones. -->
      <div class="aparte">
        <span class="caps">De otra corrida o de otra versión</span>
        <small>No reparten el trabajo de esta corrida y no se paran desde aquí.</small>
      </div>
      <div class="caja">
        <table class="tabla">
          <caption class="sr-only">Equipos de otra corrida o de otra versión del bot</caption>
          <thead>
            <tr>
              <th scope="col">Equipo</th>
              <th scope="col">Estado</th>
              <th scope="col" class="cifra">Hechos</th>
              <th scope="col">Latido</th>
            </tr>
          </thead>
          <tbody>
            {#each grupos.otros as equipo (equipo.id)}
              <tr>
                <th scope="row">{@render quien(equipo, porQueAparte(equipo))}</th>
                <td>{@render comoEsta(equipo, 'Su latido se borra solo a los 3 minutos.')}</td>
                <td class="cifra tabular">{cifra(equipo.hechos)}</td>
                <td class="tabular">{haceCuanto(equipo.quieto_hace)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  {/if}
</section>

<style>
  /* Una caja como la línea «Red», encima de las cifras de la corrida. */
  .equipos {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: var(--space-2);
    border: 1px solid var(--hairline);
    border-radius: var(--radius-md);
    padding: var(--space-3);
  }

  .cabeza {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-3);
  }
  .resumen {
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--ink);
  }
  /* La corrida terminada: una foto, no un estado en vivo. */
  .foto {
    font-size: var(--text-sm);
    color: var(--muted);
  }
  /* A la derecha; con el ancho del teléfono baja a su propia línea. */
  .todos {
    margin-left: auto;
  }

  /* La velocidad y el principal (2026-11-27): cifras con su filete, que con el
     ancho del teléfono bajan a otra línea. */
  .cifras {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-6);
    margin: 0;
  }
  .cifras dd {
    margin: 0;
  }
  /* Un escalón por debajo de las de un trabajo: van dentro de esta caja. Un
     nombre largo («DESKTOP-UMCOEU8 (35cf6a)») se parte antes que salirse. */
  .cifras .stat-value {
    font-size: var(--text-lg);
    overflow-wrap: anywhere;
  }
  /* El aviso de recursos, del tamaño de la tabla. */
  .equipos > .nota {
    margin: 0;
    font-size: var(--text-sm);
  }

  .equipos > .inline-error {
    margin: 0;
  }
  .vacio {
    margin: 0;
    font-size: var(--text-sm);
    color: var(--muted);
  }

  /* Con el ancho del teléfono la tabla se desliza dentro de su caja; la página, nunca. */
  /* Posicionada: el texto `sr-only` de dentro es `position: absolute` y, sin
     un ancestro posicionado, se salía de la caja y hacía deslizar la página
     entera (390 → 700 px en un teléfono, 2026-11-27). */
  .caja {
    position: relative;
    max-width: 100%;
    overflow-x: auto;
  }
  .tabla {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-sm);
  }
  .tabla th,
  .tabla td {
    border-top: 1px solid var(--rule);
    padding: var(--space-2) var(--space-3) var(--space-2) 0;
    text-align: left;
    vertical-align: baseline;
    white-space: nowrap;
  }
  /* La cabecera en versalitas, como todas las tablas. */
  .tabla thead th {
    border-top: 0;
    padding-top: 0;
    font-size: var(--text-2xs);
    font-weight: 600;
    letter-spacing: var(--tracking-caps);
    text-transform: uppercase;
    color: var(--muted);
  }
  .tabla tbody th {
    font-weight: 400;
  }
  .tabla .cifra {
    text-align: right;
  }
  /* Las acciones, pegadas a la derecha: con las columnas de velocidad y
     recursos la tabla mide ~1.100 px y «Parar ya» quedaba fuera de la vista en
     pantallas de 1366-1600 px (2026-11-27). */
  .tabla .derecha {
    position: sticky;
    right: 0;
    padding-right: 0;
    padding-left: var(--space-3);
    text-align: right;
    background: var(--surface-2);
  }

  .quien {
    display: inline-flex;
    align-items: baseline;
    gap: var(--space-2);
  }
  .nombre {
    font-weight: 600;
    color: var(--ink);
  }
  /* El arranque, apagado: distingue un PC reiniciado o dos PC con el mismo nombre. */
  .arranque {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--muted);
  }
  /* En línea y no en flex: el punto, vacío, correría la línea base de la fila. */
  .estado {
    color: var(--ink-2);
  }
  .estado .status-dot {
    margin-right: 2px;
    vertical-align: middle;
  }
  /* El caído explica en su fila qué pasa con lo suyo. */
  .explica {
    display: block;
    max-width: 22rem;
    margin-top: 2px;
    font-size: var(--text-xs);
    color: var(--muted);
    white-space: normal;
  }
  /* Los recursos pueden ir en dos líneas, partidas sólo entre un trozo y otro
     (`enTrozos`), para que las acciones no se vayan a la derecha de la caja;
     con poco ancho, la columna no baja de esto. */
  .recursos {
    display: block;
    min-width: 15rem;
    white-space: normal;
  }
  .recursos.alerta {
    color: var(--warning-ink);
  }
  .acciones {
    display: inline-flex;
    gap: var(--space-2);
  }
  .sin-acciones {
    color: var(--muted);
  }

  .aparte {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-1) var(--space-3);
    margin-top: var(--space-2);
  }
  .aparte small {
    font-size: var(--text-xs);
    color: var(--muted);
  }
</style>
