import base64
import hashlib
import json
import re

from subprocessor_watch import site


def write_vendor(d, vid, name, subs, status="ok"):
    (d / "vendors").mkdir(parents=True, exist_ok=True)
    (d / "vendors" / f"{vid}.json").write_text(json.dumps({
        "vendor_id": vid, "name": name, "source": f"https://{vid}.example/sub", "status": status,
        "status_detail": None if status == "ok" else "0 subprocessors found", "last_changed": "2026-11-13",
        "subprocessors": [{"vendor_id": vid, "subprocessor_id": s, "name_as_listed": n, "purpose": "p",
                           "location": "US", "source": "x", "date": "2026-11-13"} for s, n in subs]}))


def test_shared_fourth_parties_counts_and_sorts(tmp_path):
    write_vendor(tmp_path, "a", "A", [("aws", "Amazon Web Services, Inc."), ("openai", "OpenAI")])
    write_vendor(tmp_path, "b", "B", [("aws", "AWS"), ("openai", "OpenAI, L.L.C.")])
    write_vendor(tmp_path, "c", "C", [("aws", "Amazon")])
    vendors, _ = site._load(tmp_path)
    shared = site.shared_fourth_parties(vendors)
    assert [(r["subprocessor_id"], len(r["vendors"])) for r in shared] == [("aws", 3), ("openai", 2)]
    assert shared[0]["name"] == "AWS"  # shortest listed name


def test_page_escapes_untrusted_text_and_only_has_our_scripts(tmp_path):
    evil = '</script><script>alert(1)</script><img src=x onerror=y>'
    write_vendor(tmp_path, "a", "A", [("evil", evil)])
    (tmp_path / "changes.jsonl").write_text(json.dumps({
        "vendor_id": "a", "subprocessor_id": "evil", "change": "added", "before": None,
        "after": {"name_as_listed": "<b onclick=x>hi</b>", "purpose": None, "location": None},
        "source": "x", "date": "2026-11-13"}) + "\n")
    html = site.render(tmp_path, "2026-11-13")
    # exactly two script blocks: the JSON data block and our app.js
    assert html.count("<script") == 2 and html.count("</script>") == 2
    assert '<script type="application/json" id="sw-data">' in html
    assert "<img" not in html and "alert(1)</script>" not in html
    assert "&lt;script&gt;" in html                       # escaped in the static HTML
    data = re.search(r'id="sw-data">(.*?)</script>', html, re.S).group(1)
    assert "<" not in data and "\\u003c/script\\u003e" in data   # can't close the data block
    assert json.loads(data)["vendors"][0]["subs"][0]["name"] == evil  # but decodes back to the raw text


def test_app_js_never_uses_innerhtml():
    assert "innerHTML" not in site.JS and "eval(" not in site.JS and "document.write" not in site.JS


def test_csp_hashes_match_inline_script(tmp_path):
    write_vendor(tmp_path, "a", "A", [("x", "X")])
    html = site.render(tmp_path, "2026-11-13")
    script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert f"script-src 'sha256-{digest}'" in html and "connect-src 'none'" in html


def test_findings_are_plain_sentences(tmp_path):
    write_vendor(tmp_path, "a", "A", [("google", "Google LLC"), ("openai", "OpenAI")])
    write_vendor(tmp_path, "b", "B", [("google", "Google"), ("fireworks-ai", "Fireworks AI")])
    vendors, events = site._load(tmp_path)
    inc = [{"subprocessor_id": "fireworks-ai", "name": "Fireworks AI", "date": "2026-10-06", "sources": [],
            "confirmed_impact": [{"vendor_id": "a", "date": "2026-11-06", "source": "https://x"}]}]
    from subprocessor_watch.incidents import exposure
    f = site.findings(vendors, site.shared_fourth_parties(vendors), exposure(vendors, inc), events)
    assert f[0] == "Concentration: Google is behind 2 of 2 vendors."
    assert any(x.startswith("Incident exposure: Fireworks AI") and "B" in x for x in f)
    assert any(x.startswith("Disclosure gap: A publicly confirmed") for x in f)
    assert any(x == "AI everywhere: 2 of 2 vendors list at least one AI model provider." for x in f)
    # Google alone (cloud hosting) must not count as an AI provider
    cloud_only = [{"vendor_id": "g", "name": "G", "subprocessors": [{"subprocessor_id": "google"}]}]
    assert not any(x.startswith("AI everywhere") for x in site.findings(cloud_only, [], [], []))


def test_non_http_links_are_neutralised():
    assert site.safe_url("javascript:alert(1)") == "#"
    assert site.safe_url("https://ok.example/a?b=1&c=2") == "https://ok.example/a?b=1&amp;c=2"


def test_csp_hash_matches_inline_style(tmp_path):
    write_vendor(tmp_path, "a", "A", [("x", "X")])
    html = site.render(tmp_path, "2026-11-13")
    style = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    digest = base64.b64encode(hashlib.sha256(style.encode()).digest()).decode()
    assert f"style-src 'sha256-{digest}'" in html and "default-src 'none'" in html


def test_error_status_is_visible(tmp_path):
    write_vendor(tmp_path, "a", "A", [], status="parse_error")
    html = site.render(tmp_path, "2026-11-13")
    assert "1 error(s)" in html and "couldn't read" in html and "showing last good list" in html


def test_two_vendor_parties_fold_into_details(tmp_path):
    write_vendor(tmp_path, "a", "A", [("aws", "AWS"), ("x", "X Ltd.**")])
    write_vendor(tmp_path, "b", "B", [("aws", "AWS"), ("x", "X Ltd.**")])
    write_vendor(tmp_path, "c", "C", [("aws", "AWS")])
    html = site.render(tmp_path, "2026-11-13")
    top, _, folded = html.partition("1 more shared by 2 vendors")
    assert "<td>AWS</td>" in top and "X Ltd." in folded and "X Ltd.**" not in html.split("ls vendors/")[0]


def test_status_shows_checked_by_hand_date(tmp_path):
    write_vendor(tmp_path, "a", "A", [("aws", "AWS")])
    p = tmp_path / "vendors" / "a.json"
    p.write_text(p.read_text().replace('"status": "ok"', '"status": "ok", "checked_by_hand": "2026-11-15"'))
    assert "checked by hand 2026-11-15" in site.render(tmp_path, "2026-11-15")
