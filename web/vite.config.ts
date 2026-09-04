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
    // Escuchar en todas las interfaces, no sólo en localhost.
    //
    // Por omisión Vite sólo acepta conexiones de la propia máquina, así que
    // desde otro equipo de la red la pantalla no cargaba en absoluto. El
    // servicio lo opera más de una persona sobre las mismas cajas, de modo que
    // llegar desde otro puesto no es un extra: es como se usa.
    //
    // El backend puede seguir escuchando sólo en 127.0.0.1: quien habla con él
    // es este servidor a través del proxy de abajo, no el navegador remoto.
    host: true,
    proxy: {
      // Proxying keeps every request same-origin, so uploads and the SSE stream
      // never touch CORS or credentialed-request rules in development.
      // El 8000 es el puerto del backend en todo el proyecto: el README, el de
      // db/ y el mensaje de error de api.ts dicen ese y no otro. API_URL sigue
      // mandando para el caso puntual de tener que correr el servicio en otro.
      '/api': {
        target: process.env.API_URL ?? 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  }
});
