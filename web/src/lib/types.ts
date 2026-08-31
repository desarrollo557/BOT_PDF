export type JobState = 'queued' | 'running' | 'done' | 'failed';

export interface Group {
  code: string;
  title: string | null;
  pages: number[];
  size: number;
}

export interface Repair {
  page: number;
  observed: string;
  applied: string;
  distance: number;
}

export interface ReviewItem {
  page: number;
  reason: string;
}

export interface InventoryItem {
  file_name: string;
  code: string;
  title: string | null;
  page_count: number;
  first_page: number;
  last_page: number;
  page_numbers: number[];
}

export interface Inventory {
  source_document: string;
  source_pages: number;
  generated_files: number;
  pages_accounted_for: number;
  items: InventoryItem[];
  quarantine_pages: number[];
  review_pages: number[];
}

export interface Stats {
  by_provenance: Record<string, number>;
  escalated: number;
  vision_requests: number;
  resolved_by_context: number;
  vision_page_ratio: number;
  failed_pages: Record<string, string>;
}

export interface Report {
  document: string;
  page_count: number;
  groups: Group[];
  quarantine: number[];
  repairs: Repair[];
  review_queue: ReviewItem[];
  outputs: string[];
  stats: Stats;
  inventory: Inventory | null;
}

/** Live state of one document while it is being processed. */
export interface Progress {
  stage: 'queued' | 'analysing' | 'grouping' | 'assembling' | 'done' | 'failed';
  page_count: number;
  pages_done: number;
  failed_pages: number;
  by_provenance: Record<string, number>;
  /** One character per page: . pending, t text, h header OCR, f full OCR, v model, x unreadable. */
  ribbon: string;
  percent: number;
  pages_per_second: number;
  elapsed_seconds: number;
}

export interface Job {
  id: string;
  /** Set on the frame that announces the job was cleared from the workspace. */
  deleted?: boolean;
  batch_id: string | null;
  filename: string;
  /** Size of the source PDF, recorded at intake. */
  bytes: number;
  /** Who was at the console. Attribution, never authorisation. */
  operator: string | null;
  state: JobState;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  report: Report | null;
  progress: Progress;
}

export interface Batch {
  id: string;
  name: string;
  created_at: string;
  documents: number;
  done: number;
  failed: number;
  running: number;
  queued: number;
  pages_total: number;
  pages_done: number;
  bytes_total: number;
  percent: number;
  resolutions: number;
  review_items: number;
  job_ids: string[];
}

/** One generated resolution PDF, as the durable inventory recorded it. */
export interface InventoryRow {
  recorded_at: string;
  source_document: string;
  code: string;
  title: string | null;
  file_name: string;
  page_count: number;
  first_page: number;
  last_page: number;
  pages: string;
  job_id: string;
  operator: string | null;
}

export interface InventorySummary {
  resolutions: number;
  documents: number;
  codes: number;
  pages: number;
}

export interface InventoryPage {
  rows: InventoryRow[];
  total: number;
  offset: number;
  limit: number;
  summary: InventorySummary;
}

export type RunState = 'scanning' | 'processing' | 'watching' | 'done' | 'stopped' | 'failed';
export type SourceDisposition = 'leave' | 'move' | 'delete';

/** One generated PDF copied into the destination folder. */
export interface Delivery {
  file_name: string;
  source_document: string;
  destination: string;
  at: string;
}

/** A local source folder being drained into a local destination folder. */
export interface FolderRun {
  kind: 'folder_run';
  id: string;
  source: string;
  destination: string;
  disposition: SourceDisposition;
  watch: boolean;
  operator: string | null;
  state: RunState;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  queue: string[];
  current: string | null;
  current_job_id: string | null;
  /** Every document the run created, in the order it took them. */
  job_ids: string[];
  discovered: number;
  processed: number;
  bytes_total: number;
  pages_total: number;
  failed: number;
  delivered: number;
  resolutions: number;
  deliveries: Delivery[];
}

/** One source document ever processed, folded back out of the ledger. */
export interface ProcessedDocument {
  job_id: string;
  source_document: string;
  processed_at: string;
  resolutions: number;
  pages: number;
  codes: string[];
  operator: string | null;
  /** Facts about the source document, recorded alongside its resolutions. */
  source_pages: number;
  bytes: number;
  review: number;
}

/** Una carpeta, tal como la lista el explorador del servicio. */
export interface FolderEntry {
  name: string;
  path: string;
}

export interface FolderListing {
  path: string | null;
  parent: string | null;
  drives: FolderEntry[];
  folders: FolderEntry[];
}
