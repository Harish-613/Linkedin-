import cors from 'cors';
import express, { NextFunction, Request, Response } from 'express';
import { Cache } from './cache';
import { Database } from './db';
import { buildInsights } from './insights';
import { normalizeCompany } from './normalize';

export const CACHE_TTL_SECONDS = 6 * 60 * 60; // insights are recomputed by the pipeline, not per request
const NEGATIVE_TTL_SECONDS = 30 * 60; // remember "unknown company" too, so LinkedIn browsing doesn't hammer Postgres

export interface AppOptions {
  db: Database;
  cache: Cache;
  allowedOrigins?: string[]; // extra origins besides chrome-extension://
  rateLimitPerMinute?: number;
}

/** Fixed-window per-IP limiter; plenty for one extension user, protects a public deployment. */
function rateLimiter(perMinute: number) {
  const hits = new Map<string, { count: number; reset: number }>();
  return (req: Request, res: Response, next: NextFunction) => {
    const key = req.ip ?? 'unknown';
    const now = Date.now();
    const entry = hits.get(key);
    if (!entry || entry.reset < now) {
      hits.set(key, { count: 1, reset: now + 60_000 });
      return next();
    }
    if (++entry.count > perMinute) {
      res.setHeader('Retry-After', Math.ceil((entry.reset - now) / 1000));
      return res.status(429).json({ error: 'rate_limited' });
    }
    next();
  };
}

export function createApp({ db, cache, allowedOrigins = [], rateLimitPerMinute = 120 }: AppOptions) {
  const app = express();
  app.disable('x-powered-by');
  app.use(
    cors({
      origin: (origin, cb) => cb(null, !origin || origin.startsWith('chrome-extension://') || allowedOrigins.includes(origin)),
    }),
  );

  app.get('/health', async (_req, res) => {
    try {
      await db.ping();
      res.json({ ok: true });
    } catch {
      res.status(503).json({ ok: false });
    }
  });

  app.use('/api', rateLimiter(rateLimitPerMinute));

  // GET /api/insights?company=Stripe&title=Software%20Engineer&domain=stripe.com
  app.get('/api/insights', async (req, res, next) => {
    try {
      const company = String(req.query.company ?? '').trim();
      const domain = String(req.query.domain ?? '').trim() || undefined;
      const title = String(req.query.title ?? '').trim() || undefined;
      if (!company && !domain) {
        return res.status(400).json({ error: 'company or domain is required' });
      }
      if (company.length > 200 || (title?.length ?? 0) > 300) {
        return res.status(400).json({ error: 'input too long' });
      }

      const key = `insights:v1:${normalizeCompany(company)}:${domain ?? ''}:${(title ?? '').toLowerCase()}`;
      const cached = await cache.get<{ status: number; body: unknown }>(key);
      if (cached) {
        res.setHeader('X-Cache', 'hit');
        return res.status(cached.status).json(cached.body);
      }
      res.setHeader('X-Cache', 'miss');

      const id = await db.findCompanyId(company, domain);
      if (id === null) {
        const body = { error: 'unknown_company', company };
        await cache.set(key, { status: 404, body }, NEGATIVE_TTL_SECONDS);
        return res.status(404).json(body);
      }
      const [row, tech] = await Promise.all([db.getCompany(id), db.getTech(id)]);
      const body = buildInsights(row!, title, tech);
      await cache.set(key, { status: 200, body }, CACHE_TTL_SECONDS);
      res.json(body);
    } catch (err) {
      next(err);
    }
  });

  // GET /api/companies?q=str  (autocomplete, used by the extension's options page)
  app.get('/api/companies', async (req, res, next) => {
    try {
      const q = String(req.query.q ?? '').trim();
      if (q.length < 2) {
        return res.json([]);
      }
      res.json(await db.search(q));
    } catch (err) {
      next(err);
    }
  });

  app.use((err: Error, _req: Request, res: Response, _next: NextFunction) => {
    console.error(err);
    res.status(500).json({ error: 'internal_error' });
  });

  return app;
}
