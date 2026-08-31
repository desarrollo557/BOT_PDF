import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  // Rune files are compiled by the Svelte plugin, so the store logic is tested
  // as it actually runs rather than as a plain-TS lookalike.
  test: {
    include: ['src/**/*.test.ts'],
    environment: 'node'
  },
  server: {
    port: 5173,
    proxy: {
      // Proxying keeps every request same-origin, so uploads and the SSE stream
      // never touch CORS or credentialed-request rules in development.
      // 8001, no 8000: en esta máquina quedó un socket huérfano enlazado al
      // 8000 que no se puede cerrar sin permisos de administrador y que gana
      // todas las peticiones, dejando cualquier servicio nuevo tapado detrás.
      // Se vuelve al 8000 en cuanto se cierre ese proceso o se reinicie el
      // equipo; mientras tanto, API_URL manda.
      '/api': {
        target: process.env.API_URL ?? 'http://127.0.0.1:8001',
        changeOrigin: true
      }
    }
  }
});
