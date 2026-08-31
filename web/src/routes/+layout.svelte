<script lang="ts">
  import '../app.css';

  let { children } = $props();
</script>

<div class="mx-auto max-w-5xl px-5 pt-10 pb-20">
  <header class="mb-8">
    <h1 class="text-2xl font-semibold tracking-tight">Separador de resoluciones</h1>
    <p class="mt-1 text-ink-2">
      Cargue los PDF y cada página se dirige a la resolución que le corresponde.
    </p>
  </header>
  {@render children()}
</div>
