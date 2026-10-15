<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import {
    descargarPlanilla,
    documentFuidUrl,
    documentInventoryUrl,
    downloadUrl,
    fetchDocument,
    renameJob,
    type ArchivedDocument
  } from '$lib/api';
  import { formatBytes } from '$lib/format';
  import EncabezadoDePagina from '$lib/components/EncabezadoDePagina.svelte';
  import FuidViewer from '$lib/components/FuidViewer.svelte';
  import Icono from '$lib/components/Icono.svelte';
  import JobCard from '$lib/components/JobCard.svelte';
  import ValidationPanel from '$lib/components/ValidationPanel.svelte';
  import { jobStore } from '$lib/jobs.svelte';
  import { padreDe, vista } from '$lib/navegacion.svelte';
  import { session } from '$lib/session.svelte';
  import type { InventoryReport } from '$lib/types';

  const job = $derived(jobStore.get(page.params.id ?? ''));

  // El nombre que enseñan las migas: el del trabajo si sigue en pantalla, el
  // del inventario si ya se archivó.
  $effect(() => {
    vista.titulo = job?.filename ?? archived?.source_document ?? null;
    return () => (vista.titulo = null);
  });

  /**
   * El mismo documento, pero recordado por el inventario.
   *
   * La ficha se dibujaba sólo desde el trabajo en memoria, así que en cuanto el
   * área de trabajo se limpiaba el documento quedaba en un callejón sin salida:
   * decía "archivado" y no llevaba a ninguna parte. El inventario sí lo
   * recuerda, y esto es lo que se enseña cuando ya no está en pantalla.
   */
  let archived = $state<ArchivedDocument | null>(null);
  let loadingArchived = $state(false);
  let archivedError = $state<string | null>(null);

  $effect(() => {
    const id = page.params.id ?? '';
    if (!id || job) return;
    loadingArchived = true;
    archivedError = null;
    fetchDocument(id)
      .then((found) => (archived = found))
      .catch((problem) => (archivedError = (problem as Error).message))
      .finally(() => (loadingArchived = false));
  });

  /**
   * El informe de un trabajo de inventario, que tiene otra forma que el de una
   * división: no trae grupos ni salidas, trae el tipo reconocido y las filas.
   */
  const inventory = $derived.by(() => {
    // Por la forma del informe y no por la acción: "dividir e inventariar"
    // produce los dos, y un libro de folios dividido también trae el tipo
    // reconocido y sus registros.
    const report = job?.report as unknown as InventoryReport | null;
    return report?.document_type ? report : null;
  });

  /** El FUID existe cuando la acción lo incluía y se pudo escribir. */
  const fuid = $derived(job?.report?.fuid ?? inventory?.fuid ?? null);
  const fuidError = $derived(job?.report?.fuid_error ?? inventory?.fuid_error ?? null);
  /** Por qué no bajó el FUID, si al pulsar el botón falló la descarga. */
  let errorDeDescarga = $state<string | null>(null);

  /**
   * Cómo se llama en pantalla lo que el sistema reconoció. Se muestra en las
   * dos acciones: al dividir importa igual, porque el tipo es lo que decide con
   * qué regla se parte y con qué columnas se inventaría.
   */
  const TIPOS: Record<string, string> = {
    resolucion: 'Resoluciones',
    diploma: 'Registro de diplomas',
    matricula: 'Registros de matrícula',
    desconocido: 'Sin identificar'
  };

  const recognised = $derived.by(() => {
    if (inventory) {
      return { label: inventory.document_type_label, confidence: inventory.type_confidence };
    }
    const stats = job?.report?.stats;
    if (!stats?.document_type) return null;
    return { label: TIPOS[stats.document_type] ?? stats.document_type, confidence: stats.type_confidence ?? 0 };
  });
  /**
   * El título de la ficha. La ficha no tenía encabezado: el nombre del
   * documento aparecía, según el caso, dentro de una tarjeta o en ninguna
   * parte, y la página no se parecía a las demás secciones.
   */
  const titulo = $derived(job?.filename ?? archived?.source_document ?? 'Documento');

  let confirmingDelete = $state(false);
  let renaming = $state(false);
  let draft = $state('');
  let error = $state<string | null>(null);

  /**
   * Un documento no se renombra a la nada.
   *
   * Vale para todos los perfiles, no sólo para el que exige el formulario
   * completo: un nombre en blanco no es una elección, es un campo que se
   * quedó sin llenar, y el archivo quedaría con un documento que no se puede
   * nombrar al buscarlo.
   */
  const puedeRenombrar = $derived(draft.trim().length > 0);

  async function rename() {
    const name = draft.trim();
    if (!name) return;
    try {
      await renameJob(page.params.id ?? '', name);
      renaming = false;
    } catch (problem) {
      error = (problem as Error).message;
    }
  }

  async function remove(purge: boolean) {
    confirmingDelete = false;
    try {
      await jobStore.remove(page.params.id ?? '', purge);
      // Borrado el documento, se sube al nivel del que colgaba.
      await goto(padreDe(page.url) ?? '/archivo');
    } catch (problem) {
      error = (problem as Error).message;
    }
  }
</script>

<!-- «Volver» y dónde se está los pone el layout, con las migas. Aquí va el
     nombre del documento y lo que se puede hacer con él entero. -->
<EncabezadoDePagina {titulo}>
  {#snippet acciones()}
    {#if job}
      {#if renaming}
        <input class="input input-sm min-w-64" bind:value={draft} aria-label="Nuevo nombre" />
        <button class="btn btn-primary btn-sm" onclick={rename} disabled={!puedeRenombrar}>
          Guardar
        </button>
        <button class="btn btn-ghost btn-sm" onclick={() => (renaming = false)}>Cancelar</button>
      {:else if confirmingDelete}
        <button class="btn btn-sm" onclick={() => remove(false)}>Quitar de la pantalla</button>
        <button class="btn btn-danger btn-sm" onclick={() => remove(true)}>
          Eliminar también los PDF
        </button>
        <button class="btn btn-ghost btn-sm" onclick={() => (confirmingDelete = false)}>
          Cancelar
        </button>
      {:else}
        <button
          class="btn btn-sm"
          onclick={() => {
            draft = job?.filename ?? '';
            renaming = true;
          }}
        >
          <Icono nombre="editar" />
          Renombrar
        </button>
        <button class="btn btn-danger btn-sm" onclick={() => (confirmingDelete = true)}>
          <Icono nombre="borrar" />
          Eliminar
        </button>
      {/if}
    {:else if archived}
      <span class="pill">Archivado</span>
    {/if}
  {/snippet}
</EncabezadoDePagina>

{#if error}
  <p class="inline-error mb-4">{error}</p>
{/if}

{#if job}
  {#if job.state === 'done' && (inventory || fuid || fuidError)}
    <!-- Un documento inventariado no deja PDF: lo único que produce es su FUID,
         y sin un sitio desde donde bajarlo la función no está terminada. -->
    <section class="panel seccion flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="titulo-seccion">Inventario del documento</h2>
        <p class="texto">
          {#if inventory}
            Reconocido como <b>{inventory.document_type_label}</b>. Se registraron
            <b class="tabular">{inventory.records}</b>
            {inventory.records === 1 ? 'unidad documental' : 'unidades documentales'}.
            {#if job.task === 'inventory'}
              El PDF de origen quedó entero.
            {/if}
          {:else}
            El inventario del documento, en el formato oficial de la Universidad.
          {/if}
        </p>
      </div>
      {#if fuid}
        <!-- Verlo lo pueden los tres perfiles; bajarlo, sólo el que el servicio
             deje. El botón de descarga vive dentro del visor, que es donde el
             servicio ya contestó quién puede. -->
        <div class="flex shrink-0 flex-wrap items-center gap-2">
          <FuidViewer jobId={job.id} nombre={job.filename} />
          {#if session.descargaPlanillas}
            <a
              class="btn btn-tonal"
              href={documentFuidUrl(job.id)}
              onclick={(evento) => {
                // Por `fetch`, que lleva la cédula: siguiendo el enlace el
                // servicio no sabe quién lo pide y contesta 401.
                evento.preventDefault();
                descargarPlanilla(documentFuidUrl(job.id), `${job.filename}__FUID.xlsx`).catch(
                  (problema) => (errorDeDescarga = (problema as Error).message)
                );
              }}
            >
              <Icono nombre="descargar" />
              Descargar FUID (Excel)
            </a>
          {/if}
          {#if errorDeDescarga}
            <span class="inline-error m-0">{errorDeDescarga}</span>
          {/if}
        </div>
      {:else if fuidError}
        <span class="pill pill-bad">No se pudo escribir el FUID</span>
      {/if}
    </section>
  {/if}

  {#if !inventory && job.state === 'done' && recognised}
    <section class="panel seccion">
      <h2 class="titulo-seccion">Tipo de documento</h2>
      <p class="texto">
        El sistema lo reconoció como <b>{recognised.label}</b> por lo que está impreso en sus
        páginas —no por el nombre del archivo—, con una confianza de
        <span class="tabular">{(recognised.confidence * 100).toFixed(1)} %</span>.
      </p>
    </section>
  {/if}

  {#if job.state === 'done' && job.report?.validation}
    <div class="seccion">
      <ValidationPanel validation={job.report.validation} issues={job.report.issues} />
    </div>
  {/if}

  <JobCard {job} />
{:else if loadingArchived}
  <p class="empty-state">Buscándolo en el inventario…</p>
{:else if archived}
  <!--
    La ficha de un documento que ya salió del área de trabajo. Enseña lo que el
    inventario guarda, que es lo que se produjo, y dice explícitamente lo que no
    guarda: el reparto por peldaños y la cinta de páginas viven en el informe del
    proceso y no sobreviven a la limpieza. Callarlo sería enseñar una ficha
    incompleta con aspecto de completa.
  -->
  <section class="panel seccion">
    <!-- Las cifras con el aspecto de las del resto de la aplicación: rótulo en
         versalitas y valor grande, sin cajas propias. «PDF generados» y no
         «Resoluciones»: la ficha es la misma para cualquier tipo de documento. -->
    <dl class="cifras">
      <div>
        <dt class="caps">PDF generados</dt>
        <dd class="valor tabular">{archived.resolutions}</dd>
      </div>
      <div>
        <dt class="caps">Páginas</dt>
        <dd class="valor tabular">{archived.source_pages || archived.pages}</dd>
      </div>
      <div>
        <dt class="caps">Tamaño</dt>
        <dd class="valor tabular">
          {archived.bytes ? formatBytes(archived.bytes) : '—'}
        </dd>
      </div>
      <div>
        <dt class="caps">Requiere revisión</dt>
        <dd class="valor tabular" class:aviso={archived.review}>
          {archived.review}
        </dd>
      </div>
      {#if archived.operator}
        <div>
          <dt class="caps">Operador</dt>
          <dd class="valor">{archived.operator}</dd>
        </div>
      {/if}
    </dl>

    <p class="texto mt-4">
      Esta ficha se dibuja desde el inventario. El reparto por peldaños de lectura y la
      cinta de páginas sólo existen mientras el documento está en el área de trabajo.
    </p>
  </section>

  {#if archived.rows.length}
    <section class="panel">
      <!-- El listado y su descarga en la misma línea. La planilla se escribe
           sola al terminar el documento, junto a los PDF que describe, así que
           aquí no hay nada que generar: sólo bajarla. -->
      <header class="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 class="titulo-seccion">
          Lo que produjo <span class="tabular">({archived.rows.length})</span>
        </h2>
        <a class="btn btn-tonal" href={documentInventoryUrl(archived.job_id)} download>
          <Icono nombre="descargar" />
          Descargar inventario (Excel)
        </a>
      </header>
      <div class="overflow-x-auto">
        <table class="tabla">
          <thead>
            <tr>
              <th>N°</th>
              <th>Páginas</th>
              <th>Tipo documental</th>
              <th>Fecha</th>
              <th>Archivo generado</th>
              <th><span class="sr-only">Descargar</span></th>
            </tr>
          </thead>
          <tbody>
            {#each archived.rows as row (row.file_name)}
              <tr>
                <td class="mono">{row.code}</td>
                <!-- Las páginas delante del tipo: es el orden en que se lee
                     esta tabla, "de la 1 a la 8, un derecho de petición", y es
                     también el orden en que están en la caja de origen. -->
                <td class="tabular apagado nowrap">{row.pages}</td>
                <!-- El tipo y, debajo, lo que declara el documento: su asunto
                     o su referencia. Un archivo por mes junta varias cartas y
                     «DOCUMENTO» solo no dice cuáles; el título sí. La
                     procedencia («páginas 1-2») no se repite: ya está en la
                     columna de al lado. -->
                <td>
                  {row.type ?? '—'}
                  {#if row.title && !/^p[aá]ginas? /i.test(row.title)}
                    <span class="subtitulo">{row.title}</span>
                  {/if}
                </td>
                <!-- La fecha más reciente que lleva escrita el documento. Se
                     lee de todas sus páginas, no sólo de la primera: un acta
                     puede llevar la de la visita arriba y la del acuse detrás. -->
                <td class="tabular apagado nowrap">{row.fecha ?? '—'}</td>
                <!-- El nombre, escrito y no sólo enlazado. Esta columna llevaba
                     únicamente el icono de descarga, así que la tabla no decía
                     cómo se llama en el disco ninguno de los archivos que
                     acababa de producir: para saberlo había que bajarlos. -->
                <td class="mono archivo">{row.file_name.split('/').pop()}</td>
                <td class="acciones">
                  <a
                    class="btn btn-icon"
                    href={downloadUrl(row.job_id, row.file_name)}
                    download
                    title="Descargar PDF"
                    aria-label={`Descargar ${row.file_name}`}
                  >
                    <Icono nombre="descargar" />
                  </a>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </section>
  {/if}
{:else}
  <div class="empty-state">
    <strong>Este documento no está en el inventario</strong>
    {archivedError ?? 'No se encontró ni en el área de trabajo ni en el registro.'}
    Puede haberse eliminado. Lo que sí quedó está en el
    <a class="enlace" href="/archivo">archivo</a>.
  </div>
{/if}

<style>
  /* Las secciones de la ficha se apilan con el mismo aire entre ellas. */
  .seccion {
    margin-bottom: var(--space-4);
  }

  .titulo-seccion {
    margin: 0;
    font-size: var(--text-md);
    font-weight: 600;
    color: var(--ink);
  }
  .texto {
    margin: 0.25rem 0 0;
    font-size: var(--text-md);
    line-height: 1.5;
    color: var(--ink-2);
  }

  /* Las cifras del documento archivado, con la medida de StatTile: rótulo en
     versalitas, valor grande. */
  .cifras {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-4) var(--space-8);
    margin: 0;
  }
  .cifras dt {
    margin-bottom: 0.15rem;
  }
  .valor {
    margin: 0;
    font-size: var(--text-xl);
    font-weight: 550;
    line-height: 1.15;
    letter-spacing: -0.02em;
    color: var(--ink);
  }
  .valor.aviso {
    color: var(--warning-ink);
  }

  /* La tabla del documento archivado, con la cabecera y la letra de las
     demás tablas de la aplicación. */
  .tabla {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-sm);
  }
  .tabla th {
    padding: 0 0.75rem 0.5rem 0;
    font-size: var(--text-2xs);
    font-weight: 600;
    letter-spacing: var(--tracking-caps);
    text-align: left;
    text-transform: uppercase;
    color: var(--muted);
  }
  .tabla tbody tr {
    border-top: 1px solid var(--hairline);
  }
  .tabla td {
    padding: 0.4rem 0.75rem 0.4rem 0;
    vertical-align: baseline;
    color: var(--ink);
  }
  .mono {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    font-variant-numeric: tabular-nums;
  }
  .tabla td.apagado {
    color: var(--muted);
  }
  .nowrap {
    white-space: nowrap;
  }
  .subtitulo {
    display: block;
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .tabla td.archivo {
    word-break: break-all;
    color: var(--ink-2);
  }
  .tabla td.acciones {
    padding-right: 0;
    text-align: right;
  }

  .enlace {
    color: var(--accent);
    text-decoration: none;
  }
  .enlace:hover {
    text-decoration: underline;
  }
</style>
