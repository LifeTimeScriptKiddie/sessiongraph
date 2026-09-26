"""Pictures and summaries of mined workflows (content-free, like the data)."""

from __future__ import annotations

import html
from typing import Any

VERDICT_CLASS = {"observe": "kObserve", "cheap_fix": "kCheap", "engineer": "kEngineer"}
VERDICT_TEXT = {"observe": "observe only", "cheap_fix": "cheap fix", "engineer": "engineer it"}
CLASSES = [
    "classDef kObserve fill:#f1f5f9,stroke:#64748b,color:#0f172a",
    "classDef kCheap fill:#dbeafe,stroke:#2563eb,color:#0f172a",
    "classDef kEngineer fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#0f172a",
    "classDef kPhase fill:#ffffff,stroke:#94a3b8,color:#0f172a",
    "classDef kEnd fill:#e2e8f0,stroke:#475569,color:#0f172a",
]


def _label(*lines: Any) -> str:
    text = "<br/>".join(str(x) for x in lines if x not in (None, ""))
    return '"' + text.replace("&", "&amp;").replace('"', "#quot;").replace("<br/>", "\x00").replace("<", "#lt;").replace(">", "#gt;").replace("\x00", "<br/>") + '"'


def overview_mermaid(doc: dict[str, Any]) -> str:
    """Families (sized by share) → the gate's verdict."""
    lines = ["flowchart LR"]
    fams = doc.get("families", [])
    if not fams:
        lines.append(f"  none[{_label('no requests in this window')}]:::kObserve")
    for v, text in VERDICT_TEXT.items():
        if any(f.get("verdict") == v for f in fams):
            lines.append(f"  v_{v}[{_label(text)}]:::{VERDICT_CLASS[v]}")
    for i, f in enumerate(fams[:14]):
        tokens = f.get("median_output_tokens")
        size = "{} req · {}%".format(f["requests"], round(f["share"] * 100))
        tok = "{} tok median".format(tokens) if tokens else None
        lines.append(f"  f{i}[{_label(f['family'], size, tok)}]:::{VERDICT_CLASS.get(f.get('verdict', 'observe'))}")
        lines.append(f"  f{i} --> v_{f.get('verdict', 'observe')}")
    lines += [f"  {c}" for c in CLASSES]
    return "\n".join(lines) + "\n"


def family_mermaid(fam: dict[str, Any], min_share: float = 0.05, keep: int = 12) -> str:
    """Directly-follows graph over phases: edge labels are transition counts, the typical path is thick green.

    Rare transitions (under `min_share` of the family's requests, beyond the `keep` most frequent) are hidden
    so erratic families stay readable; a note says how many.
    """
    lines = ["flowchart LR"]
    full: dict[str, int] = fam.get("dfg", {})
    floor = max(1, min_share * fam.get("requests", 0))
    ranked = sorted(full.items(), key=lambda kv: -kv[1])
    dfg = {e: c for i, (e, c) in enumerate(ranked) if i < keep or c >= floor}
    typical = fam.get("typical_path") or []
    path_edges = {f"{a}>{b}" for a, b in zip(["START", *typical], [*typical, "END"])}
    for e in path_edges:
        if e in full:
            dfg.setdefault(e, full[e])
    hidden = len(full) - len(dfg)
    nodes: set[str] = set()
    for edge in dfg:
        a, b = edge.split(">", 1)
        nodes.update((a, b))
    ids = {n: f"p{i}" for i, n in enumerate(sorted(nodes))}
    for n, nid in ids.items():
        lines.append(f"  {nid}([{_label(n)}]):::{'kEnd' if n in ('START', 'END') else 'kPhase'}")
    thick = []
    for i, (edge, count) in enumerate(dfg.items()):
        a, b = edge.split(">", 1)
        lines.append(f"  {ids[a]} -->|{count}| {ids[b]}")
        if edge in path_edges:
            thick.append(i)
    if thick:
        lines.append(f"  linkStyle {','.join(map(str, thick))} stroke:#16a34a,stroke-width:3px")
    if hidden:
        lines.append(f"  note[{_label(f'{hidden} rare transition(s) hidden')}]:::kObserve")
    lines += [f"  {c}" for c in CLASSES]
    return "\n".join(lines) + "\n"


def summary_markdown(doc: dict[str, Any]) -> str:
    gate = doc.get("gate", {})
    out = [
        "# SessionGraph workflows",
        "",
        f"**{gate.get('headline', '')}.** {doc.get('requests', 0)} requests, {doc.get('sessions', 0)} sessions, "
        f"{len(doc.get('days', []))} day(s). Content-free: phases, counts and token usage only.",
        "",
        "| Family | Requests | Share | Sessions | Days | Median steps | Median out tokens | Friction | Ended on error | Variants | Verdict |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for f in doc.get("families", []):
        out.append(
            f"| {f['family']} | {f['requests']} | {round(f['share'] * 100)}% | {f['sessions']} | {f['days']} | {f['median_steps']} | "
            f"{f.get('median_output_tokens') or '—'} | {round(f.get('friction_rate', f['error_rate']) * 100)}% | {round(f.get('unrecovered_rate', 0) * 100)}% | {f['variant_count']} | {VERDICT_TEXT.get(f.get('verdict', ''), '—')} |"
        )
    for f in doc.get("families", []):
        if f.get("verdict") in ("cheap_fix", "engineer"):
            r = f["recommendation"]
            out += ["", f"## {f['family']}: {VERDICT_TEXT[f['verdict']]}", "",
                    *[f"- {x}" for x in f.get("reasons", [])], "",
                    f"**Change ({r['id']}):** {r['change']}", "",
                    f"**Expected:** {r['expected']}. **Metric:** `{r['metric']['key']}` {r['metric']['direction']}"
                    + (f"; guard `{r['guard']['key']}` {r['guard']['direction']}" if r.get("guard") else "") + "."]
    out += ["", "Pictures: `workflows.html`. Keep or roll back a change: `sessiongraph workflows-compare before.json after.json --recommendation <id>`."]
    return "\n".join(out) + "\n"


def page_html(doc: dict[str, Any]) -> str:
    e = html.escape
    gate = doc.get("gate", {})
    block = lambda src: f'<pre class="mermaid">{e(src)}</pre>'  # noqa: E731
    cards = []
    for f in doc.get("families", [])[:14]:
        rec = f.get("recommendation")
        variants = "".join(
            f"<tr><td>{e(' > '.join(v['shape']) or '(no tools)')}</td><td>{v['count']}</td></tr>" for v in f.get("variants", [])
        )
        cards.append(f"""
<section class="card v-{e(f.get('verdict', 'observe'))}">
  <h2>{e(f['family'])} <span class="badge">{e(VERDICT_TEXT.get(f.get('verdict', ''), ''))}</span></h2>
  <p>{f['requests']} requests ({round(f['share'] * 100)}%) · {f['sessions']} sessions · {f['days']} day(s) · median {f['median_steps']} steps,
  {f.get('median_output_tokens') or '—'} output tokens, {f['median_seconds']}s · friction {round(f.get('friction_rate', f['error_rate']) * 100)}% (a non-test tool failed), ended on error {round(f.get('unrecovered_rate', 0) * 100)}% · {f['variant_count']} variant(s) · typical path {e(' > '.join(f.get('typical_path') or []) or '—')}</p>
  <ul>{''.join(f'<li>{e(r)}</li>' for r in f.get('reasons', []))}</ul>
  {f'<p><b>Change ({e(rec["id"])}):</b> {e(rec["change"])}<br><b>Expected:</b> {e(rec["expected"])} · <b>metric</b> <code>{e(rec["metric"]["key"])}</code> {e(rec["metric"]["direction"])}</p>' if rec else ''}
  <details><summary>Workflow graph (typical path in green) and variants</summary>
  {block(family_mermaid(f))}
  <table><thead><tr><th>Variant (phase shape)</th><th>Count</th></tr></thead><tbody>{variants}</tbody></table>
  </details>
</section>""")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SessionGraph workflows</title>
<style>
  :root {{ --bg:#f8fafc; --fg:#0f172a; --muted:#475569; --card:#fff; --line:#e2e8f0; --obs:#64748b; --cheap:#2563eb; --eng:#d97706; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#0b1220; --fg:#e2e8f0; --muted:#94a3b8; --card:#111a2e; --line:#1e293b; }} }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,sans-serif; }}
  main {{ max-width:1100px; margin:0 auto; padding:24px 16px 48px; }}
  h1 {{ font-size:22px; margin:0 0 4px; }} h2 {{ font-size:17px; margin:0 0 6px; }}
  p, li {{ color:var(--muted); }}
  .card {{ background:var(--card); border:1px solid var(--line); border-left:4px solid var(--obs); border-radius:10px; padding:14px 16px; margin:14px 0; overflow-x:auto; }}
  .v-cheap_fix {{ border-left-color:var(--cheap); }} .v-engineer {{ border-left-color:var(--eng); }}
  .badge {{ font-size:12px; font-weight:600; padding:2px 8px; border-radius:999px; border:1px solid var(--line); margin-left:6px; }}
  pre.mermaid {{ background:#fff; border-radius:6px; padding:8px; }}
  table {{ border-collapse:collapse; font-size:13px; margin-top:8px; }} td, th {{ text-align:left; padding:4px 8px; border-bottom:1px solid var(--line); }}
</style></head>
<body><main>
<h1>SessionGraph workflows</h1>
<p><b>{e(gate.get('headline', ''))}.</b> {doc.get('requests', 0)} requests across {doc.get('sessions', 0)} sessions and {len(doc.get('days', []))} day(s).
Each request is reduced to phases (explore, edit, test, build, commit, delegate, web, shell); requests with the same phase profile form a workflow family.
The gate says per family whether to observe only, apply a cheap fix, or engineer the workflow. Content-free: no prompt, command or answer text.</p>
<section class="card">{block(overview_mermaid(doc))}</section>
{''.join(cards)}
</main>
<script type="module">
  try {{
    const {{ default: mermaid }} = await import('https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs');
    mermaid.initialize({{ startOnLoad:false, theme:'default', securityLevel:'strict', flowchart:{{ htmlLabels:true, useMaxWidth:false }} }});
    document.querySelectorAll('details').forEach((d) => {{ d.open = true; }});
    await mermaid.run({{ querySelector:'pre.mermaid' }});
    document.querySelectorAll('details').forEach((d) => {{ d.open = false; }});
  }} catch (err) {{
    document.querySelectorAll('pre.mermaid').forEach((el) => {{ el.style.whiteSpace = 'pre'; }});
  }}
</script>
</body></html>
"""
