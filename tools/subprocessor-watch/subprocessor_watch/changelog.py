"""Render CHANGELOG.md: a status table of watched vendors, then changes newest first.

Text comes from third-party pages, so it is treated as untrusted: Markdown/HTML
special characters are escaped before it goes into the file.
"""

import json
import re
from collections import defaultdict
from pathlib import Path

from .incidents import exposure

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]<>()#+!|~])")


def esc(text) -> str:
    if text is None:
        return "—"
    return _MD_SPECIAL.sub(r"\\\1", str(text)).replace("\n", " ")


def _describe(e: dict) -> str:
    who = esc((e["after"] or e["before"])["name_as_listed"])
    if e["change"] == "added":
        return f"➕ **added** {who}: {esc(e['after']['purpose'])} ({esc(e['after']['location'])})"
    if e["change"] == "removed":
        return f"➖ **removed** {who}"
    parts = [f"{f}: {esc(e['before'][f])} → {esc(e['after'][f])}"
             for f in e["after"] if e["before"].get(f) != e["after"][f]]
    return f"✏️ **changed** {who}: " + "; ".join(parts)


def render(data_dir: Path, incidents: list[dict] | None = None) -> str:
    vendors = [json.loads(p.read_text(encoding="utf-8"))
               for p in sorted((data_dir / "vendors").glob("*.json"))]
    names = {v["vendor_id"]: v["name"] for v in vendors}
    lines = ["# Subprocessor Watch: changelog", "",
             "Generated automatically. Each entry links to the public page it came from.", "",
             "## Vendors watched", "",
             "| Vendor | Subprocessors | Last change | Page read |", "|---|---|---|---|"]
    for v in vendors:
        status = "✅ read ok" if v["status"] == "ok" else f"⚠️ {v['status']}: {esc(v['status_detail'])}"
        if v.get("checked_by_hand"):
            status += f" (checked by hand {v['checked_by_hand']})"
        lines.append(f"| [{esc(v['name'])}]({v['source']}) | {len(v['subprocessors'])} "
                     f"| {v['last_changed'] or '—'} | {status} |")

    hit = [r for r in exposure(vendors, incidents or []) if r["listed_by"] or r["confirmed"]]
    if hit:
        lines += ["", "## Incident exposure", "",
                  "Watched vendors that list (or confirmed impact from) a company on the incident watchlist. A lead to review, not proof of exposure.", ""]
        for r in hit:
            lines.append(f"- ⚠️ **{esc(r['name'])}** ({r['date']}): listed by {esc(', '.join(r['listed_by']) or 'none')}")
            lines += [f"  - ❗ disclosure gap: {esc(c['name'])} confirmed impact but does not list {esc(r['name'])}"
                      for c in r["unlisted"]]

    changes_file = data_dir / "changes.jsonl"
    events = [json.loads(l) for l in changes_file.read_text(encoding="utf-8").splitlines() if l.strip()] \
        if changes_file.exists() else []
    lines += ["", "## Changes", ""]
    if not events:
        lines.append("No changes recorded yet.")
    by_date = defaultdict(lambda: defaultdict(list))
    for e in events:
        by_date[e["date"]][e["vendor_id"]].append(e)
    for date in sorted(by_date, reverse=True):
        lines += [f"### {date}", ""]
        for vid in sorted(by_date[date]):
            src = by_date[date][vid][0]["source"]
            lines.append(f"**[{esc(names.get(vid, vid))}]({src})**")
            lines += [f"- {_describe(e)}" for e in by_date[date][vid]]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
