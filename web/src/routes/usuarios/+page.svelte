<script lang="ts">
  import { onMount } from 'svelte';
  import { cambiarUsuario, crearUsuario, darDeBaja, listarUsuarios } from '$lib/api';
  import { session } from '$lib/session.svelte';
  import type { UsuarioApi } from '$lib/types';

  /**
   * Quién entra al separador, y con qué perfil.
   *
   * Sólo la ve el administrador, y el servicio lo comprueba además de que la
   * pestaña no esté: esconder una pantalla no cierra nada frente a quien
   * escriba la dirección a mano, así que las dos cosas hacen falta y ninguna
   * sustituye a la otra.
   *
   * La cédula es la clave y por eso no se edita. Cambiarla sería dar de baja a
   * una persona y de alta a otra, que conviene que se vea como dos actos.
   *
   * **Ningún campo se envía en blanco**, el nombre incluido. Lo pidió el
   * archivo y tiene su razón: un alta sin nombre deja una fila que sólo se sabe
   * leer por su cédula, y nadie vuelve sobre ella para completarla. El botón
   * está apagado hasta que los cuatro campos digan algo, en vez de dejar que se
   * pulse y conteste el servicio: un formulario que se envía para que lo
   * rechacen hace teclear dos veces lo mismo.
   */
  const PERFILES = [
    {
      valor: 'administrador',
      etiqueta: 'Administrador',
      hace: 'Procesa, revisa, descarga el FUID y da de alta a los demás.'
    },
    {
      valor: 'tecnico',
      etiqueta: 'Técnico',
      hace: 'Procesa cajas. Ve el FUID en pantalla y no descarga el Excel.'
    },
    {
      valor: 'calidad',
      etiqueta: 'Calidad',
      hace: 'Revisa lo que salió. Ve el FUID en pantalla y no descarga el Excel.'
    }
  ];

  let usuarios = $state<UsuarioApi[]>([]);
  let cargando = $state(true);
  let error = $state<string | null>(null);
  let aviso = $state<string | null>(null);

  let cedula = $state('');
  let correo = $state('');
  let nombre = $state('');
  let perfil = $state('tecnico');
  let guardando = $state(false);

  /** A quién se está dando de baja, para pedir confirmación antes de hacerlo. */
  let confirmando = $state<string | null>(null);

  const cedulaValida = $derived(cedula.replace(/\D/g, '').length >= 5);
  const correoValido = $derived(/^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/.test(correo.trim()));
  const nombreValido = $derived(nombre.trim().length >= 2);
  const perfilValido = $derived(PERFILES.some((opcion) => opcion.valor === perfil));
  const puedeDarDeAlta = $derived(
    cedulaValida && correoValido && nombreValido && perfilValido && !guardando
  );

  /** Qué le falta al formulario, dicho antes de que nadie pulse nada. */
  const faltan = $derived(
    [
      cedulaValida ? null : 'la cédula',
      correoValido ? null : 'el correo',
      nombreValido ? null : 'el nombre'
    ].filter(Boolean) as string[]
  );

  /**
   * Cuántos administradores quedan.
   *
   * La pantalla lo mira para apagar el botón del último, en vez de dejar que lo
   * pulse y reciba un rechazo: el servicio también lo impide, y aquí se explica
   * antes para que nadie tenga que descubrirlo a base de errores.
   */
  const administradores = $derived(usuarios.filter((u) => u.perfil === 'administrador').length);

  onMount(cargar);

  async function cargar() {
    cargando = true;
    error = null;
    try {
      usuarios = await listarUsuarios();
    } catch (problema) {
      error = (problema as Error).message;
    } finally {
      cargando = false;
    }
  }

  async function darDeAlta(event: Event) {
    event.preventDefault();
    if (!puedeDarDeAlta) return;
    guardando = true;
    error = null;
    aviso = null;
    try {
      const creado = await crearUsuario({ cedula, correo, perfil, nombre });
      aviso = `${creado.nombre || creado.cedula} queda de ${creado.perfil_label.toLowerCase()}.`;
      cedula = correo = nombre = '';
      perfil = 'tecnico';
      await cargar();
    } catch (problema) {
      error = (problema as Error).message;
    } finally {
      guardando = false;
    }
  }

  async function cambiarPerfil(usuario: UsuarioApi, nuevo: string) {
    if (nuevo === usuario.perfil) return;
    error = null;
    aviso = null;
    try {
      const cambiado = await cambiarUsuario(usuario.cedula, { perfil: nuevo });
      aviso = `${cambiado.nombre || cambiado.cedula} queda de ${cambiado.perfil_label.toLowerCase()}.`;
      await cargar();
    } catch (problema) {
      error = (problema as Error).message;
      // Se recarga igual: el desplegable ya se movió en pantalla y dejarlo
      // mostrando un perfil que el servicio rechazó sería enseñar algo falso.
      await cargar();
    }
  }

  async function baja(usuario: UsuarioApi) {
    error = null;
    aviso = null;
    try {
      await darDeBaja(usuario.cedula);
      aviso = `${usuario.nombre || usuario.cedula} ya no entra.`;
      confirmando = null;
      await cargar();
    } catch (problema) {
      error = (problema as Error).message;
      confirmando = null;
    }
  }

  /** Si dar de baja a este dejaría al archivo sin nadie que administre. */
  function esElUltimoAdministrador(usuario: UsuarioApi): boolean {
    return usuario.perfil === 'administrador' && administradores <= 1;
  }
</script>

<svelte:head><title>Usuarios · Separador</title></svelte:head>

<section class="wrap">
  <header class="intro">
    <h1>Usuarios</h1>
    <p>
      Quién entra al separador y qué se le deja hacer. Se entra con la cédula y el correo, sin
      contraseña, así que esto ordena el trabajo pero no lo protege: quien conozca los datos de
      un compañero puede entrar como él.
    </p>
  </header>

  {#if error}
    <p class="banner bad" role="alert">{error}</p>
  {/if}
  {#if aviso}
    <p class="banner good">{aviso}</p>
  {/if}

  <div class="columnas">
    <form class="alta" onsubmit={darDeAlta}>
      <h2>Dar de alta</h2>

      <label>
        <span>Cédula</span>
        <input bind:value={cedula} placeholder="1 047 382 991" inputmode="numeric" />
      </label>

      <label>
        <span>Correo</span>
        <input bind:value={correo} placeholder="nombre@unicartagena.edu.co" type="email" />
      </label>

      <label>
        <span>Nombre</span>
        <input bind:value={nombre} placeholder="Ana Martínez" />
      </label>

      <fieldset>
        <legend>Perfil</legend>
        {#each PERFILES as opcion (opcion.valor)}
          <label class="radio">
            <input type="radio" bind:group={perfil} value={opcion.valor} />
            <span>
              <b>{opcion.etiqueta}</b>
              <small>{opcion.hace}</small>
            </span>
          </label>
        {/each}
      </fieldset>

      {#if faltan.length}
        <p class="falta">Falta {faltan.join(', ').replace(/, ([^,]*)$/, ' y $1')}.</p>
      {/if}

      <button class="primary" type="submit" disabled={!puedeDarDeAlta}>
        {guardando ? 'Dando de alta…' : 'Dar de alta'}
      </button>
    </form>

    <div class="listado">
      <h2>Dados de alta <span class="cuenta">{usuarios.length}</span></h2>

      {#if cargando}
        <p class="quiet">Cargando…</p>
      {:else if !usuarios.length}
        <p class="quiet">Todavía no hay nadie dado de alta.</p>
      {:else}
        <ul>
          {#each usuarios as usuario (usuario.cedula)}
            <li class:yo={usuario.cedula === session.cedula}>
              <div class="quien">
                <b>{usuario.nombre || usuario.cedula}</b>
                <small>{usuario.correo}</small>
                <small class="tabular">{usuario.cedula}</small>
              </div>

              <select
                value={usuario.perfil}
                onchange={(event) => cambiarPerfil(usuario, event.currentTarget.value)}
                disabled={esElUltimoAdministrador(usuario)}
                title={esElUltimoAdministrador(usuario)
                  ? 'Es el único administrador. Dé de alta a otro antes de cambiarle el perfil.'
                  : ''}
              >
                {#each PERFILES as opcion (opcion.valor)}
                  <option value={opcion.valor}>{opcion.etiqueta}</option>
                {/each}
              </select>

              {#if confirmando === usuario.cedula}
                <span class="confirmar">
                  <button class="danger" onclick={() => baja(usuario)}>Sí, dar de baja</button>
                  <button class="ghost" onclick={() => (confirmando = null)}>No</button>
                </span>
              {:else}
                <button
                  class="ghost"
                  onclick={() => (confirmando = usuario.cedula)}
                  disabled={esElUltimoAdministrador(usuario)}
                  title={esElUltimoAdministrador(usuario)
                    ? 'Es el único administrador. El archivo se quedaría sin quien dé de alta.'
                    : ''}
                >
                  dar de baja
                </button>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  </div>
</section>

<style>
  .wrap {
    max-width: 68rem;
    margin: 0 auto;
    padding: 1.5rem 1rem 3rem;
  }
  .intro h1 {
    margin: 0;
    font-size: 1.15rem;
    font-weight: 650;
    letter-spacing: -0.015em;
  }
  .intro p {
    max-width: 46rem;
    margin: 0.4rem 0 1.25rem;
    font-size: 0.84rem;
    line-height: 1.55;
    color: var(--muted);
  }

  .banner {
    margin: 0 0 1rem;
    border-radius: 9px;
    padding: 0.6rem 0.8rem;
    font-size: 0.84rem;
    line-height: 1.5;
  }
  .bad {
    border: 1px solid var(--critical);
    background: color-mix(in oklab, var(--critical) 10%, transparent);
    color: var(--critical);
  }
  .good {
    border: 1px solid var(--accent);
    background: var(--accent-soft);
    color: var(--accent);
  }

  .columnas {
    display: grid;
    gap: 1.25rem;
    grid-template-columns: minmax(0, 20rem) minmax(0, 1fr);
    align-items: start;
  }
  @media (max-width: 60rem) {
    .columnas {
      grid-template-columns: minmax(0, 1fr);
    }
  }

  h2 {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0 0 0.9rem;
    font-size: 0.72rem;
    font-weight: 650;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--muted);
  }
  .cuenta {
    border-radius: 999px;
    background: var(--plane);
    padding: 0.08rem 0.45rem;
    font-size: 0.72rem;
    letter-spacing: 0;
    color: var(--ink-2);
  }

  .alta,
  .listado {
    border: 1px solid var(--hairline);
    border-radius: 14px;
    background: var(--surface-2);
    padding: 1.1rem;
    box-shadow: var(--shadow);
  }
  .alta {
    display: flex;
    flex-direction: column;
    gap: 0.85rem;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }
  /* El rótulo de un campo, en versalitas. Excluye el de un radio a propósito:
     ahí el `span` envuelve el nombre del perfil y su explicación, y ponerla en
     mayúsculas convierte dos renglones de prosa en un cartel ilegible. */
  label:not(.radio) > span {
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.055em;
    text-transform: uppercase;
    color: var(--muted);
  }
  label i {
    font-style: normal;
    font-weight: 400;
    text-transform: none;
    letter-spacing: 0;
  }
  input[type='text'],
  input[type='email'],
  input:not([type]) {
    border: 1px solid var(--hairline);
    border-radius: 9px;
    background: var(--plane);
    padding: 0.5rem 0.7rem;
    font: inherit;
    font-size: 0.88rem;
    color: inherit;
    outline: none;
  }
  input:focus {
    border-color: var(--accent);
  }

  fieldset {
    border: 1px solid var(--rule);
    border-radius: 9px;
    margin: 0;
    padding: 0.6rem 0.7rem 0.7rem;
  }
  legend {
    padding: 0 0.35rem;
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.055em;
    text-transform: uppercase;
    color: var(--muted);
  }
  .radio {
    flex-direction: row;
    align-items: flex-start;
    gap: 0.5rem;
    padding: 0.3rem 0;
    cursor: pointer;
  }
  .radio input {
    margin-top: 0.2rem;
  }
  .radio b {
    display: block;
    font-size: 0.85rem;
    font-weight: 600;
  }
  .radio small {
    display: block;
    font-size: 0.74rem;
    line-height: 1.45;
    color: var(--muted);
  }

  ul {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.6rem;
    border: 1px solid var(--rule);
    border-radius: 10px;
    padding: 0.6rem 0.7rem;
  }
  li.yo {
    border-color: var(--accent);
  }
  .quien {
    flex: 1 1 12rem;
    min-width: 0;
  }
  .quien b {
    display: block;
    font-size: 0.9rem;
    font-weight: 600;
  }
  .quien small {
    display: block;
    font-size: 0.75rem;
    color: var(--muted);
    overflow-wrap: anywhere;
  }
  .tabular {
    font-variant-numeric: tabular-nums;
  }

  select {
    border: 1px solid var(--hairline);
    border-radius: 8px;
    background: var(--plane);
    padding: 0.35rem 0.5rem;
    font: inherit;
    font-size: 0.82rem;
    color: inherit;
  }
  select:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .confirmar {
    display: flex;
    gap: 0.4rem;
  }

  button {
    border-radius: 9px;
    font: inherit;
    cursor: pointer;
  }
  .primary {
    border: 1px solid var(--accent);
    background: var(--accent-soft);
    padding: 0.5rem 1rem;
    font-size: 0.86rem;
    font-weight: 600;
    color: var(--accent);
  }
  .primary:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
  .ghost {
    border: 1px solid var(--hairline);
    background: transparent;
    padding: 0.35rem 0.65rem;
    font-size: 0.78rem;
    color: var(--muted);
  }
  .ghost:hover:not(:disabled) {
    border-color: var(--accent);
    color: var(--accent);
  }
  .ghost:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .danger {
    border: 1px solid var(--critical);
    background: color-mix(in oklab, var(--critical) 12%, transparent);
    padding: 0.35rem 0.65rem;
    font-size: 0.78rem;
    color: var(--critical);
  }

  .falta {
    margin: 0;
    font-size: 0.76rem;
    line-height: 1.45;
    color: var(--muted);
  }

  .quiet {
    margin: 0;
    font-size: 0.84rem;
    color: var(--muted);
  }
</style>
