<script lang="ts">
  import { page } from '$app/state';
</script>

<section class="panel fallo">
  <p class="codigo tabular">{page.status}</p>
  <h1>{page.status === 404 ? 'Esta pantalla no existe' : 'No se pudo mostrar esta pantalla'}</h1>
  <p class="detalle">{page.error?.message ?? 'Ocurrió un error inesperado.'}</p>
  <p class="detalle">
    El trabajo que estaba en curso sigue en el servicio: volver no lo detiene.
  </p>
  <div class="acciones">
    <a class="btn btn-primary" href="/">Volver a Procesar</a>
    <button type="button" class="btn" onclick={() => location.reload()}>Recargar</button>
  </div>
</section>

<style>
  /* La tarjeta común (`.panel`), con el filete rojo arriba: la pantalla es un
     fallo antes de leer nada. */
  .fallo {
    max-width: 34rem;
    margin: 4rem auto;
    border-top: 3px solid var(--critical);
    padding: var(--space-6);
  }
  .codigo {
    margin: 0;
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    color: var(--critical);
  }
  h1 {
    margin: 0.3rem 0 0.6rem;
    font-size: var(--text-xl);
    font-weight: 650;
    letter-spacing: -0.015em;
  }
  .detalle {
    margin: 0.35rem 0 0;
    font-size: var(--text-md);
    line-height: 1.5;
    color: var(--ink-2);
  }
  /* Los botones son los comunes: volver es la acción principal de esta
     pantalla, recargar la segunda. */
  .acciones {
    display: flex;
    gap: 0.6rem;
    margin-top: 1.2rem;
  }
</style>
