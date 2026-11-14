import json
from pathlib import Path

from subprocessor_watch import changelog, site
from subprocessor_watch.incidents import exposure, flags_by_vendor, load_incidents

ROOT = Path(__file__).parent.parent


def v(vid, name, subs):
    return {"vendor_id": vid, "name": name, "source": f"https://{vid}.example", "status": "ok",
            "status_detail": None, "last_changed": "2026-11-13",
            "subprocessors": [{"vendor_id": vid, "subprocessor_id": s, "name_as_listed": s, "purpose": None,
                               "location": None, "source": "x", "date": "2026-11-13"} for s in subs]}


VENDORS = [v("asana", "Asana", ["fireworks-ai", "aws"]), v("notion", "Notion", ["aws"]), v("zoom", "Zoom", ["aws"])]
INCIDENTS = [
    {"subprocessor_id": "fireworks-ai", "name": "Fireworks AI", "date": "2026-10-06", "sources": ["https://a.example"],
     "confirmed_impact": [{"vendor_id": "notion", "date": "2026-11-06", "source": "https://n.example"},
                          {"vendor_id": "not-watched", "date": "2026-11-06", "source": "https://n.example"}]},
    {"subprocessor_id": "railway", "name": "Railway", "date": "2026-10-20", "sources": []},
    {"subprocessor_id": "northflank", "name": "Northflank", "date": "2026-10-30", "sources": []},
]


def test_listed_confirmed_and_disclosure_gap():
    rows = {r["subprocessor_id"]: r for r in exposure(VENDORS, INCIDENTS)}
    fw = rows["fireworks-ai"]
    assert fw["listed_by"] == ["Asana"]
    assert [c["name"] for c in fw["confirmed"]] == ["Notion"]   # unwatched vendors ignored
    assert [c["name"] for c in fw["unlisted"]] == ["Notion"]    # confirmed, but not on Notion's list
    assert rows["railway"]["listed_by"] == [] and rows["railway"]["unlisted"] == []


def test_order_touching_first_then_newest():
    assert [r["subprocessor_id"] for r in exposure(VENDORS, INCIDENTS)] == ["fireworks-ai", "northflank", "railway"]


def test_flags_by_vendor_includes_confirmed():
    assert flags_by_vendor(exposure(VENDORS, INCIDENTS)) == {"asana": ["Fireworks AI"], "notion": ["Fireworks AI"]}


def test_real_watchlist_is_well_formed():
    incidents = load_incidents(ROOT / "incidents.yaml")
    assert incidents, "watchlist empty"
    for i in incidents:
        assert i["subprocessor_id"] and i["name"] and len(i["date"]) == 10
        assert i["sources"] and all(u.startswith("https://") for u in i["sources"])
        for c in i.get("confirmed_impact") or []:
            assert c["source"].startswith("https://") and len(c["date"]) == 10


def test_page_and_changelog_show_exposure(tmp_path):
    (tmp_path / "vendors").mkdir()
    for x in VENDORS:
        (tmp_path / "vendors" / f"{x['vendor_id']}.json").write_text(json.dumps(x))
    html = site.render(tmp_path, "2026-11-13", INCIDENTS)
    assert "incidents --exposure" in html and "disclosure gap: Notion" in html
    assert "incident exposure:</span> <span class=\"err\">2 vendor(s)" in html
    assert ' style="' not in html  # CSP would block inline style attributes
    md = changelog.render(tmp_path, INCIDENTS)
    assert "**Fireworks AI** (2026-10-06): listed by Asana" in md and "disclosure gap: Notion" in md
