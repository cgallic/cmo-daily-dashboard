"""Build the CMO daily command-center dashboard (self-contained static HTML).

Reads the local store (inbox.db) if present, else falls back to the demo
fixtures (fixtures/inbox.jsonl + fixtures/STATE.json). All data is embedded at
build time, so the generated dashboard/index.html has ZERO external deps and
ZERO runtime fetches — open it directly from disk or serve it anywhere static.

    python -m cmo_dashboard.build              # build from store, fall back to fixtures
    python -m cmo_dashboard.build --fixtures   # force-build from fixtures only

This is the "control surface" sibling of an approval-inbox: a daily command
center (channel health + what to do today), not a universal action queue. Action
rows here are DISPLAY-ONLY — actually executing them belongs to approval-inbox.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIXTURES = ROOT / "fixtures"
DASH_DIR = ROOT / "dashboard"

STATUS_COLOR = {
    "consistent":    "#22c55e",
    "running":       "#22c55e",
    "intermittent":  "#eab308",
    "unverified":    "#a78bfa",
    "stalled":       "#ef4444",
    "no_driver":     "#f59e0b",
    "setup":         "#3b82f6",
    "manual":        "#94a3b8",
    "deprioritized": "#334155",
    "unknown":       "#475569",
}

LOOP_LABELS = {
    "revenue_leads":        "Revenue & Leads",
    "traffic_seo":          "Traffic & SEO",
    "content_distribution": "Distribution",
    "outreach_backlinks":   "Outreach",
    "ads":                  "Ads",
    "product_health":       "Product Health",
    "retention":            "Retention",
    "weekly_growth":        "Weekly Review",
    "research_digest":      "Research",
}


# --------------------------------------------------------------------------
# data loading (store-first, fixtures-fallback)
# --------------------------------------------------------------------------
def _load_data(force_fixtures: bool = False) -> tuple[list[dict], dict, dict]:
    """Return (items, state_payload, last_run). Pure stdlib; no live calls."""
    db = ROOT / "inbox.db"
    if not force_fixtures and db.exists():
        try:
            from cmo_dashboard.store import InboxStore
        except ImportError:
            sys.path.insert(0, str(ROOT))
            from cmo_dashboard.store import InboxStore  # type: ignore
        store = InboxStore(db)
        items = (store.query_items(state="staged") + store.query_items(state="new"))
        state_path = ROOT / "STATE.json"
        state = (json.loads(state_path.read_text(encoding="utf-8"))
                 if state_path.exists() else {"channels": {}})
        return items, state, store.last_run()

    # Fixtures fallback — pure file reads.
    items: list[dict] = []
    jsonl = FIXTURES / "inbox.jsonl"
    if jsonl.exists():
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                items.append(json.loads(line))
    items = [i for i in items if i.get("state", "new") in ("new", "staged")]
    state_path = FIXTURES / "STATE.json"
    state = (json.loads(state_path.read_text(encoding="utf-8"))
             if state_path.exists() else {"channels": {}})
    last_run = {"id": state.get("as_of", "-"), "mode": "dry-run"}
    return items, state, last_run


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------
def _score_class(score: int) -> str:
    if score >= 80:
        return "s-crit"
    if score >= 65:
        return "s-high"
    if score >= 50:
        return "s-med"
    return "s-low"


def _item_html(it: dict) -> str:
    state   = it.get("state", "new")
    owner   = it.get("owner", "")
    score   = int(it.get("score", 50))
    itype   = it.get("type", "suggestion")
    channel = (it.get("channel") or "").replace("_", " ")
    loop    = LOOP_LABELS.get(it.get("loop", ""), it.get("loop", ""))
    title   = html.escape(it.get("title", ""))
    body    = html.escape(it.get("body") or "")
    item_id = html.escape(it.get("id", ""))

    action  = it.get("action") or {}
    if isinstance(action, str):
        try:
            action = json.loads(action)
        except (json.JSONDecodeError, TypeError):
            action = {}
    cmd      = (action.get("cmd") or action.get("note") or "") if isinstance(action, dict) else ""
    cmd_html = (f'<div class="item-cmd"><code>{html.escape(cmd)}</code></div>'
                if cmd else "")

    # Display-only badges (no live execution from this surface).
    if state == "staged":
        tag, item_cls = "STAGED", "item staged"
    elif owner == "OPERATOR-approve":
        tag, item_cls = "NEEDS APPROVAL", "item approve"
    else:
        tag, item_cls = "TODAY", "item todo"

    type_dot = "●" if itype == "task" else "○"   # ● filled task / ○ open suggestion
    sc_cls   = _score_class(score)

    return f"""<div class="{item_cls}" data-id="{item_id}">
  <div class="item-top">
    <span class="sc {sc_cls}">{score}</span>
    <span class="type-dot" title="{itype}">{type_dot}</span>
    <div class="item-title">{title}</div>
    <span class="item-tag">{tag}</span>
  </div>
  <div class="item-meta">{html.escape(loop)} &rarr; {html.escape(channel)}</div>
  <div class="item-body">{body}</div>
  {cmd_html}
</div>"""


def _loop_section(loop_key: str, items: list[dict]) -> str:
    label = LOOP_LABELS.get(loop_key, loop_key)
    rows  = "".join(_item_html(i) for i in items)
    return f"""<section class="loop-section">
  <div class="loop-hd">{html.escape(label)} <span class="loop-count">{len(items)}</span></div>
  {rows}
</section>"""


def _chip(ch: str, s: dict) -> str:
    color  = STATUS_COLOR.get(s.get("status", ""), "#475569")
    status = s.get("status", "?")
    ev     = (s.get("evidence") or "")[:140]
    label  = ch.replace("_", " ")
    return (f'<span class="chip" style="--c:{color}" title="{html.escape(ev)}">'
            f'<span class="chip-dot"></span>{html.escape(label)}: {html.escape(status)}</span>')


def build(force_fixtures: bool = False) -> Path:
    items, state, last_run = _load_data(force_fixtures)

    approve = sorted(
        [i for i in items
         if i.get("state") == "staged" or i.get("owner") == "OPERATOR-approve"],
        key=lambda x: -int(x.get("score", 50)))
    todo = sorted(
        [i for i in items if i.get("owner") == "OPERATOR-do"],
        key=lambda x: -int(x.get("score", 50)))

    by_loop: dict[str, list] = {}
    for i in todo:
        by_loop.setdefault(i.get("loop", "other"), []).append(i)

    channels = (state.get("channels") or {})
    order = list(STATUS_COLOR)
    chips = "".join(
        _chip(ch, s) for ch, s in sorted(
            channels.items(),
            key=lambda kv: (order.index(kv[1].get("status", ""))
                            if kv[1].get("status", "") in order else 99, kv[0])))

    run_id   = str(last_run.get("id", "-"))
    run_date = run_id[:10] if len(run_id) >= 10 else run_id
    run_mode = str(last_run.get("mode", ""))

    approve_html = ("".join(_item_html(i) for i in approve)
                    or '<p class="empty">nothing waiting for approval</p>')
    todo_html    = ("".join(_loop_section(k, v) for k, v in by_loop.items())
                    or '<p class="empty">all clear</p>')

    out = HTML_TMPL.format(
        run_date=html.escape(run_date),
        run_mode=html.escape(run_mode),
        n_appr=len(approve),
        n_todo=len(todo),
        n_chan=len(channels),
        chips=chips,
        approve_rows=approve_html,
        todo_rows=todo_html,
    )
    DASH_DIR.mkdir(parents=True, exist_ok=True)
    dest = DASH_DIR / "index.html"
    dest.write_text(out, encoding="utf-8")
    return dest


HTML_TMPL = r"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>CMO Daily — Command Center</title>
<style>
:root{{
  --bg:#090e1a;--panel:#0d1426;--card:#111b30;--border:#1e2d4a;
  --ink:#dde3f0;--mut:#5a7099;--acc:#4f8ef7;
  --green:#22c55e;--yellow:#eab308;--red:#ef4444;--purple:#a78bfa;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--ink);font:13px/1.5 -apple-system,"Segoe UI",sans-serif;
      height:100dvh;display:flex;flex-direction:column;overflow:hidden}}

/* header */
header{{padding:10px 16px;border-bottom:1px solid var(--border);flex-shrink:0;
        display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.logo{{font-size:16px;font-weight:800;letter-spacing:-.3px}}
.logo span{{color:var(--acc)}}
.run-info{{font-size:11px;color:var(--mut);margin-left:auto}}
.badge{{display:inline-flex;align-items:center;gap:4px;background:var(--card);
        border:1px solid var(--border);border-radius:6px;padding:2px 8px;font-size:11px}}

/* channel-health strip */
.strip{{display:flex;flex-wrap:wrap;gap:5px;padding:7px 16px;
        border-bottom:1px solid var(--border);flex-shrink:0}}
.chip{{font-size:10px;border:1px solid var(--c,#475569);border-radius:20px;
       padding:2px 9px;color:var(--c,#475569);background:var(--bg);
       white-space:nowrap;display:inline-flex;align-items:center;gap:4px;cursor:default}}
.chip-dot{{width:5px;height:5px;border-radius:50%;background:var(--c,#475569);flex-shrink:0}}

/* two-column main */
.main{{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--border);
       flex:1;overflow:hidden;min-height:0}}
.col{{background:var(--bg);display:flex;flex-direction:column;overflow:hidden}}
.col-hd{{padding:8px 14px;font-size:11px;font-weight:700;text-transform:uppercase;
         letter-spacing:.6px;color:var(--mut);border-bottom:1px solid var(--border);
         flex-shrink:0}}
.col-hd b{{color:var(--ink);font-size:14px}}
.col-body{{overflow-y:auto;flex:1;padding:8px}}

/* loop sections (right col) */
.loop-section{{margin-bottom:12px}}
.loop-hd{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;
          color:var(--mut);padding:4px 6px;display:flex;align-items:center;gap:6px}}
.loop-count{{background:var(--card);border:1px solid var(--border);border-radius:10px;
             padding:0 6px;font-size:10px;color:var(--ink)}}

/* item cards */
.item{{background:var(--card);border:1px solid var(--border);border-radius:8px;
       padding:9px 11px;margin-bottom:5px;border-left:3px solid var(--border)}}
.item.approve{{border-left-color:#f59e0b}}
.item.staged{{border-left-color:#7c3aed;background:#0e0d1f}}
.item.todo{{border-left-color:var(--acc)}}

.item-top{{display:flex;align-items:flex-start;gap:7px}}
.sc{{font-size:10px;font-weight:800;min-width:28px;text-align:center;
     border-radius:5px;padding:2px 4px;flex-shrink:0;margin-top:1px}}
.s-crit{{background:#1a2e1a;color:#4ade80}}
.s-high{{background:#1c2e20;color:#86efac}}
.s-med{{background:#1c2535;color:#93c5fd}}
.s-low{{background:#1a1a22;color:var(--mut)}}

.type-dot{{font-size:9px;color:var(--mut);flex-shrink:0;margin-top:3px}}
.item-title{{font-weight:600;font-size:12.5px;flex:1;line-height:1.3}}
.item-tag{{font-size:9px;font-weight:700;letter-spacing:.4px;color:var(--mut);
           border:1px solid var(--border);border-radius:5px;padding:1px 6px;
           flex-shrink:0;margin-left:6px;white-space:nowrap}}
.item.staged .item-tag{{color:#c4b5fd;border-color:#7c3aed}}
.item.approve .item-tag{{color:#fbbf24;border-color:#f59e0b}}
.item.todo .item-tag{{color:#93c5fd;border-color:var(--acc)}}

.item-meta{{font-size:10px;color:var(--mut);margin:3px 0 4px 35px}}
.item-body{{font-size:11.5px;color:#94a3b8;margin-left:35px;
            white-space:pre-wrap;line-height:1.45;max-height:160px;overflow-y:auto}}
.item-cmd{{margin:6px 35px 0;background:#0a1020;border:1px solid #1e3a5f;
           border-radius:5px;padding:5px 8px;overflow-x:auto}}
.item-cmd code{{font:12px/1.4 "Fira Code","Cascadia Code",monospace;
                color:#60a5fa;white-space:nowrap}}

.empty{{color:var(--mut);font-size:12px;padding:10px 8px;font-style:italic}}
footer{{padding:6px 16px;border-top:1px solid var(--border);flex-shrink:0;
        font-size:10px;color:var(--mut)}}
</style></head><body>

<header>
  <div class=logo><span>CMO</span> Daily</div>
  <div class=badge>&#128197; {run_date}</div>
  <div class=badge>&#9889; {n_appr} to approve</div>
  <div class=badge>&#128203; {n_todo} to do</div>
  <div class=badge>&#128225; {n_chan} channels</div>
  <div class=run-info>mode: {run_mode} &nbsp;&middot;&nbsp; static build &middot; display-only</div>
</header>

<div class=strip>{chips}</div>

<div class=main>
  <div class=col>
    <div class=col-hd>&#9889; Approve / Review &nbsp;<b>{n_appr}</b></div>
    <div class=col-body>{approve_rows}</div>
  </div>
  <div class=col>
    <div class=col-hd>&#128203; Do today &nbsp;<b>{n_todo}</b></div>
    <div class=col-body>{todo_rows}</div>
  </div>
</div>

<footer>Read-only command center. Numbers shown are <b>demo data</b>.
Execution belongs to a separate approval-inbox — this surface is display-only.</footer>

</body></html>"""


if __name__ == "__main__":
    force = "--fixtures" in sys.argv
    print("wrote", build(force_fixtures=force))
