// Shape of GET /api/insights (server/src/insights.ts).

export interface PayRange {
  p25: number;
  p50: number;
  p75: number;
  n: number;
  sources: Record<string, number>;
  total_comp_p50?: number;
  family: string;
  seniority: string;
  exact: boolean;
}

export interface Insights {
  company: { id: number; name: string; domain: string | null; ticker: string | null };
  role: { title: string; family: string; seniority: string } | null;
  pay: PayRange | null;
  interview: {
    score: number;
    label: string;
    rationale: string;
    focus_areas?: string[];
    method: string;
    family: string;
  } | null;
  competitiveness: { score: number; label: string; factors: Record<string, number> } | null;
  hiring: { open_roles: number; new_roles_30d: number };
  financials: { revenue_usd: number | null; revenue_growth: number | null; fiscal_year: number | null } | null;
  funding: {
    total_usd: number | null;
    last_round_type: string | null;
    employees: { min: number; max: number | null } | null;
  } | null;
  tech: string[];
  updated_at: string | null;
}

export interface JobContext {
  company: string;
  title: string;
  jobId: string | null;
}

export type InsightsResult =
  | { ok: true; data: Insights }
  | { ok: false; reason: 'unknown_company' | 'api_unreachable' | 'error'; message?: string };

export interface InsightsRequest {
  type: 'insights';
  company: string;
  title: string;
}
