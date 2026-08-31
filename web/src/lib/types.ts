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
  batch_id: string | null;
  filename: string;
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
  percent: number;
  resolutions: number;
  review_items: number;
  job_ids: string[];
}
