import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * La máquina de la sesión, transición por transición.
 *
 * Dos cosas se fijan aquí y conviene no perderlas. La primera es que `idle` es
 * un corte y no un candado: reanudar no pide nada, porque no hay nada que
 * destrabar. La segunda es que **el perfil no lo decide esta clase**: lo
 * contesta el servicio, y lo que se guarda en el navegador es una copia para
 * pintar. Un almacenamiento manipulado a mano puede decir «administrador» y no
 * gana ningún permiso, porque cada petición se vuelve a juzgar en el servicio.
 */

const entrar = vi.fn();

vi.mock('$lib/api', () => ({
  entrar: (cedula: string, correo: string) => entrar(cedula, correo),
  ApiError: class ApiError extends Error {}
}));

const { ApiError } = await import('$lib/api');
const { IDLE_AFTER_MS, Session } = await import('./session.svelte');

const JEFE = {
  cedula: '1047382991',
  correo: 'jefe@archivo.edu.co',
  nombre: 'Ana Martínez',
  perfil: 'administrador',
  perfil_label: 'Administrador'
};

const TECNICA = {
  cedula: '52814663',
  correo: 'tecnica@archivo.edu.co',
  nombre: 'Quien procesa',
  perfil: 'tecnico',
  perfil_label: 'Técnico'
};

function storage() {
  const data = new Map<string, string>();
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key),
    get size() {
      return data.size;
    }
  };
}

/**
 * La sesión escucha la ventana para saber si hay actividad. Doblarla en vez de
 * arrastrar un DOM entero mantiene estas pruebas sobre la máquina, que es lo
 * que vale la pena fijar aquí.
 */
function fakeWindow() {
  const listeners = new Map<string, Set<(event: unknown) => void>>();
  return {
    addEventListener: (name: string, fn: (event: unknown) => void) => {
      if (!listeners.has(name)) listeners.set(name, new Set());
      listeners.get(name)!.add(fn);
    },
    removeEventListener: (name: string, fn: (event: unknown) => void) => {
      listeners.get(name)?.delete(fn);
    },
    listeners
  };
}

/** Una sesión guardada, en la forma en que la escribe la clase. */
function guardar(quien: typeof JEFE, lastSeen: number) {
  localStorage.setItem(
    'resolutions.session',
    JSON.stringify({
      operator: {
        cedula: quien.cedula,
        correo: quien.correo,
        nombre: quien.nombre,
        perfil: quien.perfil,
        perfilLabel: quien.perfil_label,
        startedAt: lastSeen
      },
      lastSeen
    })
  );
}

beforeEach(() => {
  vi.stubGlobal('localStorage', storage());
  vi.stubGlobal('window', fakeWindow());
  entrar.mockReset();
  entrar.mockResolvedValue(JEFE);
});

describe('transiciones', () => {
  it('empieza sin sesión', () => {
    expect(new Session().state).toBe('anonymous');
  });

  it('entrar con cédula y correo la deja activa', async () => {
    const session = new Session();
    expect(await session.open('1047382991', 'jefe@archivo.edu.co')).toBe(true);
    expect(session.state).toBe('active');
    expect(session.cedula).toBe('1047382991');
  });

  it('el nombre que se enseña es el que contestó el servicio', async () => {
    const session = new Session();
    await session.open('1047382991', 'jefe@archivo.edu.co');
    expect(session.name).toBe('Ana Martínez');
  });

  it('quien no dio nombre se enseña por su cédula', async () => {
    entrar.mockResolvedValue({ ...JEFE, nombre: '' });
    const session = new Session();
    await session.open('1047382991', 'jefe@archivo.edu.co');
    expect(session.name).toBe('1047382991');
  });

  it('sin cédula no se llama al servicio siquiera', async () => {
    const session = new Session();
    expect(await session.open('   ', 'jefe@archivo.edu.co')).toBe(false);
    expect(entrar).not.toHaveBeenCalled();
    expect(session.state).toBe('anonymous');
  });

  it('sin correo tampoco', async () => {
    const session = new Session();
    expect(await session.open('1047382991', '  ')).toBe(false);
    expect(entrar).not.toHaveBeenCalled();
  });

  it('un rechazo del servicio se cuenta con sus palabras', async () => {
    entrar.mockRejectedValue(new ApiError('No hay nadie dado de alta con esa cédula'));
    const session = new Session();

    expect(await session.open('999999999', 'nadie@archivo.edu.co')).toBe(false);

    expect(session.state).toBe('anonymous');
    expect(session.error).toBe('No hay nadie dado de alta con esa cédula');
  });

  it('un servicio apagado se distingue de un rechazo', async () => {
    // No es lo mismo «usted no está dado de alta» que «no contesta nadie», y
    // enseñar lo primero cuando pasa lo segundo manda al operador a pedir un
    // alta que ya tiene.
    entrar.mockRejectedValue(new TypeError('Failed to fetch'));
    const session = new Session();

    await session.open('1047382991', 'jefe@archivo.edu.co');

    expect(session.error).toMatch(/servicio/i);
  });

  it('cerrar borra la sesión y el almacenamiento', async () => {
    const session = new Session();
    await session.open('1047382991', 'jefe@archivo.edu.co');
    session.close();
    expect(session.state).toBe('anonymous');
    expect(session.cedula).toBeNull();
    expect(localStorage.getItem('resolutions.session')).toBeNull();
  });
});

describe('el perfil', () => {
  it('el administrador administra', async () => {
    const session = new Session();
    await session.open('1047382991', 'jefe@archivo.edu.co');
    expect(session.esAdministrador).toBe(true);
  });

  it('y descarga las planillas', async () => {
    const session = new Session();
    await session.open('1047382991', 'jefe@archivo.edu.co');
    expect(session.descargaPlanillas).toBe(true);
  });

  it('el técnico no descarga las planillas', async () => {
    entrar.mockResolvedValue(TECNICA);
    const session = new Session();
    await session.open('52814663', 'tecnica@archivo.edu.co');
    expect(session.perfil).toBe('tecnico');
    expect(session.descargaPlanillas).toBe(false);
  });

  it('ni administra', async () => {
    entrar.mockResolvedValue(TECNICA);
    const session = new Session();
    await session.open('52814663', 'tecnica@archivo.edu.co');
    expect(session.esAdministrador).toBe(false);
  });

  it('el de calidad tampoco descarga', async () => {
    entrar.mockResolvedValue({ ...TECNICA, perfil: 'calidad', perfil_label: 'Calidad' });
    const session = new Session();
    await session.open('39158204', 'calidad@archivo.edu.co');
    expect(session.descargaPlanillas).toBe(false);
  });

  it('sin sesión no se descarga nada', () => {
    // El valor por omisión niega. Un perfil desconocido que concediera sería
    // la forma de que la restricción no exista mientras carga la pantalla.
    expect(new Session().descargaPlanillas).toBe(false);
  });

  it('se dice cuando esta entrada fundó el archivo', async () => {
    entrar.mockResolvedValue({ ...JEFE, primer_administrador: true });
    const session = new Session();
    await session.open('1047382991', 'jefe@archivo.edu.co');
    expect(session.primerAdministrador).toBe(true);
  });

  it('y no se dice cuando no', async () => {
    const session = new Session();
    await session.open('1047382991', 'jefe@archivo.edu.co');
    expect(session.primerAdministrador).toBe(false);
  });
});

describe('inactividad', () => {
  it('una sesión guardada hace una hora vuelve como inactiva', () => {
    guardar(JEFE, Date.now() - IDLE_AFTER_MS - 1000);
    const session = new Session();
    const stop = session.start();
    expect(session.state).toBe('idle');
    expect(session.name).toBe('Ana Martínez');
    stop();
  });

  it('una sesión guardada hace un minuto vuelve activa', () => {
    guardar(JEFE, Date.now() - 60_000);
    const session = new Session();
    const stop = session.start();
    expect(session.state).toBe('active');
    stop();
  });

  it('reanudar no pide nada: no hay nada que desbloquear', async () => {
    const session = new Session();
    await session.open('1047382991', 'jefe@archivo.edu.co');
    session.state = 'idle';
    session.resume();
    expect(session.state).toBe('active');
    expect(session.name).toBe('Ana Martínez');
  });

  it('reanudar desde activa no hace nada', async () => {
    const session = new Session();
    await session.open('1047382991', 'jefe@archivo.edu.co');
    session.resume();
    expect(session.state).toBe('active');
  });

  it('tocar desde inactiva no reanuda sola', async () => {
    // Volver a la máquina no es lo mismo que decir «sigo siendo yo».
    const session = new Session();
    await session.open('1047382991', 'jefe@archivo.edu.co');
    session.state = 'idle';
    session.touch();
    expect(session.state).toBe('idle');
  });
});

describe('el perfil guardado se vuelve a preguntar', () => {
  it('al restaurar una sesión se le pregunta al servicio', async () => {
    // El administrador pudo haberle cambiado el perfil, o haberlo dado de baja,
    // desde la última vez que entró.
    guardar(JEFE, Date.now() - 60_000);
    const session = new Session();
    const stop = session.start();
    await vi.waitFor(() => expect(entrar).toHaveBeenCalledWith(JEFE.cedula, JEFE.correo));
    stop();
  });

  it('y el perfil que conteste sustituye al guardado', async () => {
    guardar(JEFE, Date.now() - 60_000);
    entrar.mockResolvedValue({ ...JEFE, perfil: 'calidad', perfil_label: 'Calidad' });
    const session = new Session();
    const stop = session.start();

    await vi.waitFor(() => expect(session.perfil).toBe('calidad'));
    expect(session.descargaPlanillas).toBe(false);
    stop();
  });

  it('a quien le dieron de baja se le cierra la sesión', async () => {
    guardar(JEFE, Date.now() - 60_000);
    entrar.mockRejectedValue(new ApiError('No hay nadie dado de alta con esa cédula'));
    const session = new Session();
    const stop = session.start();

    await vi.waitFor(() => expect(session.state).toBe('anonymous'));
    stop();
  });

  it('un fallo de red no cierra la sesión', async () => {
    // Dejaría al operador fuera cada vez que se reinicia el servicio, y lo
    // guardado sigue siendo lo último que el servicio dijo.
    guardar(JEFE, Date.now() - 60_000);
    entrar.mockRejectedValue(new TypeError('Failed to fetch'));
    const session = new Session();
    const stop = session.start();

    await vi.waitFor(() => expect(entrar).toHaveBeenCalled());
    expect(session.state).toBe('active');
    stop();
  });
});

describe('almacenamiento hostil', () => {
  it('un almacenamiento que lanza no impide entrar', async () => {
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('bloqueado');
      },
      setItem: () => {
        throw new Error('bloqueado');
      },
      removeItem: () => {
        throw new Error('bloqueado');
      }
    });

    const session = new Session();
    const stop = session.start();
    expect(session.state).toBe('anonymous');
    expect(await session.open('1047382991', 'jefe@archivo.edu.co')).toBe(true);
    expect(session.state).toBe('active');
    stop();
  });

  it('una sesión guardada corrupta se lee como que no hay sesión', () => {
    localStorage.setItem('resolutions.session', '{no es json');
    const session = new Session();
    const stop = session.start();
    expect(session.state).toBe('anonymous');
    stop();
  });

  it('una sesión guardada sin cédula no cuenta', () => {
    localStorage.setItem('resolutions.session', JSON.stringify({ operator: {}, lastSeen: 1 }));
    const session = new Session();
    const stop = session.start();
    expect(session.state).toBe('anonymous');
    stop();
  });

  it('una sesión de la versión anterior manda a la pantalla de entrada', () => {
    // Llevaba `name` y `station` y ninguna cédula. Arrancar con media sesión
    // sería peor que pedir que vuelva a entrar una vez.
    localStorage.setItem(
      'resolutions.session',
      JSON.stringify({ operator: { name: 'Ana', station: null, startedAt: 1 }, lastSeen: 1 })
    );
    const session = new Session();
    const stop = session.start();
    expect(session.state).toBe('anonymous');
    stop();
  });

  it('una sesión guardada sin perfil tampoco cuenta', () => {
    localStorage.setItem(
      'resolutions.session',
      JSON.stringify({ operator: { cedula: '1047382991' }, lastSeen: 1 })
    );
    const session = new Session();
    const stop = session.start();
    expect(session.state).toBe('anonymous');
    stop();
  });
});
