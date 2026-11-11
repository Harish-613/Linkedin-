// Injected into the overlay's shadow root, so LinkedIn's CSS can't leak in and ours can't leak out.
// Colours follow LinkedIn's palette closely enough to feel native, in light and dark mode.
export const OVERLAY_CSS = `
:host { all: initial; }
.card {
  --bg: #ffffff; --fg: #191919; --muted: #666666; --line: #e8e8e8; --accent: #0a66c2;
  --chip: #eef3f8; --dot: #d0d7de;
  position: fixed; right: 20px; bottom: 20px; z-index: 2147483000;
  width: 340px; max-height: calc(100vh - 120px); overflow: hidden; display: flex; flex-direction: column;
  background: var(--bg); color: var(--fg); border: 1px solid var(--line); border-radius: 10px;
  box-shadow: 0 6px 24px rgba(0,0,0,.14);
  font: 14px/1.4 -apple-system, system-ui, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
@media (prefers-color-scheme: dark) {
  .card { --bg: #1d2226; --fg: #e9e9e9; --muted: #a3a3a3; --line: #38434f; --accent: #70b5f9; --chip: #2c3640; --dot: #4b5662; }
}
header { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--line); }
.logo { font-weight: 700; color: #fff; background: var(--accent); border-radius: 4px; padding: 1px 5px; font-size: 13px; }
.logo b { font-weight: 800; }
.title { flex: 1; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
button { font: inherit; color: inherit; background: none; border: 0; cursor: pointer; }
.icon { width: 24px; height: 24px; border-radius: 50%; color: var(--muted); font-size: 16px; line-height: 1; }
.icon:hover { background: var(--chip); }
.link { color: var(--accent); font-weight: 600; padding: 0; margin-left: auto; }
.body { overflow-y: auto; }
section { padding: 10px 14px; border-bottom: 1px solid var(--line); }
section:last-child { border-bottom: 0; }
h3 { margin: 0 0 6px; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }
.tag { text-transform: none; letter-spacing: 0; font-weight: 500; background: var(--chip); border-radius: 8px; padding: 0 6px; margin-left: 4px; }
.pay { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
.big { font-size: 22px; font-weight: 700; }
.dash { color: var(--muted); }
.median { color: var(--muted); margin-left: 4px; }
.row { display: flex; align-items: center; gap: 8px; }
.meter { display: inline-flex; gap: 3px; }
.dot { width: 9px; height: 9px; border-radius: 50%; background: var(--dot); }
.dot.on { background: var(--accent); }
.note { margin: 6px 0 0; }
.muted { color: var(--muted); margin: 0; }
.small { font-size: 12px; margin: 6px 0 0; }
.pad { padding: 14px; }
.chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.chip { background: var(--chip); border-radius: 10px; padding: 1px 8px; font-size: 12px; }
.factors { list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 4px; font-size: 12px; }
.factors li { display: grid; grid-template-columns: 1fr 90px; align-items: center; gap: 8px; }
.bar { height: 6px; background: var(--chip); border-radius: 3px; overflow: hidden; }
.bar span { display: block; height: 100%; background: var(--accent); }
.facts { margin: 0; display: grid; gap: 2px; }
.facts div { display: flex; justify-content: space-between; gap: 12px; }
.facts dt { color: var(--muted); }
.facts dd { margin: 0; font-weight: 600; text-align: right; }
`;
