import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Overlay } from '../src/overlay/Overlay';
import { dots, employees, money, pct, roundType } from '../src/overlay/format';
import type { Insights } from '../src/types';

const insights: Insights = {
  company: { id: 1, name: 'Coinbase Global, Inc.', domain: 'coinbase.com', ticker: 'COIN' },
  role: { title: 'Software Engineer, New Grad', family: 'software_engineering', seniority: 'new_grad' },
  pay: { p25: 140000, p50: 150000, p75: 165000, n: 12, sources: { postings: 9, levels: 3 }, family: 'software_engineering', seniority: 'new_grad', exact: true, total_comp_p50: 210000 },
  interview: { score: 3.8, label: 'Hard', rationale: 'Algorithms-heavy; asks for ~2 yrs', focus_areas: ['graphs', 'system design'], method: 'llm:gpt-4o-mini', family: 'software_engineering' },
  competitiveness: { score: 82, label: 'Very competitive', factors: { pay: 0.9, scale: 0.95, scarcity: 0.6 } },
  hiring: { open_roles: 120, new_roles_30d: 30 },
  financials: { revenue_usd: 6564028000, revenue_growth: 1.11, fiscal_year: 2024 },
  funding: null,
  tech: ['React', 'Go'],
  updated_at: '2026-11-10T00:00:00Z',
};

describe('Overlay', () => {
  it('shows pay, interview, competitiveness and company facts', () => {
    render(<Overlay result={{ ok: true, data: insights }} loading={false} onClose={() => {}} />);
    expect(screen.getByText('Coinbase Global, Inc.')).toBeTruthy();
    expect(screen.getByText('$140K')).toBeTruthy();
    expect(screen.getByText('$165K')).toBeTruthy();
    expect(screen.getByText('median $150K')).toBeTruthy();
    expect(screen.getByText('Total comp median $210K')).toBeTruthy();
    expect(screen.getByText('9 posted ranges · 3 Levels.fyi reports')).toBeTruthy();
    expect(screen.getByText('Hard')).toBeTruthy();
    expect(screen.getByText(/summarized by an LLM/)).toBeTruthy();
    expect(screen.getByText('Very competitive')).toBeTruthy();
    expect(screen.getByText('$6.6B (+111%)')).toBeTruthy();
    expect(screen.getByText('graphs')).toBeTruthy();
  });

  it('explains competitiveness factors on demand', () => {
    render(<Overlay result={{ ok: true, data: insights }} loading={false} onClose={() => {}} />);
    expect(screen.queryByText('Pay vs. market')).toBeNull();
    fireEvent.click(screen.getByText('why?'));
    expect(screen.getByText('Pay vs. market')).toBeTruthy();
    expect(screen.getByText('Few openings per employee')).toBeTruthy();
  });

  it('says when pay comes from a broader group than the job', () => {
    const data = { ...insights, pay: { ...insights.pay!, exact: false, seniority: 'all' } };
    render(<Overlay result={{ ok: true, data }} loading={false} onClose={() => {}} />);
    expect(screen.getByText('Based on software engineering (all levels) at this company')).toBeTruthy();
  });

  it('handles missing data honestly', () => {
    const data = { ...insights, pay: null, interview: null, competitiveness: null, financials: null, tech: [] };
    render(<Overlay result={{ ok: true, data }} loading={false} onClose={() => {}} />);
    expect(screen.getByText('Not enough salary data for this role yet.')).toBeTruthy();
    expect(screen.getByText('Not enough public data to rank this company.')).toBeTruthy();
  });

  it('shows loading, unknown-company and unreachable states', () => {
    const { rerender } = render(<Overlay result={null} loading onClose={() => {}} />);
    expect(screen.getByText('Loading company insights…')).toBeTruthy();
    rerender(<Overlay result={{ ok: false, reason: 'unknown_company' }} loading={false} onClose={() => {}} />);
    expect(screen.getByText('No data for this company yet.')).toBeTruthy();
    rerender(<Overlay result={{ ok: false, reason: 'api_unreachable' }} loading={false} onClose={() => {}} />);
    expect(screen.getByText(/Can’t reach the LinkedIn\+\+ server/)).toBeTruthy();
  });

  it('collapses and closes', () => {
    const onClose = vi.fn();
    render(<Overlay result={{ ok: true, data: insights }} loading={false} onClose={onClose} />);
    fireEvent.click(screen.getByLabelText('Collapse'));
    expect(screen.queryByText('Hard')).toBeNull();
    fireEvent.click(screen.getByLabelText('Close'));
    expect(onClose).toHaveBeenCalled();
  });
});

describe('format', () => {
  it('formats numbers', () => {
    expect(money(1900000000)).toBe('$1.9B');
    expect(money(25000000000)).toBe('$25B');
    expect(money(152400)).toBe('$152K');
    expect(money(null)).toBe('—');
    expect(pct(-0.034)).toBe('-3%');
    expect(employees({ min: 1001, max: 5000 })).toBe('1K–5K');
    expect(employees({ min: 10001, max: null })).toBe('10K+');
    expect(roundType('series_e')).toBe('Series E');
    expect(dots(82)).toBe(4);
  });
});
