import { redirect } from '@sveltejs/kit';

/**
 * Documents and resolutions were two screens showing the same work at two
 * grains. They are one screen now; an old link still lands on it.
 */
export function load() {
  redirect(307, '/archivo');
}
