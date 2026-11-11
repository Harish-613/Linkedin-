// Service worker: the only place that talks to the LinkedIn++ API.
// Content scripts on linkedin.com are subject to LinkedIn's CORS rules, so they
// message this worker instead of fetching directly.

import type { InsightsRequest, InsightsResult } from './types';

export const DEFAULT_API = 'http://localhost:8787';
const CACHE_MS = 10 * 60 * 1000;
const cache = new Map<string, { at: number; result: InsightsResult }>();

export async function apiBase(): Promise<string> {
  const { apiUrl } = await chrome.storage.sync.get('apiUrl');
  return String(apiUrl || DEFAULT_API).replace(/\/+$/, '');
}

export async function fetchInsights(req: InsightsRequest, fetchImpl: typeof fetch = fetch): Promise<InsightsResult> {
  const key = `${req.company}|${req.title}`;
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < CACHE_MS) {
    return hit.result;
  }
  const url = `${await apiBase()}/api/insights?${new URLSearchParams({ company: req.company, title: req.title })}`;
  let result: InsightsResult;
  try {
    const res = await fetchImpl(url);
    if (res.status === 404) {
      result = { ok: false, reason: 'unknown_company' };
    } else if (!res.ok) {
      result = { ok: false, reason: 'error', message: `API returned ${res.status}` };
    } else {
      result = { ok: true, data: await res.json() };
    }
  } catch (err) {
    return { ok: false, reason: 'api_unreachable', message: (err as Error).message }; // not cached: retry next time
  }
  cache.set(key, { at: Date.now(), result });
  return result;
}

if (typeof chrome !== 'undefined' && chrome.runtime?.onMessage) {
  chrome.runtime.onMessage.addListener((msg: InsightsRequest, _sender, sendResponse) => {
    if (msg?.type !== 'insights') {
      return false;
    }
    fetchInsights(msg).then(sendResponse);
    return true; // keep the channel open for the async response
  });
}
