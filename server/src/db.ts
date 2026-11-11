import { Pool } from 'pg';
import { normalizeCompany, normalizeDomain } from './normalize';

export interface CompanyRow {
  id: number;
  name: string;
  domain: string | null;
  ticker: string | null;
  open_roles: number | null;
  new_roles_30d: number | null;
  pay: Record<string, Record<string, PayStats>> | null;
  competitiveness: { score: number; label: string; factors: Record<string, number> } | null;
  interview: Record<string, Interview> | null;
  computed_at: Date | null;
  revenue_usd: string | null;
  revenue_growth: string | null;
  fiscal_year: number | null;
  funding_usd: string | null;
  last_round_type: string | null;
  employee_min: number | null;
  employee_max: number | null;
  founded_on: Date | null;
}

export interface PayStats {
  p25: number;
  p50: number;
  p75: number;
  n: number;
  sources: Record<string, number>;
  total_comp_p50?: number;
}

export interface Interview {
  score: number;
  label: string;
  rationale: string;
  focus_areas?: string[];
  method: string;
}

export class Database {
  constructor(private readonly pool: Pool) {}

  static fromUrl(url: string): Database {
    const pool = new Pool({ connectionString: url, max: 10 });
    // An idle client can error (e.g. Postgres restarts); without a listener that would crash the process.
    pool.on('error', (err) => console.warn(`postgres idle client error: ${err.message}`));
    return new Database(pool);
  }

  /** Same order as the pipeline: domain first (exact), then any known name. */
  async findCompanyId(name?: string, domain?: string): Promise<number | null> {
    const d = normalizeDomain(domain);
    if (d) {
      const r = await this.pool.query('SELECT id FROM companies WHERE domain = $1', [d]);
      if (r.rows[0]) {
        return r.rows[0].id;
      }
    }
    if (name) {
      const r = await this.pool.query('SELECT company_id FROM company_aliases WHERE alias = $1', [normalizeCompany(name)]);
      if (r.rows[0]) {
        return r.rows[0].company_id;
      }
    }
    return null;
  }

  async getCompany(id: number): Promise<CompanyRow | null> {
    const r = await this.pool.query(
      `SELECT c.id, c.name, c.domain, c.ticker,
              i.open_roles, i.new_roles_30d, i.pay, i.competitiveness, i.interview, i.computed_at,
              s.revenue_usd, s.revenue_growth, s.fiscal_year,
              f.total_usd AS funding_usd, f.last_round_type, f.employee_min, f.employee_max, f.founded_on
       FROM companies c
       LEFT JOIN company_insights i ON i.company_id = c.id
       LEFT JOIN sec_financials s ON s.company_id = c.id
       LEFT JOIN funding f ON f.company_id = c.id
       WHERE c.id = $1`,
      [id],
    );
    return r.rows[0] ?? null;
  }

  async getTech(id: number, limit = 12): Promise<{ technology: string; category: string | null }[]> {
    const r = await this.pool.query(
      `SELECT technology, category FROM tech_stack WHERE company_id = $1 AND live
       ORDER BY (technology LIKE 'category:%'), technology LIMIT $2`,
      [id, limit],
    );
    return r.rows.map((t) => ({ technology: t.technology.replace(/^category:/, ''), category: t.category }));
  }

  async search(prefix: string, limit = 10): Promise<{ id: number; name: string }[]> {
    const r = await this.pool.query(
      `SELECT DISTINCT ON (c.id) c.id, c.name FROM company_aliases a JOIN companies c ON c.id = a.company_id
       WHERE a.alias LIKE $1 ORDER BY c.id LIMIT $2`,
      [normalizeCompany(prefix).replace(/[%_]/g, '') + '%', limit],
    );
    return r.rows;
  }

  async ping(): Promise<void> {
    await this.pool.query('SELECT 1');
  }

  async close(): Promise<void> {
    await this.pool.end();
  }
}
