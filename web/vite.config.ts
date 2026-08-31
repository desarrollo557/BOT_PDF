import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  server: {
    port: 5173,
    proxy: {
      // Proxying keeps every request same-origin, so uploads and the SSE stream
      // never touch CORS or credentialed-request rules in development.
      '/api': {
        target: process.env.API_URL ?? 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  }
});
