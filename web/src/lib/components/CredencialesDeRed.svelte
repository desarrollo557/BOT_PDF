<script lang="ts">
  import { preguntaDeRed } from '$lib/red.svelte';

  /**
   * Usuario y clave de una carpeta de red, pedidos cuando el servidor los pide.
   *
   * Viajan al servicio, que entra con ellos y los guarda sólo en su memoria;
   * aquí no se guardan, ni en el navegador ni en ningún archivo. Al cerrar el
   * cuadro se borran del formulario.
   */
  const pregunta = $derived(preguntaDeRed.actual);

  let usuario = $state('');
  let clave = $state('');
  let campoUsuario = $state<HTMLInputElement | null>(null);

  $effect(() => {
    if (pregunta) campoUsuario?.focus();
  });

  function cerrar(cuenta: { usuario: string; clave: string } | null) {
    preguntaDeRed.responder(cuenta);
    clave = '';
  }

  function enviar(evento: SubmitEvent) {
    evento.preventDefault();
    if (!usuario.trim()) return;
    cerrar({ usuario: usuario.trim(), clave });
  }

  function teclas(evento: KeyboardEvent) {
    if (pregunta && evento.key === 'Escape') {
      evento.preventDefault();
      cerrar(null);
    }
  }
</script>

<svelte:window onkeydown={teclas} />

{#if pregunta}
  <div class="velo" role="presentation" onclick={() => cerrar(null)}></div>
  <div
    class="hoja"
    role="dialog"
    aria-modal="true"
    aria-labelledby="red-titulo"
    aria-describedby="red-mensaje"
  >
    <form onsubmit={enviar} autocomplete="off">
      <h2 id="red-titulo">Carpeta de red</h2>
      <p id="red-mensaje">{pregunta.mensaje}</p>
      <p class="recurso mono">{pregunta.recurso}</p>

      <label>
        <span>Usuario</span>
        <input
          bind:this={campoUsuario}
          bind:value={usuario}
          class="input mono"
          placeholder="DOMINIO\usuario"
          autocomplete="off"
          spellcheck="false"
          required
        />
      </label>
      <label>
        <span>Clave</span>
        <input bind:value={clave} class="input" type="password" autocomplete="off" />
      </label>
      <small>
        El mismo usuario y clave con que entra a Windows. Si no escribe el dominio, se usa el de
        este equipo. Se usan sólo para entrar a esta carpeta y no se guardan en ningún archivo.
      </small>

      <div class="botones">
        <button type="button" class="btn" onclick={() => cerrar(null)}>Cancelar</button>
        <button type="submit" class="btn btn-primary" disabled={!usuario.trim()}>Conectar</button>
      </div>
    </form>
  </div>
{/if}

<style>
  .velo {
    position: fixed;
    inset: 0;
    z-index: 100;
    background: var(--scrim);
    backdrop-filter: blur(3px);
  }

  /* Por encima del explorador de carpetas (90), que es desde donde suele pedirse. */
  .hoja {
    position: fixed;
    top: 50%;
    left: 50%;
    z-index: 101;
    width: min(26rem, calc(100vw - 2rem));
    transform: translate(-50%, -50%);
    border: 1px solid var(--hairline);
    border-radius: var(--radius-xl);
    background: var(--surface-2);
    box-shadow: var(--shadow-lg);
    padding: 1.2rem 1.3rem 1rem;
  }

  form {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }

  h2 {
    margin: 0;
    font-size: var(--text-lg);
    font-weight: 650;
    letter-spacing: -0.01em;
  }

  p {
    margin: 0;
    font-size: var(--text-md);
    line-height: 1.5;
    color: var(--ink-2);
  }

  .recurso {
    overflow-wrap: anywhere;
    font-size: var(--text-sm);
    color: var(--muted);
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    font-size: var(--text-sm);
    font-weight: 600;
  }

  small {
    font-size: var(--text-xs);
    color: var(--muted);
  }

  .botones {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    margin-top: 0.4rem;
  }
</style>
