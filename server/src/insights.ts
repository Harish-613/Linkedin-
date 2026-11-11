import { CompanyRow, Interview, PayStats } from './db';
import { classifyTitle, familyChain } from './normalize';

/** A pay range needs at least this many data points before we show it. */
export const MIN_PAY_SAMPLES = 3;

export interface PayAnswer extends PayStats {
  family: string;
  seniority: string; // a seniority level or "all"
  exact: boolean; // true if it matches the job's own family and seniority
}

/**
 * Most specific pay range with enough data, trying in order:
 *   family+seniority, family overall, parent family+seniority, parent family overall.
 */
export function pickPay(pay: CompanyRow['pay'], family: string, seniority: string): PayAnswer | null {
  if (!pay) {
    return null;
  }
  const chain = familyChain(family);
  for (const fam of chain) {
    for (const level of [seniority, 'all']) {
      const stats = pay[fam]?.[level];
      if (stats && stats.n >= MIN_PAY_SAMPLES) {
        return { ...stats, family: fam, seniority: level, exact: fam === family && level === seniority };
      }
    }
  }
  return null;
}

export function pickInterview(interview: CompanyRow['interview'], family: string): (Interview & { family: string }) | null {
  if (!interview) {
    return null;
  }
  for (const fam of familyChain(family)) {
    if (interview[fam]) {
      return { ...interview[fam], family: fam };
    }
  }
  return null;
}

const num = (v: string | null) => (v === null ? null : Number(v));

/** Shape the API response for one job: the company plus what applies to this title. */
export function buildInsights(
  company: CompanyRow,
  title: string | undefined,
  tech: { technology: string; category: string | null }[],
) {
  const role = title ? { title, ...classifyTitle(title) } : null;
  return {
    company: { id: company.id, name: company.name, domain: company.domain, ticker: company.ticker },
    role,
    pay: role ? pickPay(company.pay, role.family, role.seniority) : null,
    interview: role ? pickInterview(company.interview, role.family) : null,
    competitiveness: company.competitiveness,
    hiring: { open_roles: company.open_roles ?? 0, new_roles_30d: company.new_roles_30d ?? 0 },
    financials:
      company.revenue_usd !== null
        ? { revenue_usd: num(company.revenue_usd), revenue_growth: num(company.revenue_growth), fiscal_year: company.fiscal_year }
        : null,
    funding:
      company.funding_usd !== null || company.employee_min !== null
        ? {
            total_usd: num(company.funding_usd),
            last_round_type: company.last_round_type,
            employees: company.employee_min !== null ? { min: company.employee_min, max: company.employee_max } : null,
          }
        : null,
    tech: tech.map((t) => t.technology),
    updated_at: company.computed_at,
  };
}
