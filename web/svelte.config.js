import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
export default {
  preprocess: vitePreprocess(),
  kit: {
    // The front is a static shell; every byte of state comes from the API.
    adapter: adapter({ fallback: 'index.html' })
  }
};
