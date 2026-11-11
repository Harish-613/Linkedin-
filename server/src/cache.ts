import Redis from 'ioredis';

export interface Cache {
  get<T>(key: string): Promise<T | null>;
  set(key: string, value: unknown, ttlSeconds: number): Promise<void>;
  close(): Promise<void>;
}

/** Redis-backed cache that degrades to "no cache" if Redis is down, so the API keeps serving. */
export class RedisCache implements Cache {
  private healthy = true;

  constructor(private readonly redis: Redis, private readonly log: (msg: string) => void = console.warn) {
    redis.on('error', (err) => {
      if (this.healthy) {
        this.log(`redis unavailable, serving without cache: ${err.message}`);
      }
      this.healthy = false;
    });
    redis.on('ready', () => (this.healthy = true));
  }

  static fromUrl(url: string): RedisCache {
    return new RedisCache(new Redis(url, { maxRetriesPerRequest: 1, enableOfflineQueue: false, lazyConnect: false }));
  }

  async get<T>(key: string): Promise<T | null> {
    if (!this.healthy) {
      return null;
    }
    try {
      const raw = await this.redis.get(key);
      return raw ? (JSON.parse(raw) as T) : null;
    } catch {
      return null;
    }
  }

  async set(key: string, value: unknown, ttlSeconds: number): Promise<void> {
    if (!this.healthy) {
      return;
    }
    try {
      await this.redis.set(key, JSON.stringify(value), 'EX', ttlSeconds);
    } catch {
      /* cache is best-effort */
    }
  }

  async close(): Promise<void> {
    this.redis.disconnect();
  }
}

/** In-process cache for tests and local runs without Redis. */
export class MemoryCache implements Cache {
  private store = new Map<string, { value: string; expires: number }>();

  async get<T>(key: string): Promise<T | null> {
    const hit = this.store.get(key);
    if (!hit || hit.expires < Date.now()) {
      return null;
    }
    return JSON.parse(hit.value) as T;
  }

  async set(key: string, value: unknown, ttlSeconds: number): Promise<void> {
    this.store.set(key, { value: JSON.stringify(value), expires: Date.now() + ttlSeconds * 1000 });
  }

  async close(): Promise<void> {
    this.store.clear();
  }
}
