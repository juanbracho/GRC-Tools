"""Spot-check: compare what we extract with the whole live page.

Tests prove we parse the tables we saved. This catches what tests can't:
tables we never read (like Notion's collapsed sections, debug #3), names we
extracted that aren't on the page, and watchlist companies mentioned outside
the tables. Read-only: it never writes data.

    python -m subprocessor_watch.spotcheck [--vendor ID]
"""

import argparse
import sys

from bs4 import BeautifulSoup

from .extract import ExtractError, _find_tables, extract, merge_duplicates

UNREAD_TABLE_MIN_ROWS = 3


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def check(html: str, vendor: dict, aliases: dict, incidents: list[dict]) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    page_text = _norm(soup.get_text(" "))
    tables = soup.find_all("table")
    used = set()
    for spec in vendor["tables"]:
        used |= {id(t) for t in _find_tables(soup, spec)}

    warnings = []
    try:
        merged = merge_duplicates(extract(html, vendor, aliases))
    except ExtractError as exc:
        return {"vendor_id": vendor["vendor_id"], "extracted": 0, "tables": len(tables), "warnings": [f"extract failed: {exc}"]}

    for i, t in enumerate(tables):
        rows = t.find_all("tr")
        if id(t) not in used and i not in vendor.get("reviewed_skip", []) and len(rows) >= UNREAD_TABLE_MIN_ROWS:
            first = next((r.get_text(" ", strip=True)[:40] for r in rows[1:] if r.get_text(strip=True)), "")
            warnings.append(f"table {i} not read ({len(rows)} rows, e.g. {first!r}): confirm it isn't subprocessors")

    missing = [e["name_as_listed"] for e in merged.values() if _norm(e["name_as_listed"]) not in page_text]
    if missing:
        warnings.append(f"{len(missing)} extracted name(s) not found in page text: {missing[:5]}")

    for inc in incidents:
        if inc["subprocessor_id"] not in merged and _norm(inc["name"]) in page_text:
            warnings.append(f"watchlist company {inc['name']!r} is mentioned on the page but not extracted")

    return {"vendor_id": vendor["vendor_id"], "extracted": len(merged), "tables": len(tables),
            "tables_read": len(used), "warnings": warnings}


def main(argv=None) -> int:
    from .__main__ import ROOT, load_config
    from .fetch import Fetcher
    from .incidents import load_incidents

    p = argparse.ArgumentParser(description="Compare extracted lists with the full live pages.")
    p.add_argument("--vendor", help="only check this vendor_id")
    args = p.parse_args(argv)
    vendors, aliases = load_config()
    incidents = load_incidents(ROOT / "incidents.yaml")
    if args.vendor:
        vendors = [v for v in vendors if v["vendor_id"] == args.vendor]

    fetcher, total = Fetcher(), 0
    try:
        for v in vendors:
            try:
                html = fetcher(v["subprocessor_url"], v.get("render"))
            except Exception as exc:
                print(f"{v['vendor_id']:12} FETCH FAILED ({exc})")
                total += 1
                continue
            r = check(html, v, aliases, incidents)
            mark = "ok " if not r["warnings"] else "!! "
            print(f"{mark}{r['vendor_id']:12} extracted {r['extracted']:3}  tables read {r.get('tables_read', 0)}/{r['tables']}")
            for w in r["warnings"]:
                print(f"      - {w}")
            total += len(r["warnings"])
    finally:
        fetcher.close()
    print(f"\n{total} warning(s). Each one needs a human look, not an automatic fix.")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
