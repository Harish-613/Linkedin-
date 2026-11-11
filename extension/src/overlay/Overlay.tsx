import { useState } from 'react';
import type { Insights, InsightsResult } from '../types';
import { dots, employees, humanize, money, pct, roundType } from './format';

const FACTOR_NAMES: Record<string, string> = {
  pay: 'Pay vs. market',
  scale: 'Company size',
  scarcity: 'Few openings per employee',
  momentum: 'Slow hiring pace',
};

function Meter({ value, max = 5 }: { value: number; max?: number }) {
  return (
    <span className="meter" aria-hidden="true">
      {Array.from({ length: max }, (_, i) => (
        <span key={i} className={i < Math.round(value) ? 'dot on' : 'dot'} />
      ))}
    </span>
  );
}

function PaySection({ data }: { data: Insights }) {
  const pay = data.pay;
  if (!pay) {
    return (
      <section>
        <h3>Pay range</h3>
        <p className="muted">Not enough salary data for this role yet.</p>
      </section>
    );
  }
  const sources = Object.entries(pay.sources)
    .map(([k, v]) => `${v} ${k === 'levels' ? 'Levels.fyi report' : 'posted range'}${v === 1 ? '' : 's'}`)
    .join(' · ');
  const scope = pay.exact
    ? null
    : `Based on ${humanize(pay.family)}${pay.seniority === 'all' ? ' (all levels)' : `, ${humanize(pay.seniority)}`} at this company`;
  return (
    <section>
      <h3>Pay range <span className="tag">base</span></h3>
      <div className="pay">
        <span className="big">{money(pay.p25)}</span>
        <span className="dash">–</span>
        <span className="big">{money(pay.p75)}</span>
        <span className="median">median {money(pay.p50)}</span>
      </div>
      {pay.total_comp_p50 ? <p className="note">Total comp median {money(pay.total_comp_p50)}</p> : null}
      {scope ? <p className="note">{scope}</p> : null}
      <p className="muted small">{sources}</p>
    </section>
  );
}

function InterviewSection({ data }: { data: Insights }) {
  const iv = data.interview;
  return (
    <section>
      <h3>Interview difficulty <span className="tag">estimate</span></h3>
      {iv ? (
        <>
          <div className="row">
            <Meter value={iv.score} />
            <strong>{iv.label}</strong>
            <span className="muted">{iv.score.toFixed(1)} / 5</span>
          </div>
          <p className="note">{iv.rationale}</p>
          {iv.focus_areas?.length ? (
            <div className="chips">{iv.focus_areas.map((f) => <span key={f} className="chip">{f}</span>)}</div>
          ) : null}
          <p className="muted small">
            From this company&apos;s {humanize(iv.family)} job requirements
            {iv.method.startsWith('llm') ? ', summarized by an LLM' : ''}
          </p>
        </>
      ) : (
        <p className="muted">No postings in this role family to estimate from.</p>
      )}
    </section>
  );
}

function CompetitivenessSection({ data }: { data: Insights }) {
  const c = data.competitiveness;
  const [open, setOpen] = useState(false);
  return (
    <section>
      <h3>Hiring competitiveness</h3>
      {c ? (
        <>
          <div className="row">
            <Meter value={dots(c.score)} />
            <strong>{c.label}</strong>
            <span className="muted">{c.score} / 100</span>
            <button className="link" onClick={() => setOpen(!open)} aria-expanded={open}>
              {open ? 'hide' : 'why?'}
            </button>
          </div>
          {open ? (
            <ul className="factors">
              {Object.entries(c.factors).map(([k, v]) => (
                <li key={k}>
                  <span>{FACTOR_NAMES[k] ?? humanize(k)}</span>
                  <span className="bar"><span style={{ width: `${Math.round(v * 100)}%` }} /></span>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : (
        <p className="muted">Not enough public data to rank this company.</p>
      )}
      <p className="small">
        <strong>{data.hiring.open_roles}</strong> open roles
        {data.hiring.new_roles_30d ? <> · <strong>{data.hiring.new_roles_30d}</strong> new in 30 days</> : null}
      </p>
    </section>
  );
}

function CompanySection({ data }: { data: Insights }) {
  const facts: [string, string][] = [];
  if (data.financials?.revenue_usd) {
    facts.push([`Revenue FY${data.financials.fiscal_year}`, `${money(data.financials.revenue_usd)}${data.financials.revenue_growth !== null ? ` (${pct(data.financials.revenue_growth)})` : ''}`]);
  }
  if (data.funding?.total_usd) {
    facts.push(['Funding', `${money(data.funding.total_usd)}${data.funding.last_round_type ? ` · ${roundType(data.funding.last_round_type)}` : ''}`]);
  }
  if (data.funding?.employees) {
    facts.push(['Employees', employees(data.funding.employees)]);
  }
  if (!facts.length && !data.tech.length) {
    return null;
  }
  return (
    <section>
      <h3>Company</h3>
      {facts.length ? (
        <dl className="facts">
          {facts.map(([k, v]) => (
            <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
          ))}
        </dl>
      ) : null}
      {data.tech.length ? <div className="chips">{data.tech.slice(0, 10).map((t) => <span key={t} className="chip">{t}</span>)}</div> : null}
    </section>
  );
}

export function Overlay({ result, loading, onClose }: { result: InsightsResult | null; loading: boolean; onClose: () => void }) {
  const [collapsed, setCollapsed] = useState(false);
  let body;
  if (loading || !result) {
    body = <p className="muted pad">Loading company insights…</p>;
  } else if (!result.ok) {
    body = (
      <p className="muted pad">
        {result.reason === 'unknown_company'
          ? 'No data for this company yet.'
          : result.reason === 'api_unreachable'
            ? 'Can’t reach the LinkedIn++ server. Check the API URL in the extension options.'
            : `Something went wrong${result.message ? `: ${result.message}` : '.'}`}
      </p>
    );
  } else {
    body = (
      <>
        <PaySection data={result.data} />
        <InterviewSection data={result.data} />
        <CompetitivenessSection data={result.data} />
        <CompanySection data={result.data} />
      </>
    );
  }
  const name = result?.ok ? result.data.company.name : 'LinkedIn++';
  return (
    <div className="card" role="complementary" aria-label="LinkedIn++ company insights">
      <header>
        <span className="logo">in<b>++</b></span>
        <span className="title">{name}</span>
        <button className="icon" onClick={() => setCollapsed(!collapsed)} aria-label={collapsed ? 'Expand' : 'Collapse'}>
          {collapsed ? '▸' : '▾'}
        </button>
        <button className="icon" onClick={onClose} aria-label="Close">×</button>
      </header>
      {collapsed ? null : <div className="body">{body}</div>}
    </div>
  );
}
