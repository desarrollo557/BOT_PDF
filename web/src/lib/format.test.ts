import { describe, expect, it } from 'vitest';
import { formatBytes, formatDuration } from './format';

/**
 * Human units. Pinned because they are shown on four different screens, and the
 * same batch reading 1.2 GB in one place and 1,288 MB in another is exactly the
 * kind of inconsistency nobody reports and everybody distrusts.
 */

describe('formatBytes', () => {
  it('cuenta bytes sin decimales', () => {
    expect(formatBytes(512)).toBe('512 B');
  });

  it('sube de unidad al pasar 1024', () => {
    expect(formatBytes(1024)).toBe('1.00 KB');
    expect(formatBytes(1024 * 1024)).toBe('1.00 MB');
    expect(formatBytes(1024 ** 3)).toBe('1.00 GB');
  });

  it('reduce decimales a medida que crece el número', () => {
    expect(formatBytes(1024 * 15)).toBe('15.0 KB');
    expect(formatBytes(1024 * 150)).toBe('150 KB');
  });

  it('el peso real de los PDF del usuario', () => {
    expect(formatBytes(109_419_640)).toBe('104 MB');
    expect(formatBytes(192_570_700)).toBe('184 MB');
  });

  it('cero y valores imposibles no rompen', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(-5)).toBe('0 B');
    expect(formatBytes(NaN)).toBe('0 B');
  });
});

describe('formatDuration', () => {
  it('segundos con un decimal por debajo de diez', () => {
    expect(formatDuration(6.14)).toBe('6.1 s');
  });

  it('segundos redondos por encima de diez', () => {
    expect(formatDuration(42.6)).toBe('43 s');
  });

  it('minutos con segundos a dos cifras', () => {
    expect(formatDuration(252)).toBe('4 min 12 s');
    expect(formatDuration(305)).toBe('5 min 05 s');
  });

  it('horas para una corrida larga', () => {
    expect(formatDuration(3600 * 2 + 60 * 7)).toBe('2 h 07 min');
  });

  it('un valor imposible se dice, no se inventa', () => {
    expect(formatDuration(NaN)).toBe('—');
    expect(formatDuration(-1)).toBe('—');
  });
});
