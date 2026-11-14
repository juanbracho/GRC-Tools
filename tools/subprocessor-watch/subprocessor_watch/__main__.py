"""Command line: ``python -m subprocessor_watch [--vendor ID] [--date YYYY-MM-DD]``"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import yaml

from . import changelog, site
from .incidents import load_incidents
from .fetch import Fetcher
from .watch import run

ROOT = Path(__file__).resolve().parent.parent


def load_config(root: Path = ROOT) -> tuple[list[dict], dict]:
    vendors = yaml.safe_load((root / "vendors.yaml").read_text(encoding="utf-8"))["vendors"]
    aliases = yaml.safe_load((root / "aliases.yaml").read_text(encoding="utf-8")) or {}
    return vendors, aliases


def write_outputs(data_dir: Path) -> None:
    """CHANGELOG.md + site/index.html, only rewritten when the content changes."""
    vendor_files = list((data_dir / "vendors").glob("*.json"))
    # "Last run" on the page = newest data change, so a quiet day doesn't rewrite the file.
    stamp = max((json.loads(p.read_text(encoding="utf-8"))["last_changed"] or "" for p in vendor_files),
                default="—")
    incidents = load_incidents(ROOT / "incidents.yaml")
    outputs = {ROOT / "CHANGELOG.md": changelog.render(data_dir, incidents),
               ROOT / "site" / "index.html": site.render(data_dir, generated=stamp, incidents=incidents)}
    for path, text in outputs.items():
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Check vendors' public subprocessor lists for changes.")
    p.add_argument("--vendor", help="only check this vendor_id")
    p.add_argument("--date", default=dt.datetime.now(dt.UTC).date().isoformat(), help="override today (UTC)")
    p.add_argument("--render-only", action="store_true", help="rebuild CHANGELOG.md and site/ without fetching")
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
        finally:
            fetcher.close()
    write_outputs(data_dir)

    for r in results:
        note = "baseline" if r["baseline"] else f"{len(r['events'])} change(s)"
        line = f"{r['vendor_id']:12} {r['status']:12} {r['count']:4} subprocessors  {note}"
        print(line + (f"  ({r['detail']})" if r["detail"] else ""))
    # Exit 1 if any vendor failed, so the scheduled job shows up red and someone looks.
    return 1 if any(r["status"] != "ok" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
