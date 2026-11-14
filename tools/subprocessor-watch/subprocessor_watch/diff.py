"""Compare yesterday's list with today's and produce change events.

Safety valve: if today's list is empty or shrank by more than half, we assume
the parser broke (a page redesign), not that half the suppliers left. We keep
the previous list and emit no "removed" events.
"""

TRACKED_FIELDS = ("purpose", "location")
SHRINK_LIMIT = 0.5


class SuspiciousShrink(Exception):
    pass


def check_shrink(previous: dict[str, dict], current: dict[str, dict]) -> None:
    if not current:
        raise SuspiciousShrink("0 subprocessors found")
    if previous and len(current) < len(previous) * SHRINK_LIMIT:
        raise SuspiciousShrink(f"list shrank from {len(previous)} to {len(current)}")


def diff(vendor_id: str, previous: dict[str, dict], current: dict[str, dict],
         source: str, date: str) -> list[dict]:
    """Change events in the shared-schema shape, sorted for stable output."""
    events = []
    for sid in sorted(current.keys() - previous.keys()):
        events.append(_event(vendor_id, sid, "added", None, _fields(current[sid]), source, date))
    for sid in sorted(previous.keys() - current.keys()):
        events.append(_event(vendor_id, sid, "removed", _fields(previous[sid]), None, source, date))
    for sid in sorted(previous.keys() & current.keys()):
        before, after = _fields(previous[sid]), _fields(current[sid])
        if before != after:
            events.append(_event(vendor_id, sid, "modified", before, after, source, date))
    return events


def _fields(entry: dict) -> dict:
    return {"name_as_listed": entry["name_as_listed"], **{f: entry.get(f) for f in TRACKED_FIELDS}}


def _event(vendor_id, sid, change, before, after, source, date):
    return {"vendor_id": vendor_id, "subprocessor_id": sid, "change": change,
            "before": before, "after": after, "source": source, "date": date}
