export function money(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) {
    return '—';
  }
  const abs = Math.abs(n);
  if (abs >= 1e9) {
    return `$${(n / 1e9).toFixed(abs >= 1e10 ? 0 : 1)}B`;
  }
  if (abs >= 1e6) {
    return `$${(n / 1e6).toFixed(abs >= 1e7 ? 0 : 1)}M`;
  }
  if (abs >= 1e3) {
    return `$${Math.round(n / 1e3)}K`;
  }
  return `$${Math.round(n)}`;
}

export function pct(x: number | null | undefined): string {
  if (x === null || x === undefined) {
    return '—';
  }
  const v = Math.round(x * 100);
  return `${v > 0 ? '+' : ''}${v}%`;
}

export function humanize(key: string): string {
  return key.replace(/_/g, ' ').replace(/\bml\b/i, 'ML');
}

export function employees(e: { min: number; max: number | null } | null): string {
  if (!e) {
    return '—';
  }
  const f = (n: number) => (n >= 1000 ? `${Math.round(n / 100) / 10}K`.replace('.0K', 'K') : String(n));
  return e.max ? `${f(e.min)}–${f(e.max)}` : `${f(e.min)}+`;
}

export function roundType(t: string | null): string {
  if (!t) {
    return '';
  }
  return t
    .replace(/^series_/, 'Series ')
    .replace(/_/g, ' ')
    .replace(/\b([a-z])/g, (m) => m.toUpperCase());
}

/** 0–100 score -> 1–5 filled dots. */
export function dots(score: number, outOf = 5, max = 100): number {
  return Math.max(1, Math.min(outOf, Math.round((score / max) * outOf)));
}
