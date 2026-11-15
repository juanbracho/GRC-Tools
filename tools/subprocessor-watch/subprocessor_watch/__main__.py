"""Command line: ``python -m subprocessor_watch [--vendor ID] [--date YYYY-MM-DD]``"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import yaml

from . import changelog, leads, site
from .incidents import load_incidents
from .fetch import Fetcher
from .watch import run

ROOT = Path(__file__).resolve().parent.parent


def load_config(root: Path = ROOT) -> tuple[list[dict], dict]:
    vendors = yaml.safe_load((root / "vendors.yaml").read_text(encoding="utf-8"))["vendors"]
    aliases = yaml.safe_load((root / "aliases.yaml").read_text(encoding="utf-8")) or {}
    return vendors, aliases


def _load_leads(data_dir: Path) -> list[dict]:
    f = data_dir / "incident_leads.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def _vendor_states(data_dir: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((data_dir / "vendors").glob("*.json"))]


def write_outputs(data_dir: Path) -> None:
    """CHANGELOG.md + site/index.html, only rewritten when the content changes."""
    vendor_files = list((data_dir / "vendors").glob("*.json"))
    # "Last run" on the page = newest data change, so a quiet day doesn't rewrite the file.
    stamp = max((json.loads(p.read_text(encoding="utf-8"))["last_changed"] or "" for p in vendor_files),
                default="—")
    incidents = load_incidents(ROOT / "incidents.yaml")
    outputs = {ROOT / "CHANGELOG.md": changelog.render(data_dir, incidents),
               ROOT / "site" / "index.html": site.render(data_dir, generated=stamp, incidents=incidents,
                                                         leads=_load_leads(data_dir))}
    for path, text in outputs.items():
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")


STALE_DAYS = 3


def needs_attention(results: list[dict], today: str) -> bool:
    """Should the scheduled job go red? Only when a person has to act:
    - parse_error: the page layout changed and our reader needs fixing;
    - fetch_error for STALE_DAYS days or more: blocked or down for a while.
    A short fetch_error (a site briefly down, or blocking cloud IPs for a day)
    keeps the last good list and is shown on the page, but doesn't fail the job."""
    for r in results:
        if r["status"] == "parse_error":
            return True
        if r["status"] == "fetch_error" and r.get("failing_since"):
            days = (dt.date.fromisoformat(today) - dt.date.fromisoformat(r["failing_since"])).days
            if days >= STALE_DAYS:
                return True
    return False


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Check vendors' public subprocessor lists for changes.")
    p.add_argument("--vendor", help="only check this vendor_id")
    p.add_argument("--date", default=dt.datetime.now(dt.UTC).date().isoformat(), help="override today (UTC)")
    p.add_argument("--render-only", action="store_true", help="rebuild CHANGELOG.md and site/ without fetching")
    p.add_argument("--no-leads", action="store_true", help="skip the security-news scan for incident leads")
    args = p.parse_args(argv)

    vendors, aliases = load_config()
    if args.vendor:
        vendors = [v for v in vendors if v["vendor_id"] == args.vendor]
        if not vendors:
            print(f"unknown vendor_id: {args.vendor}", file=sys.stderr)
            return 2

    data_dir = ROOT / "data"
    results = []
    if not args.render_only:
        fetcher = Fetcher()
        try:
            results = run(vendors, aliases, data_dir, fetcher, args.date)
            if not args.no_leads and not args.vendor:
                feeds = yaml.safe_load((ROOT / "feeds.yaml").read_text(encoding="utf-8"))["feeds"]
                found, feed_errors = leads.run(feeds, _vendor_states(data_dir), load_incidents(ROOT / "incidents.yaml"),
                                               fetcher.client, data_dir / "incident_leads.json", args.date)
                print(f"incident leads: {len(found)} in the last {leads.KEEP_DAYS} days"
                      + (f"  (feeds failed: {', '.join(feed_errors)})" if feed_errors else ""))
        finally:
            fetcher.close()
    write_outputs(data_dir)

    for r in results:
        note = "baseline" if r["baseline"] else f"{len(r['events'])} change(s)"
        line = f"{r['vendor_id']:12} {r['status']:12} {r['count']:4} subprocessors  {note}"
        if r.get("failing_since"):
            line += f"  [failing since {r['failing_since']}]"
        print(line + (f"  ({r['detail']})" if r["detail"] else ""))
    return 1 if needs_attention(results, args.date) else 0


if __name__ == "__main__":
    sys.exit(main())
