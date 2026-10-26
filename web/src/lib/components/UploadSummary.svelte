<script lang="ts">
  import { formatBytes } from '$lib/format';
  import type { Habilidad } from '$lib/habilidades';
  import type {
    AgruparChoice,
    CorteChoice,
    LecturaChoice,
    OracleChoice,
    TaskKind,
    TipoPedido
  } from '$lib/tipos';

  /**
   * What is about to happen, said before it happens.
   *
   * With files staged it is the last check before uploading: what they are,
   * how they will be read and what comes back, plus the totals. Without files
   * it is the same list as a reminder of the choices, and no action button --
   * a "confirm" that has nothing to confirm is a button that does nothing.
   */
  interface Props {
    files: File[];
    mode: 'single' | 'batch' | 'folder';
    habilidad: Habilidad;
    lectura: LecturaChoice;
    task: TaskKind;
    tipo: TipoPedido;
    corte?: CorteChoice;
    agrupar?: AgruparChoice;
    oracle?: OracleChoice;
    source?: string;
    destination?: string;
    disposition?: 'leave' | 'move' | 'delete';
    watch?: boolean;
    /** What the run leaves in the destination, already worded by the panel. */
    entrega?: string;
    /** Back to adjust the choices. */
    onback?: () => void;
    /** Upload the staged files. Only offered when there are files. */
    onconfirm?: () => void;
    /** Drop the staged files without uploading them. */
    onclear?: () => void;
    busy?: boolean;
  }

  let {
    files,
    mode,
    habilidad,
    lectura,
    task,
    tipo,
    corte,
    agrupar,
    oracle,
    source,
    destination,
    disposition,
    watch,
    entrega,
    onback,
    onconfirm,
    onclear,
    busy = false
  }: Props = $props();

  const MODE_LABELS = {
    single: 'Carga individual',
    batch: 'Carga por lote',
    folder: 'Carpeta local'
  };

  const TASK_LABELS: Record<string, string> = {
    split: 'Partir en documentos',
    inventory: 'Solo inventariar',
    both: 'Partir e inventariar',
    segment: 'Separar por documento',
    inventory_file: 'Inventariar el archivo'
  };

  const LECTURA: Record<string, { label: string; hint: string }> = {
    local: { label: 'Solo OCR', hint: 'Gratis. Lee lo impreso y mecanografiado.' },
    mistral: { label: 'OCR + IA', hint: 'Se paga por página. Añade lo escrito a mano.' },
    'mistral-nombres': {
      label: 'OCR + IA (ahorro)',
      hint: 'Diez caras por página facturada. Lee sólo el nombre.'
    }
  };

  const ORACLE_LABELS: Record<string, string> = {
    auto: 'Automático',
    claude: 'Claude',
    gemini: 'Gemini',
    mistral: 'Mistral'
  };

  const DISPOSITION_LABELS = {
    leave: 'Dejarlo donde está',
    move: 'Apartarlo a «_procesados»',
    delete: 'Borrarlo'
  };

  const totalFiles = $derived(files.length);
  const totalBytes = $derived(files.reduce((sum, file) => sum + file.size, 0));

  const corteLabel = $derived(
    habilidad.cortes?.opciones.find((opcion) => opcion.id === corte)?.label ?? corte
  );
  const agruparLabel = $derived(
    habilidad.agrupar?.opciones.find((opcion) => opcion.id === agrupar)?.label ?? agrupar
  );
  const lecturaInfo = $derived(LECTURA[lectura] ?? { label: lectura, hint: '' });

  /** How many staged files are listed by name; the rest are counted. */
  const LISTED = 6;
</script>

<section class="panel panel-inset summary" aria-label="Resumen de la carga">
  <header>
    <div>
      <h3>{totalFiles ? 'Revisa antes de subir' : 'Resumen de la configuración'}</h3>
      <p class="subtitle">
        {#if totalFiles}
          {totalFiles} {totalFiles === 1 ? 'archivo' : 'archivos'} · {formatBytes(totalBytes)}
        {:else if mode === 'folder'}
          Se aplicará a cada PDF de la carpeta.
        {:else}
          Suelta los PDF para revisarlos aquí antes de subirlos.
        {/if}
      </p>
    </div>
    {#if onback}
      <button type="button" class="btn btn-ghost btn-sm" onclick={onback}>Ajustar</button>
    {/if}
  </header>

  <dl>
    <div class="row">
      <dt>Tipo de documento</dt>
      <dd>
        <strong>{habilidad.titulo}</strong>
        {#if tipo !== 'auto'}
          <span class="hint">Declarado: no se gasta la muestra de reconocimiento.</span>
        {/if}
      </dd>
    </div>

    <div class="row">
      <dt>Acción</dt>
      <dd>
        <strong>
          {task === 'both' && (tipo === 'acta-consejo' || tipo === 'acta')
            ? 'Dividir e inventariar'
            : (TASK_LABELS[task] ?? task)}
        </strong>
        {#if entrega}<span class="hint">{entrega}</span>{/if}
      </dd>
    </div>

    <div class="row">
      <dt>Lectura</dt>
      <dd>
        <strong>{lecturaInfo.label}</strong>
        {#if lecturaInfo.hint}<span class="hint">{lecturaInfo.hint}</span>{/if}
      </dd>
    </div>

    {#if habilidad.cortes && corteLabel}
      <div class="row">
        <dt>Corte</dt>
        <dd><strong>{corteLabel}</strong></dd>
      </div>
    {/if}

    {#if habilidad.agrupar && agruparLabel}
      <div class="row">
        <dt>Agrupación</dt>
        <dd><strong>{agruparLabel}</strong></dd>
      </div>
    {/if}

    {#if task === 'segment'}
      <div class="row">
        <dt>Modelo de IA</dt>
        <dd><strong>{ORACLE_LABELS[oracle ?? 'auto'] ?? oracle}</strong></dd>
      </div>
    {/if}

    <div class="row">
      <dt>Origen</dt>
      <dd><strong>{MODE_LABELS[mode]}</strong></dd>
    </div>

    {#if mode === 'folder' && (source || destination)}
      <div class="row">
        <dt>Carpetas</dt>
        <dd class="paths">
          <span><span class="key">Origen</span><code>{source || '—'}</code></span>
          <span><span class="key">Destino</span><code>{destination || '—'}</code></span>
          <span>
            <span class="key">Al terminar</span>{DISPOSITION_LABELS[disposition ?? 'leave']}
            {#if watch}· queda vigilando archivos nuevos{/if}
          </span>
        </dd>
      </div>
    {/if}
  </dl>

  {#if totalFiles}
    <ul class="files">
      {#each files.slice(0, LISTED) as file (file.name + file.size)}
        <li>
          <span class="name" title={file.name}>{file.name}</span>
          <span class="size">{formatBytes(file.size)}</span>
        </li>
      {/each}
      {#if totalFiles > LISTED}
        <li class="more">y {totalFiles - LISTED} más</li>
      {/if}
    </ul>
  {/if}

  {#if totalFiles && onconfirm}
    <footer>
      {#if onclear}
        <button type="button" class="btn" onclick={onclear} disabled={busy}>Quitar</button>
      {/if}
      <button type="button" class="btn btn-primary" onclick={onconfirm} disabled={busy}>
        Confirmar y subir {totalFiles} {totalFiles === 1 ? 'archivo' : 'archivos'}
      </button>
    </footer>
  {/if}
</section>

<style>
  /* El `.panel-inset` común: un escalón por debajo de la tarjeta del asistente
     que lo contiene. */
  .summary {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }

  header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-4);
  }

  h3 {
    margin: 0;
    font-size: var(--text-lg);
    font-weight: 650;
    color: var(--ink);
  }

  .subtitle {
    margin: var(--space-1) 0 0;
    font-size: var(--text-sm);
    color: var(--muted);
    font-variant-numeric: tabular-nums;
  }

  dl {
    display: flex;
    flex-direction: column;
    margin: 0;
  }

  .row {
    display: grid;
    grid-template-columns: minmax(7rem, 10rem) 1fr;
    gap: var(--space-3);
    border-top: 1px solid var(--rule);
    padding: var(--space-2) 0;
  }

  dt {
    font-size: var(--text-xs);
    font-weight: 600;
    line-height: 1.6;
    color: var(--muted);
  }

  dd {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 2px;
    margin: 0;
    font-size: var(--text-sm);
    color: var(--ink);
  }

  dd strong {
    font-weight: 600;
  }

  .hint {
    font-size: var(--text-xs);
    line-height: 1.45;
    color: var(--ink-2);
  }

  .paths span {
    display: flex;
    min-width: 0;
    gap: var(--space-2);
  }

  .key {
    flex-shrink: 0;
    min-width: 5.5rem;
    color: var(--muted);
  }

  code {
    min-width: 0;
    overflow-wrap: anywhere;
    font-family: var(--font-mono);
    font-size: var(--text-xs);
  }

  .files {
    display: flex;
    flex-direction: column;
    margin: 0;
    border: 1px solid var(--hairline);
    border-radius: var(--radius);
    padding: 0;
    list-style: none;
    background: var(--surface-2);
  }

  .files li {
    display: flex;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-3);
    font-size: var(--text-sm);
  }

  .files li + li {
    border-top: 1px solid var(--rule);
  }

  .name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--ink);
  }

  .size,
  .more {
    flex-shrink: 0;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
  }

  footer {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: var(--space-2);
  }

  @media (max-width: 40rem) {
    .row {
      grid-template-columns: 1fr;
      gap: 2px;
    }
  }
</style>
