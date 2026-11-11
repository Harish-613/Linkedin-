import { createApp } from './app';
import { MemoryCache, RedisCache } from './cache';
import { Database } from './db';

const port = Number(process.env.PORT || 8787);
const db = Database.fromUrl(process.env.DATABASE_URL || 'postgresql://postgres@localhost:5432/linkedinpp');
const cache = process.env.REDIS_URL === 'off' ? new MemoryCache() : RedisCache.fromUrl(process.env.REDIS_URL || 'redis://localhost:6379');
const allowedOrigins = (process.env.ALLOWED_ORIGINS || '').split(',').filter(Boolean);

const server = createApp({ db, cache, allowedOrigins }).listen(port, () => {
  console.log(`LinkedIn++ API listening on http://localhost:${port}`);
});

async function shutdown() {
  server.close();
  await Promise.allSettled([db.close(), cache.close()]);
  process.exit(0);
}
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
