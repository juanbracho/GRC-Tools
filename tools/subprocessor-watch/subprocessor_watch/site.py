"""Render site/index.html: a single static page in a terminal style.

Works without JavaScript; app.js adds search and "my stack" on top. Every piece
of vendor-sourced text goes through html.escape (and textContent in app.js),
links are limited to http(s), and the Content-Security-Policy only allows the
page's own inline stylesheet and script, each by SHA-256 hash.
"""

import base64
import hashlib
import json
from collections import defaultdict
from html import escape
from pathlib import Path

from . import __version__
from .incidents import exposure, flags_by_vendor

CSS = """
:root{--bg:#1a1a1a;--panel:#212121;--fg:#e6e6e6;--dim:#8a8a8a;--line:#3a3a3a;
--accent:#d97757;--add:#7ec27e;--del:#e5787a;--mod:#e0b456;--link:#9ab8e8}
@media (prefers-color-scheme:light){:root{--bg:#faf9f6;--panel:#f0eee8;--fg:#1f1f1f;
--dim:#6b6b6b;--line:#d8d4cc;--accent:#c4613f;--add:#2f7d32;--del:#b3261e;--mod:#8a6100;--link:#2a5db0}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}
.box{border:1px solid var(--accent);border-radius:8px;padding:12px 16px;margin-bottom:28px}
.box b{color:var(--accent)}
.dim{color:var(--dim)}
h2{font-size:14px;font-weight:normal;margin:32px 0 8px}
h2::before{content:"> ";color:var(--accent)}
h2 .dim{margin-left:8px}
.out{border-left:2px solid var(--line);padding-left:14px}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:2px 16px 2px 0;vertical-align:top;white-space:nowrap}
th{color:var(--dim);font-weight:normal;border-bottom:1px solid var(--line)}
td.wrap{white-space:normal}
.ok{color:var(--add)}.err{color:var(--del)}
.add{color:var(--add)}.del{color:var(--del)}.mod{color:var(--mod)}
.date{color:var(--accent);margin-top:10px}
.bar{color:var(--accent)}
details{margin:2px 0}summary{cursor:pointer}summary::marker{color:var(--accent)}
details .out{margin:6px 0 12px 6px}
footer{margin-top:40px;color:var(--dim);font-size:12px}
.findings{margin:0 0 8px;padding-left:18px}.findings li{margin:4px 0}
input[type=search]{width:100%;max-width:520px;background:var(--panel);color:var(--fg);
border:1px solid var(--line);border-radius:6px;padding:6px 10px;font:inherit}
input[type=search]:focus{outline:none;border-color:var(--accent)}
.chips{display:flex;flex-wrap:wrap;gap:6px 14px;margin:6px 0 10px}
.chip{cursor:pointer;white-space:nowrap}.chip input{accent-color:var(--accent)}
#sw-results,#sw-stack-out{margin-top:8px}
"""

JS = (Path(__file__).parent / "app.js").read_text(encoding="utf-8")


def _sha256(text: str) -> str:
    return base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()


CSP_HASH = _sha256(CSS)
JS_HASH = _sha256(JS)


def _json_for_html(data) -> str:
    """JSON that can't close its <script> block or open a comment."""
    return (json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def safe_url(url: str) -> str:
    return escape(url) if url.startswith(("https://", "http://")) else "#"


def _load(data_dir: Path):
    vendors = [json.loads(p.read_text(encoding="utf-8"))
               for p in sorted((data_dir / "vendors").glob("*.json"))]
    f = data_dir / "changes.jsonl"
    events = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()] \
        if f.exists() else []
    return vendors, events


def shared_fourth_parties(vendors: list[dict], min_vendors: int = 2) -> list[dict]:
    """Subprocessors that appear behind several vendors (concentration risk)."""
    users, names = defaultdict(set), defaultdict(set)
    for v in vendors:
        for e in v["subprocessors"]:
            users[e["subprocessor_id"]].add(v["name"])
            names[e["subprocessor_id"]].add(e["name_as_listed"])
    rows = [{"subprocessor_id": sid, "name": min(names[sid], key=len), "vendors": sorted(vs)}
            for sid, vs in users.items() if len(vs) >= min_vendors]
    return sorted(rows, key=lambda r: (-len(r["vendors"]), r["subprocessor_id"]))


def _shared_row(r: dict) -> str:
    n = len(r["vendors"])
    name = r["name"].rstrip("*† ")  # footnote markers some pages add
    return (f'<tr><td>{escape(name)}</td><td><span class="bar">{"█" * n}</span> {n}</td>'
            f'<td class="wrap dim">{escape(", ".join(r["vendors"]))}</td></tr>')


def _change_line(e: dict) -> str:
    rec = e["after"] or e["before"]
    who = escape(rec["name_as_listed"])
    if e["change"] == "added":
        detail = escape(" · ".join(x for x in (rec["purpose"], rec["location"]) if x))
        return f'<div><span class="add">+ {who}</span> <span class="dim">{detail}</span></div>'
    if e["change"] == "removed":
        return f'<div><span class="del">- {who}</span></div>'
    diffs = [f"{escape(k)}: {escape(str(e['before'].get(k)))} → {escape(str(v))}"
             for k, v in e["after"].items() if e["before"].get(k) != v]
    return f'<div><span class="mod">~ {who}</span> <span class="dim">{"; ".join(diffs)}</span></div>'


def findings(vendors: list[dict], shared: list[dict], inc_rows: list[dict], events: list[dict]) -> list[str]:
    """Three to five plain sentences a visitor can read in 30 seconds."""
    n = len(vendors)
    out = []
    if shared:
        first, *rest = shared[:3]
        out.append(f"Concentration: {first['name'].rstrip('*† ')} is behind {len(first['vendors'])} of {n} vendors"
                   + "".join(f", {r['name'].rstrip('*† ')} {len(r['vendors'])}" for r in rest) + ".")
    for r in inc_rows:
        if r["listed_by"]:
            out.append(f"Incident exposure: {r['name']} (incident {r['date']}) is listed by {len(r['listed_by'])} "
                       f"vendor(s): {', '.join(r['listed_by'])}.")
        for c in r["unlisted"]:
            out.append(f"Disclosure gap: {c['name']} publicly confirmed impact from the {r['name']} incident, "
                       f"but {r['name']} is not on {c['name']}'s subprocessor list.")
    # Companies whose main business is AI models. Google, AWS and Microsoft are left out on purpose:
    # most vendors list them for hosting, so counting them would overstate AI use.
    ai = {"openai", "anthropic", "xai", "fireworks-ai", "cerebras", "mistral-ai", "cohere", "baseten-labs",
          "together-ai", "groq", "perplexity", "elevenlabs", "deepgram", "assemblyai"}
    with_ai = [v for v in vendors if ai & {e["subprocessor_id"] for e in v["subprocessors"]}]
    if with_ai:
        out.append(f"AI everywhere: {len(with_ai)} of {n} vendors list at least one AI model provider.")
    if events:
        out.append(f"Changes recorded: {len(events)} since monitoring began.")
    return out


def _data_for_js(vendors: list[dict], inc_rows: list[dict]) -> dict:
    return {
        "vendors": [{"id": v["vendor_id"], "name": v["name"],
                     "subs": [{"id": e["subprocessor_id"], "name": e["name_as_listed"].rstrip("*† "),
                               "purpose": e["purpose"]} for e in v["subprocessors"]]} for v in vendors],
        "incidents": [{"id": r["subprocessor_id"], "name": r["name"], "date": r["date"],
                       "summary": r.get("summary") or "", "confirmed": [c["vendor_id"] for c in r["confirmed"]]}
                      for r in inc_rows],
    }


def _source_links(r: dict) -> str:
    return " ".join(f'<a href="{safe_url(u)}">[{i + 1}]</a>' for i, u in enumerate(r.get("sources") or []))


def _incident_section(rows: list[dict]) -> list[str]:
    hit = [r for r in rows if r["listed_by"] or r["confirmed"]]
    out = [f'<h2>incidents --exposure<span class="dim">{len(hit)} of {len(rows)} watched incidents touch your vendors</span></h2>'
           '<div class="out">']
    if not rows:
        out.append('<span class="dim">No incidents on the watchlist (incidents.yaml).</span>')
    for r in hit:
        out.append(f'<div class="date"><span class="del">⚠ {escape(r["name"])}</span> '
                   f'<span class="dim">{escape(r["date"])}</span></div>')
        out.append(f'<div class="dim">{escape(r.get("summary") or "")}</div>')
        if r["listed_by"]:
            out.append(f'<div>listed by: <span class="mod">{escape(", ".join(r["listed_by"]))}</span></div>')
        for c in r["confirmed"]:
            out.append(f'<div>confirmed impact: <span class="mod">{escape(c["name"])}</span> '
                       f'<span class="dim">{escape(c.get("note") or "")} ({escape(c["date"])}, '
                       f'<a href="{safe_url(c["source"])}">source</a>)</span></div>')
        for c in r["unlisted"]:
            out.append(f'<div class="del">! disclosure gap: {escape(c["name"])} confirmed impact, but '
                       f'{escape(r["name"])} is not on its public subprocessor list. Ask why.</div>')
        out.append(f'<div class="dim">sources: {_source_links(r)}</div>')
    quiet = [r for r in rows if r not in hit]
    if quiet:
        out.append(f'<details><summary class="dim">{len(quiet)} watched incident(s) not on any vendor\'s list</summary>'
                   '<div class="out">' + "".join(
                       f'<div>· {escape(r["name"])} <span class="dim">{escape(r["date"])} · '
                       f'{escape(r.get("summary") or "")} {_source_links(r)}</span></div>' for r in quiet)
                   + '</div></details>')
    out.append('</div>')
    return out


def _leads_section(leads: list[dict]) -> list[str]:
    fresh = [l for l in leads if not l.get("on_watchlist")]
    out = [f'<h2>incident-leads --to-review<span class="dim">news that names a fourth party next to incident words · '
           f'{len(fresh)} new</span></h2><div class="out">',
           '<div class="dim">Found automatically in security-news feeds. A lead is a suggestion, not a flag: a person '
           'reads it and, if it is a real incident, adds it to the watchlist with a source.</div>']
    if not leads:
        out.append('<div class="dim">No leads in the last 30 days.</div>')
    for l in leads[:40]:
        tag = '<span class="dim">[on watchlist]</span> ' if l.get("on_watchlist") else ""
        out.append(f'<div class="date"><span class="mod">? {escape(l["name"])}</span> '
                   f'<span class="dim">{escape(l.get("published") or l["first_seen"])} · {escape(l["feed"])}</span></div>'
                   f'<div>{tag}<a href="{safe_url(l["link"])}">{escape(l["title"])}</a></div>'
                   f'<div class="dim">listed by: {escape(", ".join(l["vendors"]) or "—")} · '
                   f'matched: {escape(", ".join(l["words"]))}</div>')
    out.append('</div>')
    return out


def render(data_dir: Path, generated: str, incidents: list[dict] | None = None,
           leads: list[dict] | None = None) -> str:
    vendors, events = _load(data_dir)
    names = {v["vendor_id"]: v["name"] for v in vendors}
    total = sum(len(v["subprocessors"]) for v in vendors)
    unique = len({e["subprocessor_id"] for v in vendors for e in v["subprocessors"]})
    errors = [v for v in vendors if v["status"] != "ok"]
    shared = shared_fourth_parties(vendors)
    inc_rows = exposure(vendors, incidents or [])
    flags = flags_by_vendor(inc_rows)
    out = []

    out.append(f'<div class="box"><b>✻ subprocessor-watch</b> <span class="dim">v{__version__}</span><br>'
               f'<span class="dim">Daily check of vendors\' public subprocessor lists. Who sends data where, and what changed.</span><br>'
               f'<span class="dim">data as of:</span> {escape(generated)} &nbsp;'
               f'<span class="dim">vendors:</span> {len(vendors)} &nbsp;'
               f'<span class="dim">fourth parties:</span> {unique} &nbsp;'
               f'<span class="dim">incident exposure:</span> '
               + (f'<span class="err">{len(flags)} vendor(s)</span> &nbsp;' if flags else '<span class="ok">none</span> &nbsp;')
               + f'<span class="dim">pages read:</span> '
               + (f'<span class="err">{len(errors)} error(s)</span>' if errors else '<span class="ok">all ok</span>')
               + '</div>')

    # findings + interactive layer
    items = findings(vendors, shared, inc_rows, events)
    if items:
        out.append('<h2>findings<span class="dim">read this first</span></h2><div class="out"><ul class="findings">'
                   + "".join(f"<li>{escape(x)}</li>" for x in items) + "</ul></div>")
    out.append('<section id="sw-interactive" hidden>'
               '<h2>search<span class="dim">a vendor (what it uses) or a fourth party (who uses it)</span></h2>'
               '<div class="out"><input type="search" id="sw-q" placeholder="e.g. Notion, Fireworks, OpenAI" '
               'aria-label="Search vendors and fourth parties" autocomplete="off"><div id="sw-results"></div></div>'
               '<h2>my-stack<span class="dim">tick the apps you use · saved in this browser only</span></h2>'
               '<div class="out"><div class="chips" id="sw-stack"></div><div id="sw-stack-out"></div></div>'
               '</section>')

    # status
    out.append('<h2>status<span class="dim">"read ok" = we could read the list. It is not a safety rating.</span></h2><div class="out scroll"><table>'
               '<tr><th>vendor</th><th>subprocessors</th><th>incidents</th><th>last change</th><th>page read</th></tr>')
    for v in vendors:
        st = '<span class="ok">● read ok</span>' if v["status"] == "ok" else \
            (f'<span class="err">● couldn\'t read</span> <span class="dim">{escape(v["status_detail"] or "")}'
             f'{" since " + escape(v["failing_since"]) if v.get("failing_since") else ""} · showing last good list</span>')
        out.append(f'<tr><td><a href="{safe_url(v["source"])}">{escape(v["name"])}</a></td>'
                   f'<td>{len(v["subprocessors"])}</td>'
                   + (f'<td class="err">⚠ {escape(", ".join(flags[v["vendor_id"]]))}</td>' if v["vendor_id"] in flags
                      else '<td class="dim">—</td>')
                   + f'<td>{escape(v["last_changed"] or "—")}</td><td>{st}</td></tr>')
    out.append('</table></div>')
    out += _incident_section(inc_rows)
    out += _leads_section(leads or [])

    # changes
    out.append(f'<h2>changes --recent<span class="dim">{len(events)} event(s)</span></h2><div class="out">')
    if not events:
        out.append('<span class="dim">No changes yet. The first run sets the baseline, and later runs record what moves.</span>')
    by_date = defaultdict(lambda: defaultdict(list))
    for e in events:
        by_date[e["date"]][e["vendor_id"]].append(e)
    for date in sorted(by_date, reverse=True)[:60]:
        out.append(f'<div class="date">{escape(date)}</div>')
        for vid in sorted(by_date[date]):
            out.append(f'<div class="dim">  {escape(names.get(vid, vid))}</div>')
            out += [_change_line(e) for e in by_date[date][vid]]
    out.append('</div>')

    # shared fourth parties
    out.append(f'<h2>fourth-parties --shared<span class="dim">behind 2+ vendors (concentration risk)</span></h2>'
               '<div class="out scroll"><table><tr><th>fourth party</th><th>vendors</th><th>used by</th></tr>')
    if not shared:
        out.append('<tr><td class="dim" colspan="3">none yet</td></tr>')
    top = [r for r in shared if len(r["vendors"]) >= 3] or shared
    rest = shared[len(top):]
    out += [_shared_row(r) for r in top]
    out.append('</table></div>')
    if rest:
        out.append(f'<details><summary class="dim">{len(rest)} more shared by 2 vendors</summary>'
                   '<div class="out scroll"><table>' + "".join(_shared_row(r) for r in rest) + '</table></div></details>')

    # per-vendor lists
    out.append(f'<h2>ls vendors/<span class="dim">{total} entries</span></h2>')
    for v in vendors:
        out.append(f'<details><summary>{escape(v["name"])} <span class="dim">({len(v["subprocessors"])})</span></summary>'
                   '<div class="out scroll"><table><tr><th>subprocessor</th><th>purpose</th><th>location</th><th>since</th></tr>')
        for e in v["subprocessors"]:
            out.append(f'<tr><td>{escape(e["name_as_listed"])}</td><td class="wrap dim">{escape(e["purpose"] or "—")}</td>'
                       f'<td class="wrap dim">{escape(e["location"] or "—")}</td><td class="dim">{escape(e["date"])}</td></tr>')
        out.append(f'</table><div class="dim">source: <a href="{safe_url(v["source"])}">{escape(v["source"])}</a></div></div></details>')

    out.append('<footer>Public data only, checked once a day. Names are shown as each vendor lists them. '
               'A change here is a lead to review, not a verdict.</footer>')

    csp = (f"default-src 'none'; style-src 'sha256-{CSP_HASH}'; script-src 'sha256-{JS_HASH}'; "
           "img-src 'none'; connect-src 'none'; base-uri 'none'; form-action 'none'")
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            f'<meta http-equiv="Content-Security-Policy" content="{csp}">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="referrer" content="no-referrer">'
            f"<title>Subprocessor Watch</title><style>{CSS}</style></head><body><main>\n"
            + "\n".join(out) + "\n</main>"
            f'<script type="application/json" id="sw-data">{_json_for_html(_data_for_js(vendors, inc_rows))}</script>'
            f"<script>{JS}</script></body></html>\n")
