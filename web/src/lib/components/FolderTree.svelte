<script lang="ts">
  import {
    descargarPlanilla,
    documentFuidStatus,
    documentFuidUrl,
    documentInventoryUrl,
    downloadUrl,
    makeDocumentFuid
  } from '$lib/api';
  import Icono from '$lib/components/Icono.svelte';
  import { pageRange } from '$lib/format';
  import { jobStore } from '$lib/jobs.svelte';
  import { session } from '$lib/session.svelte';
  import type { FolderRun, Job } from '$lib/types';

  /**
   * Lo que salió de una carpeta, en la forma en que está guardado: un árbol.
   *
   * Una carpeta contiene PDF y cada PDF contiene las unidades documentales en
   * que se partió. Enseñarlo como tres listas planas -- lo que se está
   * consumiendo, lo que espera turno, lo que se entregó -- obliga a quien mira a
   * reconstruir de memoria qué resolución salió de qué archivo, que es
   * justamente lo que la pantalla puede responder sola.
   *
   * Nada de lo que se dibuja aquí se calcula ni se estima: cada nivel sale del
   * informe que produjo su trabajo. Un documento que todavía no terminó no
   * enseña un número provisional, enseña que no ha terminado.
   */
  interface Props {
    run: FolderRun;
  }

  let { run }: Props = $props();

  /** Qué ramas están abiertas. Se abre a mano; nada se despliega solo. */
  let abiertos = $state<Set<string>>(new Set());

  /** El estado del inventario de cada documento, mientras se levanta. */
  let inventarios = $state<
    Record<string, { trabajando: boolean; error: string | null; aviso?: string | null }>
  >({});

  /**
   * Los documentos de la corrida, en el orden en que los tomó.
   *
   * Sólo los que siguen en el registro de la pantalla. Uno que se limpió no se
   * dibuja con datos inventados: se cuenta aparte, diciendo cuántos son.
   */
  const documentos = $derived(
    (run.job_ids ?? [])
      .map((id) => jobStore.get(id))
      .filter((job): job is Job => job !== undefined)
  );

  // Del total de la corrida: `job_ids` trae sólo los últimos.
  const olvidados = $derived((run.job_count ?? (run.job_ids ?? []).length) - documentos.length);

  function alternar(clave: string) {
    const siguiente = new Set(abiertos);
    if (siguiente.has(clave)) siguiente.delete(clave);
    else siguiente.add(clave);
    abiertos = siguiente;
  }

  /** Las unidades documentales de un PDF, tal como quedaron escritas. */
  function unidadesDe(job: Job) {
    return job.report?.inventory?.items ?? [];
  }

  /**
   * Bajar el inventario del documento.
   *
   * Llama a la misma acción que «Solo inventariar» de la pantalla de carga --
   * el mismo worker, y la plantilla la elige el tipo de documento que se
   * reconozca al leerlo -- y en cuanto la planilla está escrita, la descarga.
   * Si ya estaba escrita no se vuelve a leer nada: se descarga y ya.
   */
  async function inventariar(job: Job) {
    inventarios = { ...inventarios, [job.id]: { trabajando: true, error: null } };
    try {
      // Un acta de consejo ya dejó su Excel al procesarse: se baja y nada más.
      // Volver a leerla -- lo que hacía este botón cuando no encontraba la
      // planilla -- la leía sin IA y pisaba su Excel con uno sin folios ni
      // resumen.
      if (job.report?.inventario_actas?.length) {
        await descargarPlanilla(documentInventoryUrl(job.id));
        inventarios = { ...inventarios, [job.id]: { trabajando: false, error: null } };
        return;
      }
      // La planilla del documento se escribe sola al procesarlo, así que lo
      // primero es probar si ya está: bajarla es instantáneo y no vuelve a
      // leer el PDF. Sólo si no está se levanta el FUID, que sí lo lee entero.
      if (await bajarLaPlanilla(job)) {
        inventarios = { ...inventarios, [job.id]: { trabajando: false, error: null } };
        return;
      }

      let estado = await makeDocumentFuid(job.id);
      // Leer un libro de cuatrocientos folios son minutos. Se pregunta cada dos
      // segundos en vez de dejar la petición abierta todo ese rato.
      //
      // Y se para cuando el servicio deja de estar trabajando. Antes la
      // condición era sólo "ni listo ni con error", y un documento que
      // terminaba sin producir planilla -- un escaneo sin capa de texto -- no
      // cumplía ninguna de las dos: el botón se quedaba diciendo "levantando…"
      // indefinidamente y sin nada más que decir.
      while (!estado.ready && !estado.error && estado.working !== false) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        estado = await documentFuidStatus(job.id);
      }
      if (estado.error) throw new Error(estado.error);
      if (!estado.ready) {
        throw new Error('El documento se leyó y no produjo inventario');
      }
      // Bajarla sólo quien puede. A los demás se les dice dónde mirarla, en
      // vez de dispararles una descarga que el servicio va a rechazar: un 403
      // sin explicación se lee como una avería del programa.
      // Por `fetch`, que lleva la cédula: un enlace llega sin ella y el
      // servicio contesta 401 en vez de la planilla.
      if (session.descargaPlanillas) await descargarPlanilla(documentFuidUrl(job.id));
      inventarios = {
        ...inventarios,
        [job.id]: {
          trabajando: false,
          error: null,
          aviso: session.descargaPlanillas
            ? null
            : 'La planilla quedó escrita. Ábrala desde la ficha del documento.'
        }
      };
    } catch (problema) {
      inventarios = {
        ...inventarios,
        [job.id]: { trabajando: false, error: (problema as Error).message }
      };
    }
  }

  /** La planilla que el proceso ya dejó escrita, si está. */
  async function bajarLaPlanilla(job: Job): Promise<boolean> {
    // Quien no descarga planillas tampoco se lleva ésta por este atajo. No
    // es el FUID -- es el inventario que el proceso deja junto a los PDF --
    // pero es el mismo Excel saliendo por la misma puerta, y dejarlo abierto
    // haría de la restricción una que sólo aplica a veces.
    if (!session.descargaPlanillas) return false;
    // Con GET y no con HEAD: el servicio no contesta HEAD (405), y tomar eso
    // por «no hay planilla» relanzaba la lectura entera del documento.
    try {
      await descargarPlanilla(documentInventoryUrl(job.id));
      return true;
    } catch (problema) {
      if ((problema as { status?: number }).status === 404) return false;
      throw problema;
    }
  }

  const ESTADOS: Record<string, string> = {
    queued: 'En cola',
    running: 'Leyendo',
    paused: 'En pausa',
    done: 'Listo',
    failed: 'Falló',
    cancelled: 'Cancelado'
  };
</script>

<div class="arbol">
  <!-- La raíz: la carpeta, por su ruta. Es lo que el operador escribió y es
       como la reconoce, así que va entera y no recortada a su último tramo. -->
  <div class="nodo raiz">
    <span class="glifo" aria-hidden="true"><Icono nombre="carpeta" /></span>
    <span class="etiqueta" title={run.source}>{run.source}</span>
    <!-- Cuántos PDF tomó de la carpeta, sobre cuántos había. "1 de 2 PDF"
         contando sólo lo que quedaba en pantalla decía que la carpeta tenía dos
         archivos cuando tenía seis, y que había procesado uno cuando la cifra
         de arriba decía otra cosa. Lo que sigue en pantalla se cuenta aparte,
         abajo, porque es una propiedad de la pantalla y no de la carpeta. -->
    <span class="cuenta tabular">{run.processed} de {run.discovered} PDF</span>
  </div>

  {#if run.destination}
    <div class="nodo destino">
      <span class="rama" aria-hidden="true"></span>
      <span class="glifo" aria-hidden="true">↳</span>
      <span class="etiqueta" title={run.destination}>{run.destination}</span>
      <span class="cuenta tabular">{run.delivered} entregados</span>
    </div>
  {/if}

  <ul class="hijos">
    {#each documentos as job (job.id)}
      {@const unidades = unidadesDe(job)}
      {@const inventario = inventarios[job.id]}
      {@const acta = job.report?.inventario_actas?.[0]}
      <li class="pdf" data-state={job.state}>
        <div class="nodo">
          <span class="rama" aria-hidden="true"></span>
          <button
            class="pliegue"
            onclick={() => alternar(job.id)}
            disabled={unidades.length === 0}
            aria-expanded={abiertos.has(job.id)}
          >
            <span class="chevron" aria-hidden="true">
              {#if unidades.length > 0}
                <Icono nombre={abiertos.has(job.id) ? 'abajo' : 'chevron'} />
              {/if}
            </span>
            <span class="glifo" aria-hidden="true"><Icono nombre="hoja" /></span>
            <span class="etiqueta" title={job.filename}>{job.filename}</span>
          </button>

          <!-- Lo que se dice de un documento es lo que su informe dice, y sólo
               cuando lo dice: mientras corre, su estado; cuando terminó, sus
               páginas y sus unidades. -->
          {#if job.state === 'done' && job.report && acta}
            <!-- Un acta de consejo no se parte: lo que se dice de ella es su
                 acta y su fecha, que es lo que el inventario general anota. -->
            {@const actas = job.report.inventario_actas?.length ?? 1}
            <span class="cuenta" title={`${acta.acta} · ${acta.fecha}`}>
              {actas > 1 ? `Libro de ${actas} actas` : `${acta.acta} · ${acta.fecha}`}
            </span>
            <button
              class="btn btn-tonal btn-sm"
              onclick={() => inventariar(job)}
              disabled={inventario?.trabajando}
              title="Sólo esta acta. El inventario general de la carpeta, con todas, está arriba."
            >
              <Icono nombre="descargar" />
              {inventario?.trabajando
                ? 'Descargando…'
                : actas > 1
                  ? 'Descargar inventario del libro (Excel)'
                  : 'Descargar inventario del acta (Excel)'}
            </button>
          {:else if job.state === 'done' && job.report}
            <span class="cuenta tabular">
              {job.report.page_count} pág · {unidades.length}
              {unidades.length === 1 ? 'unidad' : 'unidades'}
            </span>
            <button
              class="btn btn-tonal btn-sm"
              onclick={() => inventariar(job)}
              disabled={inventario?.trabajando}
              title="Levanta el inventario con la plantilla del tipo de documento que se reconozca, y lo descarga"
            >
              <Icono nombre="descargar" />
              {inventario?.trabajando ? 'Levantando…' : 'Descargar inventario (Excel)'}
            </button>
          {:else}
            <span
              class="pill estado"
              class:pill-bad={job.state === 'failed'}
              class:pill-warn={job.state === 'paused' || job.state === 'cancelled'}
              >{ESTADOS[job.state] ?? job.state}</span
            >
          {/if}
        </div>

        {#if inventario?.error}
          <p class="inline-error">{inventario.error}</p>
        {:else if inventario?.aviso}
          <p class="aviso">{inventario.aviso}</p>
        {/if}

        {#if abiertos.has(job.id)}
          <ul class="hijos">
            {#each unidades as unidad (unidad.file_name)}
              <li class="unidad">
                <div class="nodo">
                  <span class="rama" aria-hidden="true"></span>
                  <span class="glifo" aria-hidden="true"><Icono nombre="documento" /></span>
                  <a
                    class="etiqueta enlace"
                    href={downloadUrl(job.id, unidad.file_name)}
                    download
                    title={unidad.title ?? unidad.file_name}
                  >
                    {unidad.file_name}
                  </a>
                  <span class="cuenta tabular">
                    pág. {pageRange(unidad.page_numbers)}
                  </span>
                </div>
                {#if unidad.title}
                  <p class="asunto" title={unidad.title}>{unidad.title}</p>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}
      </li>
    {/each}
  </ul>

  {#if olvidados > 0}
    <!-- Se dice, no se rellena: un documento que ya no está en pantalla no
         puede enseñar lo que produjo, y fingir un número sería peor. -->
    <p class="nota">
      {olvidados}
      {olvidados === 1 ? 'documento salió' : 'documentos salieron'} de la pantalla y ya no
      pueden detallarse aquí. Están en el archivo.
    </p>
  {/if}

  {#if documentos.length === 0 && olvidados === 0}
    <p class="nota">Todavía no se ha tomado ningún archivo de la carpeta.</p>
  {/if}
</div>

<style>
  .arbol {
    display: flex;
    min-width: 0;
    flex-direction: column;
    font-size: var(--text-sm);
  }

  .nodo {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 0.4rem;
    padding: 2px 0;
  }

  .raiz .etiqueta {
    font-weight: 650;
  }

  .destino .etiqueta {
    color: var(--muted);
  }

  /* La sangría y el filete que la acompaña: es lo que convierte una lista en un
     árbol sin necesidad de dibujar líneas por cada rama. */
  .hijos {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0 0 0 0.85rem;
    border-left: 1px solid var(--rule);
    list-style: none;
  }
  .arbol > .hijos {
    margin-left: 0.35rem;
  }

  .rama {
    flex: none;
    width: 0.55rem;
    height: 1px;
    align-self: center;
    background: var(--rule);
  }

  /* Carpeta, PDF y unidad, del juego común de íconos (antes, emojis: cada
     sistema los dibuja a su manera y ponen un tono que esta consola no tiene). */
  .glifo {
    --icono: 14px;
    display: grid;
    flex: none;
    place-items: center;
    color: var(--muted);
  }

  .etiqueta {
    overflow: hidden;
    min-width: 0;
    flex: 1;
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .enlace {
    color: var(--accent);
    text-decoration: none;
  }
  .enlace:hover {
    text-decoration: underline;
  }

  .cuenta {
    flex: none;
    font-size: var(--text-xs);
    color: var(--muted);
  }
  .estado {
    flex: none;
    padding-block: 0;
  }
  /* El botón de cada fila es el `btn-sm` común, apretado a la altura de la
     línea del árbol para que no la ensanche. */
  .nodo .btn {
    flex: none;
    min-height: 0;
    padding-block: 1px;
  }

  /* La fila del PDF es el control que la despliega: no lleva la caja de
     `.btn`, como cualquier rama de un árbol. */
  .pliegue {
    display: flex;
    min-width: 0;
    flex: 1;
    align-items: center;
    gap: 0.4rem;
    border: 0;
    background: transparent;
    padding: 0;
    font: inherit;
    text-align: left;
    color: inherit;
    cursor: pointer;
  }
  .pliegue:disabled {
    cursor: default;
  }
  .pliegue:hover:not(:disabled) .etiqueta {
    color: var(--ink);
  }

  .chevron {
    --icono: 12px;
    display: grid;
    flex: none;
    width: 0.75rem;
    place-items: center;
    color: var(--muted);
  }

  /* El asunto es la única línea que puede ser larga, y es la que dice qué es
     cada unidad: se recorta a lo ancho en vez de romper la fila. */
  .asunto {
    overflow: hidden;
    margin: 0 0 2px 2.1rem;
    font-size: var(--text-xs);
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--muted);
  }

  [data-state='failed'] .etiqueta {
    color: var(--critical);
  }
  [data-state='running'] .etiqueta {
    color: var(--ink);
  }

  .pdf > .inline-error {
    margin: 2px 0 4px 1.4rem;
    font-size: var(--text-xs);
  }
  .aviso {
    margin: 0.35rem 0 0 1.9rem;
    font-size: var(--text-xs);
    line-height: 1.45;
    color: var(--muted);
  }

  .nota {
    margin: 0.5rem 0 0;
    font-size: var(--text-xs);
    color: var(--muted);
  }
</style>
