// Read the company and job title from a LinkedIn job page.
//
// LinkedIn renames its CSS classes often, so this tries several layers, most
// specific first, and finishes with the page title, which has kept the form
// "<Job title> | <Company> | LinkedIn" across redesigns.

import type { JobContext } from '../types';

const TITLE_SELECTORS = [
  '.job-details-jobs-unified-top-card__job-title h1',
  '.job-details-jobs-unified-top-card__job-title',
  '.jobs-unified-top-card__job-title',
  '.top-card-layout__title',
  'h1.t-24',
  'main h1',
];

const COMPANY_SELECTORS = [
  '.job-details-jobs-unified-top-card__company-name a',
  '.job-details-jobs-unified-top-card__company-name',
  '.jobs-unified-top-card__company-name a',
  '.jobs-unified-top-card__company-name',
  '.topcard__org-name-link',
  '.top-card-layout__card a[href*="/company/"]',
  'main a[href*="/company/"][data-tracking-control-name*="company"]',
];

function text(el: Element | null): string {
  return (el?.textContent ?? '').replace(/\s+/g, ' ').trim();
}

function first(doc: Document, selectors: string[]): string {
  for (const s of selectors) {
    const t = text(doc.querySelector(s));
    if (t) {
      return t;
    }
  }
  return '';
}

/** "/jobs/view/4012345678/" or "?currentJobId=4012345678" -> "4012345678". */
export function jobIdFromUrl(href: string): string | null {
  const url = new URL(href);
  const fromPath = url.pathname.match(/\/jobs\/view\/(?:[^/]*-)?(\d{6,})/);
  if (fromPath) {
    return fromPath[1];
  }
  return url.searchParams.get('currentJobId');
}

/** "(3) Software Engineer | Stripe | LinkedIn" -> {title, company}. */
export function parseDocumentTitle(title: string): { title: string; company: string } | null {
  const cleaned = title.replace(/^\(\d+\)\s*/, '').trim();
  const parts = cleaned.split(' | ').map((p) => p.trim());
  if (parts.length >= 3 && parts[parts.length - 1] === 'LinkedIn') {
    return { title: parts[0], company: parts[1] };
  }
  const hiring = cleaned.match(/^(.+?) hiring (.+?) in .+\| LinkedIn$/); // public (logged-out) job pages
  if (hiring) {
    return { company: hiring[1].trim(), title: hiring[2].trim() };
  }
  return null;
}

export function extractJob(doc: Document, href: string): JobContext | null {
  const jobId = jobIdFromUrl(href);
  let title = first(doc, TITLE_SELECTORS);
  let company = first(doc, COMPANY_SELECTORS);
  if (!title || !company) {
    const fromTitle = parseDocumentTitle(doc.title);
    title ||= fromTitle?.title ?? '';
    company ||= fromTitle?.company ?? '';
  }
  if (!title || !company || company.length > 120) {
    return null;
  }
  return { company, title, jobId };
}
