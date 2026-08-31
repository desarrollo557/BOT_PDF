import type { Batch, Job } from './types';

const BASE = '/api';

export class ApiError extends Error {}

async function detailOf(response: Response): Promise<string> {
  const payload = await response.json().catch(() => null);
  return payload?.detail ?? `Error ${response.status}`;
}

export async function createBatch(name: string): Promise<{ id: string; name: string }> {
  const response = await fetch(`${BASE}/batches`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name })
  });
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
}

export async function uploadDocument(file: File, batchId?: string): Promise<{ id: string }> {
  const body = new FormData();
  body.append('file', file);

  const url = batchId ? `${BASE}/jobs?batch_id=${encodeURIComponent(batchId)}` : `${BASE}/jobs`;
  const response = await fetch(url, { method: 'POST', body });
  if (!response.ok) throw new ApiError(await detailOf(response));
  return response.json();
}

export async function listJobs(): Promise<Job[]> {
  const response = await fetch(`${BASE}/jobs`);
  if (!response.ok) return [];
  return (await response.json()).jobs ?? [];
}

export async function listBatches(): Promise<Batch[]> {
  const response = await fetch(`${BASE}/batches`);
  if (!response.ok) return [];
  return (await response.json()).batches ?? [];
}

/**
 * Subscribe to job updates.
 *
 * The server pushes coalesced frames; the client never polls. Polling a queue of
 * long-running jobs is a request storm that says nothing new most of the time.
 */
export function streamJobs(onJob: (job: Job) => void): () => void {
  const events = new EventSource(`${BASE}/events`);
  events.onmessage = (event) => {
    try {
      onJob(JSON.parse(event.data) as Job);
    } catch {
      // A malformed frame is not worth tearing the stream down for.
    }
  };
  return () => events.close();
}

export function downloadUrl(jobId: string, name: string): string {
  return `${BASE}/jobs/${jobId}/outputs/${encodeURIComponent(name)}`;
}

/**
 * Run `task` over `items` with at most `limit` in flight.
 *
 * Fifty uploads fired at once only starve each other and blow up the browser's
 * connection pool; a small window keeps every transfer moving at full speed.
 */
export async function withConcurrency<T>(
  items: T[],
  limit: number,
  task: (item: T, index: number) => Promise<void>
): Promise<void> {
  let cursor = 0;
  const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) {
      const index = cursor++;
      await task(items[index], index);
    }
  });
  await Promise.all(runners);
}
