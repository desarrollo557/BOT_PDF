import { beforeEach, describe, expect, it, vi } from 'vitest';
import { IDLE_AFTER_MS, Session } from './session.svelte';

/**
 * The session machine, transition by transition.
 *
 * There is no password anywhere in here, and that is the point being pinned:
 * `idle` is a checkpoint, not a lock, and resuming from it asks for nothing.
 */

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
 * The session listens to the window for activity. Stubbing it rather than
 * pulling in a whole DOM keeps these tests about the machine, which is what is
 * worth pinning here.
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

beforeEach(() => {
  vi.stubGlobal('localStorage', storage());
  vi.stubGlobal('window', fakeWindow());
});

describe('transiciones', () => {
  it('empieza sin sesión', () => {
    expect(new Session().state).toBe('anonymous');
  });

  it('abrir una sesión la deja activa y con nombre', () => {
    const session = new Session();
    expect(session.open('Ana Martínez', 'Archivo central')).toBe(true);
    expect(session.state).toBe('active');
    expect(session.name).toBe('Ana Martínez');
    expect(session.operator?.station).toBe('Archivo central');
  });

  it('un nombre en blanco no abre nada', () => {
    const session = new Session();
    expect(session.open('   ')).toBe(false);
    expect(session.state).toBe('anonymous');
  });

  it('el nombre se recorta', () => {
    const session = new Session();
    session.open('  Ana  ');
    expect(session.name).toBe('Ana');
  });

  it('un puesto vacío queda en nulo, no en cadena vacía', () => {
    const session = new Session();
    session.open('Ana', '   ');
    expect(session.operator?.station).toBeNull();
  });

  it('cerrar borra el nombre y el almacenamiento', () => {
    const session = new Session();
    session.open('Ana');
    session.close();
    expect(session.state).toBe('anonymous');
    expect(session.name).toBeNull();
    expect(localStorage.getItem('resolutions.session')).toBeNull();
  });
});

describe('inactividad', () => {
  it('una sesión guardada hace una hora vuelve como inactiva', () => {
    localStorage.setItem(
      'resolutions.session',
      JSON.stringify({
        operator: { name: 'Ana', station: null, startedAt: Date.now() - IDLE_AFTER_MS * 2 },
        lastSeen: Date.now() - IDLE_AFTER_MS - 1000
      })
    );
    const session = new Session();
    const stop = session.start();
    expect(session.state).toBe('idle');
    expect(session.name).toBe('Ana');
    stop();
  });

  it('una sesión guardada hace un minuto vuelve activa', () => {
    localStorage.setItem(
      'resolutions.session',
      JSON.stringify({
        operator: { name: 'Ana', station: null, startedAt: Date.now() - 60_000 },
        lastSeen: Date.now() - 60_000
      })
    );
    const session = new Session();
    const stop = session.start();
    expect(session.state).toBe('active');
    stop();
  });

  it('reanudar no pide nada: no hay nada que desbloquear', () => {
    const session = new Session();
    session.open('Ana');
    session.state = 'idle';
    session.resume();
    expect(session.state).toBe('active');
    expect(session.name).toBe('Ana');
  });

  it('reanudar desde activa no hace nada', () => {
    const session = new Session();
    session.open('Ana');
    session.resume();
    expect(session.state).toBe('active');
  });

  it('tocar desde inactiva no reanuda sola', () => {
    // Coming back to the machine is not the same as saying "it is still me".
    const session = new Session();
    session.open('Ana');
    session.state = 'idle';
    session.touch();
    expect(session.state).toBe('idle');
  });
});

describe('almacenamiento hostil', () => {
  it('un almacenamiento que lanza no impide entrar', () => {
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
    expect(session.open('Ana')).toBe(true);
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

  it('una sesión guardada sin nombre no cuenta', () => {
    localStorage.setItem('resolutions.session', JSON.stringify({ operator: {}, lastSeen: 1 }));
    const session = new Session();
    const stop = session.start();
    expect(session.state).toBe('anonymous');
    stop();
  });
});
