// TypeScript port of pipeline/lpp/normalize.py. Both read shared/rules.json, and
// shared/test_cases.json is checked by both test suites so they can't drift apart.
import * as fs from 'fs';
import * as path from 'path';

interface Rules {
  company_suffixes: string[];
  role_families: { family: string; patterns: string[] }[];
  seniority: { level: string; patterns: string[] }[];
  family_fallbacks: Record<string, string>;
}

const RULES_PATH = process.env.LPP_RULES_PATH || path.resolve(__dirname, '..', '..', 'shared', 'rules.json');
const rules: Rules = JSON.parse(fs.readFileSync(RULES_PATH, 'utf8'));
const suffixes = new Set(rules.company_suffixes);
const families = rules.role_families.map((r) => ({ family: r.family, patterns: r.patterns.map((p) => new RegExp(p)) }));
const levels = rules.seniority.map((r) => ({ level: r.level, patterns: r.patterns.map((p) => new RegExp(p)) }));

export function normalizeCompany(name: string): string {
  let s = name.normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[^\x00-\x7f]/g, '').toLowerCase();
  s = s.replace(/&amp;/g, '&').replace(/\./g, '');
  s = s.replace(/[^a-z0-9& ]+/g, ' ');
  const words = s.split(/\s+/).filter(Boolean);
  while (words.length > 1 && suffixes.has(words[words.length - 1])) {
    words.pop();
  }
  if (words.length > 1 && words[0] === 'the') {
    words.shift();
  }
  return words.join(' ');
}

export function normalizeDomain(input?: string | null): string | null {
  if (!input) {
    return null;
  }
  let d = input.trim().toLowerCase().replace(/^[a-z]+:\/\//, '');
  d = d.split('/')[0].split('?')[0].replace(/^www\./, '');
  return d || null;
}

function cleanTitle(title: string): string {
  let t = title.toLowerCase();
  t = t.replace(/\(.*?\)|\[.*?\]/g, ' ');
  t = t.replace(/[,/|–—-]+\s*(remote|hybrid|on-?site|us|usa|united states).*$/, ' ');
  return t.replace(/\s+/g, ' ').trim();
}

export function classifyTitle(title: string): { family: string; seniority: string } {
  const t = cleanTitle(title);
  const family = families.find((f) => f.patterns.some((p) => p.test(t)))?.family ?? 'other';
  const seniority = levels.find((l) => l.patterns.some((p) => p.test(t)))!.level;
  return { family, seniority };
}

/**
 * Role families to try for a job, best evidence first:
 *   the job's own family -> its parent (backend -> software_engineering)
 *   -> its children (software_engineering -> backend, frontend, ...).
 * Children matter for generic titles: a company whose postings are all
 * "Backend Engineer" still says a lot about a "Software Engineer" role there.
 */
export function familyChain(family: string): string[] {
  const chain = [family];
  const parent = rules.family_fallbacks[family];
  if (parent && parent !== family && !parent.startsWith('_')) {
    chain.push(parent);
  }
  for (const [child, p] of Object.entries(rules.family_fallbacks)) {
    if (p === family && !child.startsWith('_') && !chain.includes(child)) {
      chain.push(child);
    }
  }
  return chain;
}
