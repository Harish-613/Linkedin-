import * as fs from 'fs';
import * as path from 'path';
import { Client, Pool } from 'pg';
import Redis from 'ioredis';
import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { createApp } from '../src/app';
import { MemoryCache, RedisCache } from '../src/cache';
import { Database } from '../src/db';
import { classifyTitle, normalizeCompany } from '../src/normalize';

const ADMIN_URL = process.env.TEST_ADMIN_DATABASE_URL || 'postgresql://postgres@localhost:5432/postgres';
const DB_NAME = `lpp_api_test_${process.pid}`;
const DB_URL = ADMIN_URL.replace(/\/[^/]*$/, `/${DB_NAME}`);
const ROOT = path.resolve(__dirname, '..', '..');

// ---------------------------------------------------------------- shared rules parity

describe('normalize (shared/test_cases.json, also run by the Python tests)', () => {
  const cases = JSON.parse(fs.readFileSync(path.join(ROOT, 'shared', 'test_cases.json'), 'utf8'));
  it.each(cases.companies)('company %s -> %s', (raw: string, expected: string) => {
    expect(normalizeCompany(raw)).toBe(expected);
  });
  it.each(cases.titles)('title %s', (title: string, family: string, seniority: string) => {
    expect(classifyTitle(title)).toEqual({ family, seniority });
  });
});

// ---------------------------------------------------------------- API against real Postgres

const pay = (p50: number, n: number, sources: Record<string, number>) => ({ p25: p50 - 20000, p50, p75: p50 + 20000, n, sources });

async function seed(pool: Pool) {
  await pool.query(fs.readFileSync(path.join(ROOT, 'db', 'schema.sql'), 'utf8'));
  await pool.query(`INSERT INTO companies (id, name, normalized_name, domain, cik, ticker) VALUES
      (1, 'Coinbase Global, Inc.', 'coinbase', 'coinbase.com', 1679788, 'COIN'),
      (2, 'Ramp', 'ramp', 'ramp.com', NULL, NULL),
      (3, 'Tiny Startup', 'tiny startup', NULL, NULL, NULL)`);
  await pool.query(`INSERT INTO company_aliases (alias, company_id) VALUES
      ('coinbase', 1), ('coin', 1), ('ramp', 2), ('tiny startup', 3)`);
  await pool.query(`INSERT INTO sec_financials (company_id, fiscal_year, revenue_usd, revenue_growth) VALUES (1, 2024, 6564028000, 1.11)`);
  await pool.query(`INSERT INTO funding (company_id, total_usd, last_round_type, employee_min, employee_max) VALUES
      (2, 1900000000, 'series_e', 1001, 5000)`);
  await pool.query(`INSERT INTO tech_stack (company_id, technology, category) VALUES
      (2, 'React', 'JavaScript Library'), (2, 'category:Analytics', 'analytics'), (2, 'Cloudflare', 'CDN')`);
  await pool.query(
    `INSERT INTO company_insights (company_id, open_roles, new_roles_30d, pay, competitiveness, interview) VALUES
      (1, 120, 30, $1, $2, $3), (2, 45, 20, $4, NULL, $5), (3, 1, 0, $6, NULL, '{}')`,
    [
      JSON.stringify({
        software_engineering: { new_grad: pay(150000, 12, { postings: 12 }), all: pay(190000, 80, { postings: 60, levels: 20 }) },
        machine_learning: { senior: pay(240000, 2, { postings: 2 }), all: pay(235000, 5, { postings: 5 }) },
      }),
      JSON.stringify({ score: 82, label: 'Very competitive', factors: { pay: 0.9, scale: 0.95 } }),
      JSON.stringify({
        software_engineering: { score: 3.8, label: 'Hard', rationale: 'Algorithms-heavy', method: 'heuristic' },
      }),
      JSON.stringify({
        backend: { all: pay(215000, 1, { postings: 1 }) },
        software_engineering: { senior: pay(205000, 4, { levels: 4 }), all: pay(185000, 9, { levels: 9 }) },
      }),
      JSON.stringify({ backend: { score: 3.4, label: 'Hard', rationale: 'Coding + system design', method: 'llm:gpt-4o-mini' } }),
      JSON.stringify({ software_engineering: { all: pay(120000, 1, { postings: 1 }) } }),
    ],
  );
}

describe('API', () => {
  let admin: Client;
  let db: Database;
  let app: ReturnType<typeof createApp>;

  beforeAll(async () => {
    admin = new Client({ connectionString: ADMIN_URL });
    await admin.connect();
    await admin.query(`DROP DATABASE IF EXISTS ${DB_NAME} WITH (FORCE)`);
    await admin.query(`CREATE DATABASE ${DB_NAME}`);
    const pool = new Pool({ connectionString: DB_URL });
    await seed(pool);
    await pool.end();
    db = Database.fromUrl(DB_URL);
    app = createApp({ db, cache: new MemoryCache(), rateLimitPerMinute: 1000 });
  });

  afterAll(async () => {
    await db.close();
    await admin.query(`DROP DATABASE IF EXISTS ${DB_NAME} WITH (FORCE)`);
    await admin.end();
  });

  it('answers for the name LinkedIn shows, matched to the SEC entity', async () => {
    const res = await request(app).get('/api/insights').query({ company: 'Coinbase', title: 'Software Engineer, New Grad (2027)' });
    expect(res.status).toBe(200);
    expect(res.body.company).toMatchObject({ id: 1, name: 'Coinbase Global, Inc.', ticker: 'COIN' });
    expect(res.body.role).toEqual({ title: 'Software Engineer, New Grad (2027)', family: 'software_engineering', seniority: 'new_grad' });
    expect(res.body.pay).toMatchObject({ p50: 150000, n: 12, family: 'software_engineering', seniority: 'new_grad', exact: true });
    expect(res.body.interview).toMatchObject({ score: 3.8, label: 'Hard', family: 'software_engineering' });
    expect(res.body.competitiveness.score).toBe(82);
    expect(res.body.financials).toEqual({ revenue_usd: 6564028000, revenue_growth: 1.11, fiscal_year: 2024 });
    expect(res.body.hiring).toEqual({ open_roles: 120, new_roles_30d: 30 });
  });

  it('falls back to a broader pay range when the exact one is too thin', async () => {
    // senior ML has n=2 (< 3) -> ML overall (n=5)
    const ml = await request(app).get('/api/insights').query({ company: 'coinbase', title: 'Senior Machine Learning Engineer' });
    expect(ml.body.pay).toMatchObject({ family: 'machine_learning', seniority: 'all', n: 5, exact: false });
    // backend has n=1 -> parent family software_engineering, senior (n=4)
    const be = await request(app).get('/api/insights').query({ company: 'Ramp', title: 'Senior Backend Engineer' });
    expect(be.body.pay).toMatchObject({ family: 'software_engineering', seniority: 'senior', p50: 205000, exact: false });
    expect(be.body.interview).toMatchObject({ family: 'backend', method: 'llm:gpt-4o-mini' });
  });

  it('uses specific families as evidence for a generic title', async () => {
    // Ramp has interview data only for "backend"; a plain "Software Engineer" lookup should still get it.
    const res = await request(app).get('/api/insights').query({ company: 'Ramp', title: 'Software Engineer' });
    expect(res.body.interview).toMatchObject({ family: 'backend', score: 3.4 });
    expect(res.body.pay).toMatchObject({ family: 'software_engineering', seniority: 'all', exact: false });
  });

  it('familyChain order: own, parent, children', async () => {
    const { familyChain } = await import('../src/normalize');
    expect(familyChain('backend')).toEqual(['backend', 'software_engineering']);
    expect(familyChain('software_engineering').slice(0, 3)).toEqual(['software_engineering', 'backend', 'frontend']);
    expect(familyChain('chef')).toEqual(['chef']);
  });

  it('returns no pay rather than a range built on one data point', async () => {
    const res = await request(app).get('/api/insights').query({ company: 'Tiny Startup', title: 'Software Engineer' });
    expect(res.status).toBe(200);
    expect(res.body.pay).toBeNull();
  });

  it('looks up by domain and returns funding and tech', async () => {
    const res = await request(app).get('/api/insights').query({ domain: 'https://www.ramp.com/careers' });
    expect(res.body.company.name).toBe('Ramp');
    expect(res.body.role).toBeNull();
    expect(res.body.funding).toEqual({ total_usd: 1900000000, last_round_type: 'series_e', employees: { min: 1001, max: 5000 } });
    expect(res.body.tech).toEqual(['Cloudflare', 'React', 'Analytics']); // real names before category counts
  });

  it('404s unknown companies and caches both hits and misses', async () => {
    const first = await request(app).get('/api/insights').query({ company: 'Nonexistent Corp' });
    expect(first.status).toBe(404);
    expect(first.headers['x-cache']).toBe('miss');
    const second = await request(app).get('/api/insights').query({ company: 'Nonexistent Corp' });
    expect(second.status).toBe(404);
    expect(second.headers['x-cache']).toBe('hit');
    const hit = await request(app).get('/api/insights').query({ company: 'Coinbase', title: 'Software Engineer, New Grad (2027)' });
    expect(hit.headers['x-cache']).toBe('hit');
  });

  it('validates input', async () => {
    expect((await request(app).get('/api/insights')).status).toBe(400);
    expect((await request(app).get('/api/insights').query({ company: 'x'.repeat(201) })).status).toBe(400);
  });

  it('allows chrome-extension origins only', async () => {
    const ok = await request(app).get('/api/insights').set('Origin', 'chrome-extension://abcdef').query({ company: 'Ramp' });
    expect(ok.headers['access-control-allow-origin']).toBe('chrome-extension://abcdef');
    const bad = await request(app).get('/api/insights').set('Origin', 'https://evil.example').query({ company: 'Ramp' });
    expect(bad.headers['access-control-allow-origin']).toBeUndefined();
  });

  it('rate limits per client', async () => {
    const limited = createApp({ db, cache: new MemoryCache(), rateLimitPerMinute: 2 });
    await request(limited).get('/api/insights').query({ company: 'Ramp' });
    await request(limited).get('/api/insights').query({ company: 'Ramp' });
    const third = await request(limited).get('/api/insights').query({ company: 'Ramp' });
    expect(third.status).toBe(429);
    expect(third.headers['retry-after']).toBeDefined();
  });

  it('health and company search', async () => {
    expect((await request(app).get('/health')).body).toEqual({ ok: true });
    const res = await request(app).get('/api/companies').query({ q: 'coin' });
    expect(res.body).toEqual([{ id: 1, name: 'Coinbase Global, Inc.' }]);
  });
});

// ---------------------------------------------------------------- Redis

describe('RedisCache', () => {
  it('round-trips through real Redis', async () => {
    const redis = new Redis(process.env.REDIS_URL || 'redis://localhost:6379', { lazyConnect: true, maxRetriesPerRequest: 1 });
    try {
      await redis.connect();
    } catch {
      return; // no Redis available locally; CI provides one
    }
    const cache = new RedisCache(redis);
    await cache.set('lpp:test', { a: 1 }, 5);
    expect(await cache.get('lpp:test')).toEqual({ a: 1 });
    expect(await redis.ttl('lpp:test')).toBeGreaterThan(0);
    await cache.close();
  });

  it('serves without a cache when Redis is down', async () => {
    const cache = RedisCache.fromUrl('redis://localhost:1');
    await new Promise((r) => setTimeout(r, 200));
    await cache.set('k', 1, 5);
    expect(await cache.get('k')).toBeNull();
    await cache.close();
  });
});
