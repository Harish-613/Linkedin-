import { beforeEach, describe, expect, it, vi } from 'vitest';

const store: Record<string, unknown> = {};
vi.stubGlobal('chrome', {
  storage: { sync: { get: async (k: string) => ({ [k]: store[k] }), set: async (o: object) => Object.assign(store, o) } },
  runtime: {},
});

const { fetchInsights, apiBase } = await import('../src/background');

const ok = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));

describe('background fetchInsights', () => {
  beforeEach(() => {
    delete store.apiUrl;
  });

  it('uses the configured API URL and builds the query', async () => {
    store.apiUrl = 'https://api.example.com/';
    expect(await apiBase()).toBe('https://api.example.com');
    const f = vi.fn(() => ok({ company: { name: 'Stripe' } }));
    const r = await fetchInsights({ type: 'insights', company: 'Stripe', title: 'SWE & Infra' }, f as unknown as typeof fetch);
    expect(r).toEqual({ ok: true, data: { company: { name: 'Stripe' } } });
    expect(f).toHaveBeenCalledWith('https://api.example.com/api/insights?company=Stripe&title=SWE+%26+Infra');
  });

  it('caches answers but retries when the server was unreachable', async () => {
    const f = vi.fn(() => ok({ company: { name: 'Ramp' } }));
    await fetchInsights({ type: 'insights', company: 'Ramp', title: 'A' }, f as unknown as typeof fetch);
    await fetchInsights({ type: 'insights', company: 'Ramp', title: 'A' }, f as unknown as typeof fetch);
    expect(f).toHaveBeenCalledTimes(1);

    const down = vi.fn(() => Promise.reject(new TypeError('Failed to fetch')));
    const r1 = await fetchInsights({ type: 'insights', company: 'Figma', title: 'A' }, down as unknown as typeof fetch);
    expect(r1).toMatchObject({ ok: false, reason: 'api_unreachable' });
    const up = vi.fn(() => ok({}));
    await fetchInsights({ type: 'insights', company: 'Figma', title: 'A' }, up as unknown as typeof fetch);
    expect(up).toHaveBeenCalledTimes(1);
  });

  it('maps 404 and server errors', async () => {
    const nf = vi.fn(() => Promise.resolve(new Response('{}', { status: 404 })));
    expect(await fetchInsights({ type: 'insights', company: 'Nope', title: 'A' }, nf as unknown as typeof fetch))
      .toEqual({ ok: false, reason: 'unknown_company' });
    const err = vi.fn(() => Promise.resolve(new Response('{}', { status: 500 })));
    expect(await fetchInsights({ type: 'insights', company: 'Broken', title: 'A' }, err as unknown as typeof fetch))
      .toEqual({ ok: false, reason: 'error', message: 'API returned 500' });
  });
});
