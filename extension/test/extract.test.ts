import { readFileSync } from 'fs';
import { join } from 'path';
import { describe, expect, it } from 'vitest';
import { extractJob, jobIdFromUrl, parseDocumentTitle } from '../src/content/extract';

function load(name: string): Document {
  return new DOMParser().parseFromString(readFileSync(join(__dirname, 'fixtures', name), 'utf8'), 'text/html');
}

describe('extractJob', () => {
  it('reads the current two-pane job view', () => {
    const job = extractJob(load('job_view_2025.html'), 'https://www.linkedin.com/jobs/view/4012345678/');
    expect(job).toEqual({ company: 'Coinbase', title: 'Software Engineer, New Grad (2027)', jobId: '4012345678' });
  });

  it('reads the older unified top card', () => {
    const job = extractJob(load('job_view_legacy.html'), 'https://www.linkedin.com/jobs/search/?currentJobId=3999000111&keywords=swe');
    expect(job).toEqual({ company: 'Ramp', title: 'Senior Backend Engineer', jobId: '3999000111' });
  });

  it('falls back to the page title on public (logged-out) job pages', () => {
    const job = extractJob(load('job_public.html'), 'https://www.linkedin.com/jobs/view/software-engineer-backend-at-ramp-4011112223');
    expect(job).toEqual({ company: 'Ramp', title: 'Software Engineer, Backend', jobId: '4011112223' });
  });

  it('returns null on pages without a job', () => {
    expect(extractJob(load('feed.html'), 'https://www.linkedin.com/feed/')).toBeNull();
  });
});

describe('helpers', () => {
  it('parses document titles', () => {
    expect(parseDocumentTitle('(12) Quant Researcher | Jane Street | LinkedIn')).toEqual({ title: 'Quant Researcher', company: 'Jane Street' });
    expect(parseDocumentTitle('Jobs | LinkedIn')).toBeNull();
  });

  it('finds job ids in paths and query strings', () => {
    expect(jobIdFromUrl('https://www.linkedin.com/jobs/view/4012345678/?refId=x')).toBe('4012345678');
    expect(jobIdFromUrl('https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4000000001')).toBe('4000000001');
    expect(jobIdFromUrl('https://www.linkedin.com/jobs/')).toBeNull();
  });
});
