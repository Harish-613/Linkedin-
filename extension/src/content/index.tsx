// Content script for linkedin.com/jobs/*. LinkedIn is a single-page app: moving
// between jobs changes the URL and swaps the DOM without a page load, so we
// watch for both and re-render the overlay whenever the job changes.

import { createRoot, Root } from 'react-dom/client';
import { Overlay } from '../overlay/Overlay';
import { OVERLAY_CSS } from '../overlay/styles';
import type { InsightsRequest, InsightsResult, JobContext } from '../types';
import { extractJob } from './extract';

const HOST_ID = 'linkedinpp-overlay-host';
let root: Root | null = null;
let current = '';
let dismissedFor = '';
let timer: number | undefined;

function mount(): Root {
  if (root && document.getElementById(HOST_ID)) {
    return root;
  }
  const host = document.createElement('div');
  host.id = HOST_ID;
  const shadow = host.attachShadow({ mode: 'open' });
  const style = document.createElement('style');
  style.textContent = OVERLAY_CSS;
  const container = document.createElement('div');
  shadow.append(style, container);
  document.body.append(host);
  root = createRoot(container);
  return root;
}

function unmount() {
  root?.unmount();
  root = null;
  document.getElementById(HOST_ID)?.remove();
}

function render(result: InsightsResult | null, loading: boolean, key: string) {
  mount().render(
    <Overlay
      result={result}
      loading={loading}
      onClose={() => {
        dismissedFor = key;
        unmount();
      }}
    />,
  );
}

function request(job: JobContext): Promise<InsightsResult> {
  const msg: InsightsRequest = { type: 'insights', company: job.company, title: job.title };
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage(msg, (res: InsightsResult | undefined) => {
        resolve(res ?? { ok: false, reason: 'error', message: chrome.runtime.lastError?.message });
      });
    } catch (err) {
      resolve({ ok: false, reason: 'error', message: (err as Error).message }); // extension reloaded
    }
  });
}

async function check() {
  const job = extractJob(document, location.href);
  if (!job) {
    return;
  }
  const key = `${job.jobId ?? ''}|${job.company}|${job.title}`;
  if (key === current || key === dismissedFor) {
    return;
  }
  current = key;
  render(null, true, key);
  const result = await request(job);
  if (current === key) {
    render(result, false, key); // ignore answers for a job the user already left
  }
}

function schedule() {
  window.clearTimeout(timer);
  timer = window.setTimeout(check, 400);
}

new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
window.addEventListener('popstate', schedule);
schedule();
