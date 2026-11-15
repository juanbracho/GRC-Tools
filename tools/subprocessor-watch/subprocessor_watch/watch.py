"""One daily run: fetch -> extract -> safety check -> diff -> save.

Files written (all under ``data_dir``):
- ``vendors/<vendor_id>.json``  latest good list + status (only rewritten when something changed)
- ``changes.jsonl``              append-only change events (shared schema)

The per-subprocessor ``date`` is when we first saw it on that vendor's list.
"""

import json
import time
from pathlib import Path

from .diff import SuspiciousShrink, check_shrink, diff
from .extract import ExtractError, extract, merge_duplicates
from .fetch import FetchError
from .normalize import subprocessor_id


def load_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def check_vendor(vendor: dict, aliases: dict, data_dir: Path, fetch, today: str) -> dict:
    """Process one vendor. Returns a summary: status, events, detail."""
    vid, source = vendor["vendor_id"], vendor["subprocessor_url"]
    state_path = data_dir / "vendors" / f"{vid}.json"
    old = load_state(state_path)
    # Re-normalize last run's list with today's aliases, so adding an alias
    # (our change) never shows up as a vendor change.
    previous = merge_duplicates([{**e, "subprocessor_id": subprocessor_id(e["name_as_listed"], aliases)}
                                 for e in old["subprocessors"]]) if old else {}

    status, detail, events = "ok", None, []
    try:
        current = merge_duplicates(extract(fetch(source, vendor.get("render")), vendor, aliases))
        check_shrink(previous, current)
    except FetchError as exc:
        status, detail = "fetch_error", str(exc)
    except (ExtractError, SuspiciousShrink) as exc:
        status, detail = "parse_error", str(exc)

    if status == "ok":
        # First run is a baseline: record the list, don't announce 30 "added" events.
        if old:
            events = diff(vid, previous, current, source, today)
        entries = []
        for sid in sorted(current):
            entry = {"vendor_id": vid, **current[sid], "source": source,
                     "date": previous[sid]["date"] if sid in previous else today}
            entries.append(entry)
        last_changed = today if (events or not old) else old["last_changed"]
    else:
        entries = old["subprocessors"] if old else []
        last_changed = old["last_changed"] if old else None

    # failing_since: first day of the current run of failures (None when the page reads fine).
    # Stored once, so a vendor that stays blocked doesn't rewrite its file every day.
    failing_since = None if status == "ok" else ((old or {}).get("failing_since") or today)
    new = {"vendor_id": vid, "name": vendor["name"], "source": source, "status": status,
           "status_detail": detail, "failing_since": failing_since, "last_changed": last_changed,
           "subprocessors": entries}
    if new != old:
        _write_json(state_path, new)
    if events:
        with (data_dir / "changes.jsonl").open("a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return {"vendor_id": vid, "status": status, "detail": detail, "failing_since": failing_since,
            "events": events, "baseline": old is None and status == "ok", "count": len(entries)}


def run(vendors: list[dict], aliases: dict, data_dir: Path, fetch, today: str,
        delay: float = 2.0) -> list[dict]:
    results = []
    for i, vendor in enumerate(vendors):
        if i and delay:
            time.sleep(delay)  # be polite between sites
        results.append(check_vendor(vendor, aliases, data_dir, fetch, today))
    return results
