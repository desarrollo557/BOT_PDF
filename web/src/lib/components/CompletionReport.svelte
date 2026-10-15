<script lang="ts">
  import { descargarPlanilla, downloadUrl, origenInventarioUrl } from '$lib/api';
  import Icono from '$lib/components/Icono.svelte';
  import { consoleLog } from '$lib/console.svelte';
  import { formatBytes, formatDuration } from '$lib/format';
  import { jobStore } from '$lib/jobs.svelte';
  import { reports, type Completion } from '$lib/report.svelte';
  import { RUNGS, UNREADABLE } from '$lib/rungs';

  interface Props {
    completion: Completion;
  }

  let { completion }: Props = $props();

  const KIND: Record<Completion['kind'], string> = {
    documento: 'Documento procesado',
    lote: 'Lote procesado',
    carpeta: 'Carpeta procesada',
    tanda: 'Ejecución completa'
  };

  const clean = $derived(completion.failedDocuments === 0 && completion.reviewItems === 0);

  const capital = (texto: string) => texto.charAt(0).toUpperCase() + texto.slice(1);
  /** «Actas», «Resoluciones», «Unidades documentales»: lo que de verdad salió. */
  const Unidades = $derived(capital(completion.unidad[1]));
  const soloActas = $derived(completion.actas > 0 && completion.actas === completion.resolutions);
  const unidadDe = (cuantas: number, unidad: [string, string]) =>
    `${cuantas} ${cuantas === 1 ? unidad[0] : unidad[1]}`;

  /**
   * El gasto, separado por lo que se pagó.
   *
   * Las páginas se facturan al OCR y los tokens a la IA que resume; sumar las
   * peticiones de los dos decía «22 peticiones al OCR de pago» cuando once
   * eran resúmenes.
   */
  const proveedores = $derived(Object.values(completion.consumo?.proveedores ?? {}));
  const ocr = $derived(
    proveedores
      .filter((cuenta) => cuenta.paginas_facturadas > 0)
      .reduce(
        (total, cuenta) => ({
          paginas: total.paginas + cuenta.paginas_facturadas,
          peticiones: total.peticiones + cuenta.peticiones
        }),
        { paginas: 0, peticiones: 0 }
      )
  );
  const ia = $derived(
    proveedores
      .filter((cuenta) => cuenta.paginas_facturadas === 0)
      .reduce((total, cuenta) => total + cuenta.peticiones, 0)
  );

  /** Lo esencial en una frase, para quien escucha la pantalla en vez de verla. */
  const resumenHablado = $derived(
    [
      `${completion.documents - completion.failedDocuments} de ${completion.documents} documentos completos`,
      unidadDe(completion.resolutions, completion.unidad),
      `${completion.pages} páginas`,
      completion.reviewItems
        ? `${completion.reviewItems} por revisar`
        : 'nada pendiente de revisión'
    ].join(', ')
  );

  let bajando = $state<string | null>(null);
  let falloDeDescarga = $state<string | null>(null);

  async function bajarInventario(runId: string, nombre: string) {
    bajando = runId;
    falloDeDescarga = null;
    try {
      await descargarPlanilla(origenInventarioUrl(runId), nombre);
    } catch (problema) {
      falloDeDescarga = (problema as Error).message;
    } finally {
      bajando = null;
    }
  }

  /* -- teclado y foco -------------------------------------------------------
     Un diálogo modal que se deja atrás con el tabulador no es modal: el foco
     se iba a la pantalla de debajo, que no se ve. Al abrir se lleva al
     título, Tab y Mayús+Tab dan la vuelta dentro, Escape cierra, y al cerrar
     el foco vuelve a donde estaba. */
  let sheet = $state<HTMLDivElement | null>(null);
  let heading = $state<HTMLHeadingElement | null>(null);

  $effect(() => {
    const antes = document.activeElement as HTMLElement | null;
    heading?.focus();
    return () => antes?.focus?.();
  });

  function teclado(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.preventDefault();
      void dismiss();
      return;
    }
    if (event.key !== 'Tab' || !sheet) return;
    const enfocables = [
      ...sheet.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input, [tabindex]:not([tabindex="-1"])'
      )
    ];
    if (!enfocables.length) return;
    const primero = enfocables[0];
    const ultimo = enfocables[enfocables.length - 1];
    if (event.shiftKey && (document.activeElement === primero || document.activeElement === heading)) {
      event.preventDefault();
      ultimo.focus();
    } else if (!event.shiftKey && document.activeElement === ultimo) {
      event.preventDefault();
      primero.focus();
    }
  }

  /** Flechas entre pestañas, como en cualquier lista de pestañas. */
  function tecladoDePestanas(event: KeyboardEvent) {
    const ids = tabs.map((item) => item.id);
    const actual = ids.indexOf(tab);
    let siguiente = actual;
    if (event.key === 'ArrowRight') siguiente = (actual + 1) % ids.length;
    else if (event.key === 'ArrowLeft') siguiente = (actual - 1 + ids.length) % ids.length;
    else if (event.key === 'Home') siguiente = 0;
    else if (event.key === 'End') siguiente = ids.length - 1;
    else return;
    event.preventDefault();
    tab = ids[siguiente];
    document.getElementById(`informe-tab-${tab}`)?.focus();
  }

  /**
   * Cerrar el informe deja la pantalla lista para el siguiente lote. Siempre.
   *
   * Un operador que procesa caja tras caja no quiere empezar la siguiente con
   * las fichas de la anterior debajo: cerrar el informe es la señal de que ya
   * miró lo que pasó. Se olvidan los trabajos terminados, que es distinto de
   * borrarlos -- el trabajo queda en el archivo, este informe se vuelve a abrir
   * desde ahí, y lo que quedó por revisar sigue listado en Revisión, que se
   * guarda su propia copia justamente para que limpiar no le quite nada.
   */
  async function dismiss(): Promise<void> {
    reports.close();
    try {
      await jobStore.clear();
      // Y si no queda ninguna carpeta en marcha, se borran también las rutas
      // del formulario. No hace falta recordar si se marcó "Vigilar la
      // carpeta": una carpeta vigilada sigue viva en `activeRuns` esperando
      // archivos nuevos, y una que terminó no. El estado lo dice mejor que la
      // casilla, porque también acierta cuando la vigilancia se detuvo a mano.
      if (jobStore.activeRuns.length === 0) jobStore.resetWorkspace();
    } catch (problem) {
      // Que no se pueda limpiar no es motivo para dejar el informe abierto: ya
      // se cerró, y el motivo queda escrito donde se miran estas cosas.
      consoleLog.push(
        'WARN',
        `no se pudo limpiar la pantalla: ${(problem as Error).message}`,
        'warn'
      );
    }
  }
  const rate = $derived(
    completion.elapsedSeconds >= 1 ? completion.pages / completion.elapsedSeconds : 0
  );

  /** Rungs that actually answered a page, in cascade order. */
  const rungs = $derived(
    [...RUNGS, UNREADABLE]
      .map((rung) => ({ rung, count: completion.provenance[rung.key] ?? 0 }))
      .filter((entry) => entry.count > 0)
  );
  const counted = $derived(rungs.reduce((sum, entry) => sum + entry.count, 0));

  /**
   * The report is one screen with sections behind tabs, not one long scroll.
   *
   * A single file produces a page worth of report; a folder of eighty produces
   * eighty rows of documents and several hundred resolutions. Stacking all of
   * it vertically buries the four numbers anyone actually opens this for, so
   * the totals stay pinned at the top and everything else waits behind a tab.
   */
  const tabs = $derived(
    [
      { id: 'resumen', label: 'Resumen', count: 0 },
      { id: 'unidades', label: 'Unidades', count: completion.parts?.length ?? 0 },
      { id: 'documentos', label: 'Documentos', count: completion.items.length },
      { id: 'resoluciones', label: Unidades, count: completion.codes.length }
    ].filter((tab) => tab.id === 'resumen' || tab.count > 0)
  );

  let tab = $state('resumen');
  /** Narrows the resolution list, which is the only section that gets long. */
  let filter = $state('');

  const shown = $derived.by(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return completion.codes;
    return completion.codes.filter(
      (entry) =>
        entry.code.toLowerCase().includes(needle) ||
        (entry.title ?? '').toLowerCase().includes(needle) ||
        entry.document.toLowerCase().includes(needle)
    );
  });

  const failed = $derived(completion.items.filter((item) => item.state === 'failed'));

  /** El reparto de la lectura dicho con palabras, para el lector de pantalla. */
  const repartoHablado = $derived(
    rungs.map((entry) => `${entry.rung.label}: ${entry.count} páginas`).join(', ')
  );

  /** Lo que pasó por el camino, sólo lo que pasó: tres ceros no informan. */
  const incidencias = $derived(
    [
      completion.escalated
        ? `${completion.escalated} página${completion.escalated === 1 ? '' : 's'} se releyeron (${counted ? ((100 * completion.escalated) / counted).toFixed(1) : '0.0'} %)`
        : null,
      completion.repairs
        ? `${completion.repairs} corrección${completion.repairs === 1 ? '' : 'es'} de OCR`
        : null,
      completion.quarantine ? `${completion.quarantine} en cuarentena` : null
    ].filter(Boolean)
  );

  function when(at: number): string {
    return new Date(at).toLocaleString('es', { dateStyle: 'medium', timeStyle: 'medium' });
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<div
  class="scrim"
  role="presentation"
  onclick={(event) => {
    if (event.target === event.currentTarget) void dismiss();
  }}
>
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <div
    class="sheet"
    role="dialog"
    aria-modal="true"
    aria-labelledby="informe-titulo"
    aria-describedby="informe-resumen"
    tabindex="-1"
    bind:this={sheet}
    onkeydown={teclado}
  >
    <header>
      <div class="who">
        <span class="pill badge" class:pill-good={clean} class:pill-warn={!clean}>
          {KIND[completion.kind]}{clean ? '' : ' con pendientes'}
        </span>
        <h2 id="informe-titulo" tabindex="-1" bind:this={heading} title={completion.title}>
          {completion.title}
        </h2>
        <p id="informe-resumen" class="sr-only">{resumenHablado}.</p>
      </div>
      <div class="meta">
        {#if completion.operator}
          <span class="pill"><span class="sr-only">Operador: </span>{completion.operator}</span>
        {/if}
        <time datetime={new Date(completion.finishedAt).toISOString()}>
          {when(completion.finishedAt)}
        </time>
        <button class="btn btn-icon" onclick={() => void dismiss()} aria-label="Cerrar">
          <Icono nombre="cerrar" />
        </button>
      </div>
    </header>

    <!-- Siempre a la vista: es lo que se viene a mirar. -->
    <dl class="tiles">
      <div>
        <dt>Documentos</dt>
        <dd class="tabular" class:warn={completion.failedDocuments > 0}>
          {completion.documents}
        </dd>
        <dd class="note">
          {completion.failedDocuments
            ? `${completion.failedDocuments} con error`
            : 'todos completos'}
        </dd>
      </div>
      <div>
        <dt>{Unidades}</dt>
        <dd class="tabular">{completion.resolutions}</dd>
        <dd class="note">{soloActas ? 'inventariadas en Excel' : 'archivos generados'}</dd>
      </div>
      <div>
        <dt>Páginas</dt>
        <dd class="tabular">{completion.pages}</dd>
        <dd class="note">{rate ? `${rate.toFixed(1)} p/s` : 'leídas'}</dd>
      </div>
      <div>
        <dt>Peso neto</dt>
        <dd class="tabular">{formatBytes(completion.bytes)}</dd>
        <dd class="note">de los PDF de origen</dd>
      </div>
      <div>
        <dt>Tardó</dt>
        <dd class="tabular">{formatDuration(completion.elapsedSeconds)}</dd>
        <dd class="note">de reloj</dd>
      </div>
      {#if ocr.paginas}
        <div>
          <dt>Páginas facturadas</dt>
          <dd class="tabular">{ocr.paginas.toLocaleString('es-CO')}</dd>
          <dd class="note">
            {ocr.peticiones} {ocr.peticiones === 1 ? 'petición' : 'peticiones'} al OCR de pago
          </dd>
        </div>
      {/if}
      {#if completion.consumo?.tokens}
        <div>
          <dt>Tokens de IA</dt>
          <dd class="tabular">{completion.consumo.tokens.toLocaleString('es-CO')}</dd>
          <dd class="note">
            {completion.consumo.tokens_entrada.toLocaleString('es-CO')} entrada ·
            {completion.consumo.tokens_salida.toLocaleString('es-CO')} salida{#if ia}{' · '}{ia}
              {ia === 1 ? 'consulta' : 'consultas'}{/if}
          </dd>
        </div>
      {/if}
      {#if completion.consumo && completion.consumo.coste_estimado !== null}
        <div>
          <dt>Costó</dt>
          <dd class="tabular">
            {completion.consumo.coste_estimado.toFixed(2)} {completion.consumo.moneda}
          </dd>
          <dd class="note">según el precio configurado</dd>
        </div>
      {/if}
      {#if completion.consumo && (completion.consumo.rechazos || completion.consumo.fallos)}
        <div>
          <dt>Proveedor</dt>
          <dd class="tabular" class:warn={completion.consumo.fallos > 0}>
            {completion.consumo.rechazos + completion.consumo.fallos}
          </dd>
          <dd class="note">
            {completion.consumo.rechazos} esperas · {completion.consumo.fallos} sin respuesta
          </dd>
        </div>
      {/if}
      <div>
        <dt>Requiere revisión</dt>
        <dd class="tabular" class:warn={completion.reviewItems > 0}>{completion.reviewItems}</dd>
        <dd class="note">
          {completion.reviewItems
            ? completion.reviewItems === 1
              ? 'página por revisar'
              : 'páginas por revisar'
            : 'sin pendientes'}
        </dd>
      </div>
    </dl>

    {#if tabs.length > 1}
      <div class="tabs" role="tablist" aria-label="Secciones del informe" tabindex="-1" onkeydown={tecladoDePestanas}>
        {#each tabs as item (item.id)}
          <button
            id={`informe-tab-${item.id}`}
            role="tab"
            aria-selected={tab === item.id}
            aria-controls="informe-panel"
            tabindex={tab === item.id ? 0 : -1}
            class:current={tab === item.id}
            onclick={() => (tab = item.id)}
          >
            {item.label}
            {#if item.count}<span class="count tabular">{item.count}</span>{/if}
          </button>
        {/each}
      </div>
    {/if}

    <div
      class="body"
      id="informe-panel"
      role={tabs.length > 1 ? 'tabpanel' : undefined}
      aria-labelledby={tabs.length > 1 ? `informe-tab-${tab}` : undefined}
    >
      {#if tab === 'resumen'}
        {#if completion.entregas.length}
          <section>
            <h3>Entrega</h3>
            <ul class="entregas">
              {#each completion.entregas as entrega (entrega.origen + entrega.destino)}
                <li>
                  <b class="entrega-nombre">Carpeta {entrega.nombre}</b>
                  <dl>
                    <div><dt>Origen</dt><dd title={entrega.origen}>{entrega.origen}</dd></div>
                    <div><dt>Destino</dt><dd title={entrega.destino}>{entrega.destino}</dd></div>
                    {#if entrega.inventario}
                      <div><dt>Inventario</dt><dd>{entrega.inventario}</dd></div>
                    {:else if entrega.archivos}
                      <div><dt>Archivos</dt><dd>{entrega.archivos} entregados</dd></div>
                    {/if}
                  </dl>
                  {#if entrega.inventarioDe}
                    <button
                      class="btn btn-tonal"
                      onclick={() =>
                        bajarInventario(entrega.inventarioDe!, entrega.inventario ?? 'inventario.xlsx')}
                      disabled={bajando === entrega.inventarioDe}
                    >
                      <Icono nombre="descargar" />
                      {bajando === entrega.inventarioDe
                        ? 'Descargando…'
                        : 'Descargar inventario general (Excel)'}
                    </button>
                  {/if}
                </li>
              {/each}
            </ul>
            {#if falloDeDescarga}<p class="inline-error" role="alert">{falloDeDescarga}</p>{/if}
          </section>
        {/if}

        {#if completion.archivos.length}
          <section>
            <h3>PDF generados ({completion.archivos.length})</h3>
            <ul class="archivos">
              {#each completion.archivos as archivo (archivo.jobId + archivo.ruta)}
                <li>
                  <span class="archivo" title={archivo.ruta}>{archivo.ruta.split('/').pop()}</span>
                  <a
                    class="btn btn-icon"
                    href={downloadUrl(archivo.jobId, archivo.ruta)}
                    download
                    aria-label={`Descargar ${archivo.ruta.split('/').pop()}`}
                    title="Descargar (PDF)"
                  >
                    <Icono nombre="descargar" />
                  </a>
                </li>
              {/each}
            </ul>
          </section>
        {/if}

        {#if failed.length}
          <section class="trouble">
            <h3>No se pudieron procesar</h3>
            <ul class="errors">
              {#each failed as item (item.jobId)}
                <li><b>{item.filename}</b><span>{item.error ?? 'error desconocido'}</span></li>
              {/each}
            </ul>
          </section>
        {/if}

        {#if counted}
          <!-- Part-to-whole across the cascade: a stacked bar, each segment
               labelled, with a 2px surface gap rather than a border. -->
          <section>
            <h3>Cómo se leyó cada página</h3>
            <div class="stack" role="img" aria-label={`Cómo se leyeron las páginas: ${repartoHablado}`}>
              {#each rungs as entry (entry.rung.key)}
                <span
                  class="segment"
                  style:width={`${(100 * entry.count) / counted}%`}
                  style:background={entry.rung.color}
                  title={`${entry.rung.label}: ${entry.count}`}
                ></span>
              {/each}
            </div>
            <ul class="legend">
              {#each rungs as entry (entry.rung.key)}
                <li>
                  <span class="swatch" style:background={entry.rung.color}></span>
                  <span>{entry.rung.label}</span>
                  <b class="tabular">{entry.count}</b>
                  <span class="pct tabular">{((100 * entry.count) / counted).toFixed(0)} %</span>
                </li>
              {/each}
            </ul>
            {#if incidencias.length}
              <p class="footnote">{incidencias.join(' · ')}</p>
            {/if}

            <!-- Lo que se dejó de pagar. Va aparte y con su propio énfasis porque
                 no es una estadística más: es la respuesta a "¿por qué esta caja
                 costó la mitad que la anterior?", y sin ella el ahorro existe
                 pero nadie lo ve. -->
            {#if completion.unread > 0}
              <p class="footnote ahorro">
                <b>{completion.unread}</b> cara{completion.unread === 1 ? '' : 's'} no hizo
                falta leerla{completion.unread === 1 ? '' : 's'}: pertenecía{completion.unread ===
                1
                  ? ''
                  : 'n'} a la hoja anterior, así que no nombran ningún archivo ni abren fila del
                inventario.
              </p>
            {/if}
          </section>
        {/if}

        {#if !completion.entregas.length && !completion.archivos.length && !failed.length && !counted}
          <p class="footnote">Todo terminó sin errores y no queda nada pendiente.</p>
        {/if}
      {:else if tab === 'unidades'}
        <!-- El desglose de una tanda: qué fue cada cosa que corrió. -->
        <ul class="units">
          {#each completion.parts ?? [] as part (part.id)}
            <li>
              <span class="tag">{KIND[part.kind]}</span>
              <span class="name" title={part.title}>{part.title}</span>
              <span class="num tabular">{unidadDe(part.resolutions, part.unidad)}</span>
              <span class="num tabular">{part.pages} pág.</span>
              <span class="num tabular">{formatDuration(part.elapsedSeconds)}</span>
              {#if part.failedDocuments}
                <span class="num bad tabular">{part.failedDocuments} error</span>
              {/if}
            </li>
          {/each}
        </ul>
      {:else if tab === 'documentos'}
        <table>
          <caption class="sr-only">Documentos procesados, uno por fila</caption>
          <thead>
            <tr>
              <th scope="col">Archivo</th>
              <th scope="col" class="num">Páginas</th>
              <th scope="col" class="num">{Unidades}</th>
              <th scope="col" class="num">Tamaño</th>
              <th scope="col" class="num">Revisión</th>
            </tr>
          </thead>
          <tbody>
            {#each completion.items as item (item.jobId)}
              <tr class:failed={item.state === 'failed'}>
                <td title={item.error ?? item.filename}>
                  {item.filename}{#if item.state === 'failed'}<span class="sr-only"> (falló: {item.error ?? 'error desconocido'})</span>{/if}
                </td>
                <td class="num tabular">{item.pages || '—'}</td>
                <td class="num tabular">{item.resolutions || '—'}</td>
                <td class="num tabular">{formatBytes(item.bytes)}</td>
                <td class="num tabular">{item.review || '—'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {:else if tab === 'resoluciones'}
        <input
          class="input input-sm"
          type="search"
          bind:value={filter}
          placeholder="Filtrar por número, título o documento"
          aria-label="Filtrar por número, título o documento"
          spellcheck="false"
        />
        <ul class="codes">
          {#each shown as entry (entry.document + entry.code)}
            <li>
              <span class="code">{entry.code}</span>
              <span class="title">{entry.title ?? 'sin título'}</span>
              <span class="from" title={entry.document}>{entry.document}</span>
              <span class="size tabular">{entry.size} pág.</span>
            </li>
          {/each}
          {#if !shown.length}
            <li class="empty-state">Nada coincide con la búsqueda.</li>
          {/if}
        </ul>
      {/if}
    </div>

    <footer>
      <!--
        Se dice qué hace el botón antes de pulsarlo. Una pantalla que se vacía
        sola al cerrar un aviso se lee como una pérdida, aunque no lo sea.
      -->
      <span class="note">
        Al cerrar se limpia la pantalla. El trabajo queda en el archivo y este informe
        se vuelve a abrir desde ahí{#if !clean}, y lo pendiente sigue en Revisión{/if}.
      </span>
      <a href="/archivo" onclick={() => void dismiss()}>Ver en el archivo</a>
      {#if completion.reviewItems}
        <a class="warn" href="/revision" onclick={() => void dismiss()}>
          Revisar {completion.reviewItems} {completion.reviewItems === 1 ? 'página' : 'páginas'}
        </a>
      {/if}
      <button class="btn cerrar" onclick={() => void dismiss()}>Cerrar</button>
    </footer>
  </div>
</div>

<style>
  .scrim {
    position: fixed;
    inset: 0;
    z-index: 80;
    display: grid;
    place-items: center;
    background: var(--scrim);
    padding: 1.5rem;
    backdrop-filter: blur(3px);
    animation: fade 0.16s ease-out;
  }

  .sheet {
    display: flex;
    width: min(72rem, 100%);
    max-height: min(88dvh, 56rem);
    flex-direction: column;
    overflow: hidden;
    border: 1px solid var(--hairline);
    border-radius: var(--radius-xl);
    background: var(--surface-2);
    box-shadow: var(--shadow-lg);
    animation: rise 0.18s ease-out;
  }

  header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem 1rem;
    padding: 1rem 1.25rem 0.75rem;
  }
  .who {
    display: flex;
    min-width: 0;
    flex: 1;
    flex-direction: column;
    gap: 0.25rem;
  }
  .meta {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }
  .badge {
    align-self: flex-start;
  }
  header h2 {
    overflow: hidden;
    margin: 0;
    font-size: var(--text-xl);
    font-weight: 650;
    letter-spacing: -0.015em;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  header time {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .sheet:focus,
  header h2:focus {
    outline: none;
  }
  .sheet :focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 2px;
  }

  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(8rem, 1fr));
    gap: 0.9rem 1.25rem;
    margin: 0;
    padding: 0.35rem 1.25rem 1rem;
  }
  /* Las cifras con la misma forma que StatTile: rótulo en versalitas, valor
     grande y una nota debajo, con un filete a la izquierda en vez de una caja. */
  .tiles div {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    border-left: 2px solid var(--rule);
    padding-left: 0.75rem;
  }
  .tiles dt {
    font-size: var(--text-2xs);
    font-weight: 600;
    letter-spacing: var(--tracking-caps);
    text-transform: uppercase;
    color: var(--muted);
  }
  .tiles dd {
    margin: 0;
    font-size: var(--text-xl);
    font-weight: 550;
    line-height: 1.15;
    letter-spacing: -0.02em;
  }
  .tiles dd.warn {
    color: var(--warning-ink);
  }
  .tiles .note {
    font-size: var(--text-xs);
    font-weight: 400;
    letter-spacing: 0;
    color: var(--ink-2);
  }

  .tabs {
    display: flex;
    gap: 0.15rem;
    border-bottom: 1px solid var(--hairline);
    padding: 0 1rem;
  }
  .tabs button {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    border: 0;
    border-bottom: 2px solid transparent;
    background: none;
    padding: 0.5rem 0.7rem;
    font: inherit;
    font-size: var(--text-sm);
    color: var(--muted);
    cursor: pointer;
    transition:
      color 0.15s,
      border-color 0.15s;
  }
  .tabs button:hover {
    color: var(--ink-2);
  }
  .tabs button.current {
    border-bottom-color: var(--accent);
    color: var(--ink);
  }
  .count {
    border-radius: var(--radius-pill);
    background: var(--plane);
    padding: 0.02rem 0.4rem;
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--muted);
  }

  .body {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 1.5rem;
    overflow-y: auto;
    padding: 1.25rem;
  }

  .entregas {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .entregas li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 1rem;
    border-left: 2px solid var(--accent);
    padding-left: 0.75rem;
  }
  .entrega-nombre {
    flex-basis: 100%;
    font-size: var(--text-md);
  }
  .entregas dl {
    display: grid;
    flex: 1 1 22rem;
    grid-template-columns: auto minmax(0, 1fr);
    gap: 0.15rem 0.75rem;
    margin: 0;
  }
  .entregas dl div {
    display: contents;
  }
  .entregas dt {
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .entregas dd {
    overflow: hidden;
    margin: 0;
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .archivos {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 22rem), 1fr));
    gap: 2px 1rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .archivos li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    border-bottom: 1px solid var(--rule);
    padding: 0.15rem 0;
  }
  .archivo {
    overflow: hidden;
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* El botón de icono común, un punto más bajo para no ensanchar la fila. */
  .archivos .btn {
    flex-shrink: 0;
    width: 1.75rem;
    height: 1.75rem;
  }

  section h3 {
    margin: 0 0 0.55rem;
    font-size: var(--text-2xs);
    font-weight: 600;
    letter-spacing: var(--tracking-caps);
    text-transform: uppercase;
    color: var(--muted);
  }
  .trouble h3 {
    color: var(--critical);
  }
  .errors {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .errors li {
    display: flex;
    flex-wrap: wrap;
    gap: 0.15rem 0.6rem;
    border-left: 2px solid var(--critical);
    padding-left: 0.7rem;
    font-size: var(--text-sm);
  }
  .errors span {
    font-size: var(--text-xs);
    color: var(--muted);
  }

  .stack {
    display: flex;
    height: 10px;
    overflow: hidden;
    border-radius: var(--radius-sm);
    /* A surface gap between segments, never a border around them. */
    gap: 2px;
  }
  .segment {
    height: 100%;
  }

  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem 1.25rem;
    margin: 0.6rem 0 0;
    padding: 0;
    list-style: none;
  }
  .legend li {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: var(--text-sm);
    color: var(--ink-2);
  }
  .swatch {
    width: 9px;
    height: 9px;
    border-radius: 2px;
  }
  .legend b {
    font-family: var(--font-mono);
    font-weight: 600;
    color: var(--ink);
  }
  .pct {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--muted);
  }

  .ahorro {
    color: var(--ink-2);
  }

  .ahorro b {
    color: var(--ink);
  }

  .footnote {
    margin: 0.6rem 0 0;
    font-size: var(--text-xs);
    color: var(--muted);
  }

  .units {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .units li {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    border-radius: var(--radius-sm);
    padding: 0.4rem 0.55rem;
    font-size: var(--text-sm);
  }
  .units li:nth-child(odd) {
    background: var(--plane);
  }
  .tag {
    flex-shrink: 0;
    width: 9.5rem;
    font-size: var(--text-2xs);
    font-weight: 600;
    letter-spacing: var(--tracking-caps);
    text-transform: uppercase;
    color: var(--muted);
  }
  .units .name {
    overflow: hidden;
    flex: 1;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .bad {
    color: var(--critical);
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-sm);
  }
  thead th {
    padding: 0 0.5rem 0.4rem 0;
    font-size: var(--text-2xs);
    font-weight: 600;
    letter-spacing: var(--tracking-caps);
    text-align: left;
    text-transform: uppercase;
    color: var(--muted);
  }
  tbody tr {
    border-top: 1px solid var(--hairline);
  }
  tbody td {
    overflow: hidden;
    max-width: 22rem;
    padding: 0.4rem 0.5rem 0.4rem 0;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .num {
    flex-shrink: 0;
    text-align: right;
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--ink-2);
  }
  thead th.num {
    font-family: inherit;
    font-size: var(--text-2xs);
    text-align: right;
    color: var(--muted);
  }
  tr.failed td {
    color: var(--critical);
  }

  .codes {
    display: flex;
    flex-direction: column;
    gap: 1px;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .codes li {
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
    border-radius: var(--radius-sm);
    padding: 0.22rem 0.4rem;
    font-size: var(--text-sm);
  }
  .codes li:nth-child(odd) {
    background: var(--plane);
  }
  .code {
    flex-shrink: 0;
    width: 6.5rem;
    font-family: var(--font-mono);
    font-size: var(--text-xs);
  }
  .codes .title {
    overflow: hidden;
    flex: 1;
    color: var(--ink-2);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .from {
    overflow: hidden;
    max-width: 14rem;
    flex-shrink: 0;
    font-size: var(--text-xs);
    color: var(--muted);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .size {
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--muted);
  }
  /* El vacío de la búsqueda va en la caja punteada común; la lista pinta las
     filas impares y ésta no debe heredar ese fondo. */
  .codes .empty-state {
    margin-top: 0.5rem;
    background: none;
  }

  /* La explicación empuja los botones a la derecha y se lee antes que ellos. */
  .note {
    flex: 1;
    color: var(--muted);
    font-size: var(--text-sm);
    line-height: 1.35;
  }

  footer {
    display: flex;
    align-items: center;
    gap: 1rem;
    border-top: 1px solid var(--hairline);
    padding: 0.85rem 1.25rem;
  }
  footer a {
    font-size: var(--text-sm);
    color: var(--accent);
    text-decoration: none;
  }
  footer a:hover {
    text-decoration: underline;
  }
  footer a.warn {
    color: var(--warning-ink);
  }
  footer .cerrar {
    margin-left: auto;
  }

  @keyframes fade {
    from {
      opacity: 0;
    }
  }
  @keyframes rise {
    from {
      opacity: 0;
      transform: translateY(8px);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .scrim,
    .sheet {
      animation: none;
    }
  }
</style>
