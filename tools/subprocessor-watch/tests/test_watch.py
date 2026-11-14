"""End-to-end runs on a throwaway data folder with a fake fetcher (never live sites)."""

import json

import pytest

from subprocessor_watch import changelog
from subprocessor_watch.diff import diff
from subprocessor_watch.fetch import FetchError
from subprocessor_watch.watch import check_vendor

VENDOR = {"vendor_id": "acme", "name": "Acme", "subprocessor_url": "https://acme.example/subprocessors",
          "tables": [{"heading": "Subprocessors", "columns": {"name": 0, "purpose": 1, "location": 2}}]}


def page(*rows):
    body = "".join(f"<tr><td>{n}</td><td>{p}</td><td>{l}</td></tr>" for n, p, l in rows)
    return f"<html><h2>Subprocessors</h2><table><tr><th>Name</th><th>Purpose</th><th>Where</th></tr>{body}</table></html>"


BASE = [("Amazon Web Services, Inc.", "Hosting", "US"), ("Stripe, Inc.", "Payments", "US"),
        ("Zendesk", "Support", "US"), ("Twilio Inc.", "SMS", "US")]


class FakeFetch:
    def __init__(self, html=None, error=None):
        self.html, self.error = html, error

    def __call__(self, url, render=None):
        if self.error:
            raise FetchError(self.error)
        return self.html


def run(tmp_path, html=None, error=None, date="2026-11-12"):
    return check_vendor(VENDOR, {}, tmp_path, FakeFetch(html, error), date)


def state(tmp_path):
    return json.loads((tmp_path / "vendors" / "acme.json").read_text())


def changes(tmp_path):
    f = tmp_path / "changes.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []


def test_first_run_is_baseline_without_events(tmp_path):
    r = run(tmp_path, page(*BASE))
    assert r["baseline"] and r["events"] == [] and r["count"] == 4
    assert state(tmp_path)["last_changed"] == "2026-11-12"
    assert all(e["date"] == "2026-11-12" and e["source"] for e in state(tmp_path)["subprocessors"])
    assert changes(tmp_path) == []


def test_no_change_does_not_rewrite_file(tmp_path):
    run(tmp_path, page(*BASE))
    before = (tmp_path / "vendors" / "acme.json").stat().st_mtime_ns
    r = run(tmp_path, page(*BASE), date="2026-11-13")
    assert r["events"] == []
    assert (tmp_path / "vendors" / "acme.json").stat().st_mtime_ns == before  # no daily commit noise


def test_reordered_rows_are_not_a_change(tmp_path):
    run(tmp_path, page(*BASE))
    assert run(tmp_path, page(*reversed(BASE)), date="2026-11-13")["events"] == []


def test_added_removed_modified(tmp_path):
    run(tmp_path, page(*BASE))
    new = [BASE[0], ("Stripe, Inc.", "Payments", "US, EU"), BASE[2], ("Fireworks AI", "AI inference", "US")]
    r = run(tmp_path, page(*new), date="2026-11-14")
    kinds = {(e["change"], e["subprocessor_id"]) for e in r["events"]}
    assert kinds == {("added", "fireworks-ai"), ("removed", "twilio"), ("modified", "stripe")}
    s = state(tmp_path)
    assert s["last_changed"] == "2026-11-14"
    first_seen = {e["subprocessor_id"]: e["date"] for e in s["subprocessors"]}
    assert first_seen["stripe"] == "2026-11-12" and first_seen["fireworks-ai"] == "2026-11-14"
    assert len(changes(tmp_path)) == 3


def test_parser_broke_keeps_previous_list(tmp_path):
    run(tmp_path, page(*BASE))
    r = run(tmp_path, "<html><h2>New design</h2></html>", date="2026-11-13")
    assert r["status"] == "parse_error" and r["events"] == []
    s = state(tmp_path)
    assert s["status"] == "parse_error" and len(s["subprocessors"]) == 4
    assert changes(tmp_path) == []


def test_big_shrink_is_suspicious_not_mass_removal(tmp_path):
    run(tmp_path, page(*BASE))
    r = run(tmp_path, page(BASE[0]), date="2026-11-13")
    assert r["status"] == "parse_error" and "shrank" in r["detail"]
    assert changes(tmp_path) == []


def test_fetch_error_keeps_previous_list_then_recovers(tmp_path):
    run(tmp_path, page(*BASE))
    assert run(tmp_path, error="HTTP 503", date="2026-11-13")["status"] == "fetch_error"
    assert len(state(tmp_path)["subprocessors"]) == 4
    r = run(tmp_path, page(*BASE), date="2026-11-14")
    assert r["status"] == "ok" and r["events"] == [] and state(tmp_path)["status"] == "ok"


def test_changelog_renders_and_escapes_untrusted_text(tmp_path):
    run(tmp_path, page(*BASE))
    run(tmp_path, page(*BASE, ("Evil <script>alert(1)</script> [x](http://bad)", "AI", "US")), date="2026-11-15")
    md = changelog.render(tmp_path)
    assert "### 2026-11-15" in md and "added" in md
    assert "<script>" not in md and "](http://bad)" not in md
    assert "| [Acme](https://acme.example/subprocessors) | 5 | 2026-11-15 | ✅ read ok |" in md


def test_diff_is_sorted_and_stable():
    prev = {"b": {"name_as_listed": "B", "purpose": "x", "location": "y"}}
    cur = {"c": {"name_as_listed": "C", "purpose": "x", "location": "y"},
           "a": {"name_as_listed": "A", "purpose": "x", "location": "y"}}
    ids = [e["subprocessor_id"] for e in diff("v", prev, cur, "s", "d")]
    assert ids == ["a", "c", "b"]


def test_adding_an_alias_is_not_a_vendor_change(tmp_path):
    rows = [("Google LLC", "Cloud", "US"), ("Google Vertex AI", "AI", "US"), *BASE[:3]]
    check_vendor(VENDOR, {}, tmp_path, FakeFetch(page(*rows)), "2026-11-12")
    assert len(state(tmp_path)["subprocessors"]) == 5
    r = check_vendor(VENDOR, {"google-vertex-ai": "google"}, tmp_path, FakeFetch(page(*rows)), "2026-11-13")
    assert r["events"] == [] and r["count"] == 4
    assert {e["subprocessor_id"]: e["date"] for e in state(tmp_path)["subprocessors"]}["google"] == "2026-11-12"
