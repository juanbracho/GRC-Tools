"""Match the incident watchlist against every vendor's subprocessor list.

For each incident:
- listed_by:   watched vendors whose public list includes the affected company
- confirmed:   vendors that publicly said they were affected (from incidents.yaml)
- unlisted:    confirmed but NOT on that vendor's public list, which is a disclosure gap worth asking about
"""

from pathlib import Path

import yaml


def load_incidents(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    incidents = data.get("incidents") or []
    for i in incidents:
        i["date"] = str(i["date"])  # YAML reads bare dates as date objects
        for c in i.get("confirmed_impact") or []:
            c["date"] = str(c["date"])
    return incidents


def exposure(vendors: list[dict], incidents: list[dict]) -> list[dict]:
    """One row per incident, newest first. Vendor names are display names."""
    names = {v["vendor_id"]: v["name"] for v in vendors}
    listed = {}
    for v in vendors:
        for e in v["subprocessors"]:
            listed.setdefault(e["subprocessor_id"], set()).add(v["vendor_id"])
    rows = []
    for inc in incidents:
        listed_by = sorted(listed.get(inc["subprocessor_id"], set()))
        confirmed = [c for c in inc.get("confirmed_impact") or [] if c["vendor_id"] in names]
        unlisted = [c for c in confirmed if c["vendor_id"] not in listed_by]
        rows.append({**inc,
                     "listed_by": [names[v] for v in listed_by],
                     "listed_by_ids": listed_by,
                     "confirmed": [{**c, "name": names[c["vendor_id"]]} for c in confirmed],
                     "unlisted": [{**c, "name": names[c["vendor_id"]]} for c in unlisted]})
    # Incidents that touch a watched vendor first, then newest first.
    rows.sort(key=lambda r: r["date"], reverse=True)
    rows.sort(key=lambda r: not (r["listed_by"] or r["confirmed"]))
    return rows


def flags_by_vendor(rows: list[dict]) -> dict[str, list[str]]:
    """vendor_id -> names of incident-hit companies it lists or confirmed."""
    flags: dict[str, list[str]] = {}
    for r in rows:
        for vid in r["listed_by_ids"] + [c["vendor_id"] for c in r["confirmed"]]:
            if r["name"] not in flags.setdefault(vid, []):
                flags[vid].append(r["name"])
    return flags
