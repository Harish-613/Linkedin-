import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';

const DEFAULT_API = 'http://localhost:8787';

function Options() {
  const [url, setUrl] = useState(DEFAULT_API);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    chrome.storage.sync.get('apiUrl').then(({ apiUrl }) => apiUrl && setUrl(String(apiUrl)));
  }, []);

  async function save() {
    const clean = url.trim().replace(/\/+$/, '');
    let origin: string;
    try {
      origin = new URL(clean).origin;
    } catch {
      setStatus({ ok: false, text: 'That is not a valid URL.' });
      return;
    }
    // localhost is allowed by the manifest; any other server needs the user's permission once.
    if (!/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin)) {
      const granted = await chrome.permissions.request({ origins: [`${origin}/*`] });
      if (!granted) {
        setStatus({ ok: false, text: `Permission to reach ${origin} was not granted.` });
        return;
      }
    }
    await chrome.storage.sync.set({ apiUrl: clean });
    setUrl(clean);
    try {
      const res = await fetch(`${clean}/health`);
      const body = await res.json();
      setStatus(body.ok ? { ok: true, text: 'Saved. Server is up.' } : { ok: false, text: 'Saved, but the server reports a database problem.' });
    } catch {
      setStatus({ ok: false, text: 'Saved, but the server did not respond.' });
    }
  }

  return (
    <main>
      <h1>LinkedIn++</h1>
      <p>Pay ranges, interview difficulty and hiring competitiveness on LinkedIn job pages.</p>
      <label htmlFor="api">API server</label>
      <div className="row">
        <input id="api" value={url} onChange={(e) => setUrl(e.target.value)} spellCheck={false} />
        <button onClick={save}>Save &amp; test</button>
      </div>
      {status ? <p className={status.ok ? 'ok' : 'err'}>{status.text}</p> : null}
      <p className="hint">Run the server locally with <code>npm run dev</code> in <code>server/</code>, or point this at your deployment.</p>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<Options />);
