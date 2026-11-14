import json

import pytest

from subprocessor_watch import leads, site


def vendor(vid, name, subs):
    return {"vendor_id": vid, "name": name, "source": "https://x.example", "status": "ok", "status_detail": None,
            "last_changed": "2026-11-14",
            "subprocessors": [{"vendor_id": vid, "subprocessor_id": s, "name_as_listed": n, "purpose": None,
                               "location": None, "source": "x", "date": "2026-11-14"} for s, n in subs]}


VENDORS = [vendor("asana", "Asana", [("fireworks-ai", "Fireworks AI, Inc."), ("google", "Google LLC"),
                                     ("plain", "Plain"), ("databricks", "Databricks, Inc.")]),
           vendor("figma", "Figma", [("fireworks-ai", "Fireworks AI")])]

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Fireworks AI discloses second breach</title><link>https://news.example/fw</link>
  <description>&lt;p&gt;Attackers accessed billing data.&lt;/p&gt;</description><pubDate>Mon, 09 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>Google patches Chrome zero-day</title><link>https://news.example/g1</link>
  <description>Google says hackers exploited the flaw.</description><pubDate>Mon, 09 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>Google confirms breach of internal ticket system</title><link>https://news.example/g2</link>
  <description>x</description><pubDate>Mon, 09 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>In plain terms: ransomware explained</title><link>https://news.example/plain</link>
  <description>A plain guide.</description><pubDate>Mon, 09 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>Databricks launches new AI features</title><link>https://news.example/db</link>
  <description>Product news.</description><pubDate>Mon, 09 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>Bad link</title><link>javascript:alert(1)</link><description>breach Fireworks AI</description></item>
</channel></rss>"""


def found(items):
    return {(l["subprocessor_id"], l["link"].rsplit("/", 1)[-1]) for l in leads.match(items, leads.build_terms(VENDORS, []))}


def test_matching_rules():
    got = found(leads.parse_feed(RSS, "Test"))
    assert ("fireworks-ai", "fw") in got              # named + incident word
    assert ("google", "g1") not in got                # giant: incident word only in summary -> no
    assert ("google", "g2") in got                    # giant: name + strong word in headline -> yes
    assert not any(s == "plain" for s, _ in got)      # ordinary-word name skipped
    assert not any(s == "databricks" for s, _ in got) # no incident words
    assert not any(l == "alert(1)" for _, l in got)   # non-https links dropped


def test_explicit_match_terms_allow_ambiguous_names():
    inc = [{"subprocessor_id": "warp", "name": "Warp", "date": "2026-10-23", "match_terms": ["Warp terminal"]}]
    items = [{"title": "Warp terminal hit by breach", "summary": "", "link": "https://n.example/w", "feed": "T",
              "published": None}]
    assert leads.match(items, leads.build_terms(VENDORS, inc))[0]["subprocessor_id"] == "warp"


def test_feed_parser_blocks_xml_bombs():
    bomb = '<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><rss><channel><item><title>&b;</title></item></channel></rss>'
    with pytest.raises(Exception):
        leads.parse_feed(bomb, "Evil")


def test_update_keeps_first_seen_expires_and_writes_only_on_change(tmp_path):
    path = tmp_path / "leads.json"
    new = leads.match(leads.parse_feed(RSS, "Test"), leads.build_terms(VENDORS, []))
    leads.update(path, new, "2026-11-14", {"fireworks-ai"})
    first = json.loads(path.read_text())
    assert all(l["first_seen"] == "2026-11-14" for l in first)
    assert [l["on_watchlist"] for l in first if l["subprocessor_id"] == "fireworks-ai"] == [True]
    mtime = path.stat().st_mtime_ns
    leads.update(path, new, "2026-11-14", {"fireworks-ai"})
    assert path.stat().st_mtime_ns == mtime                          # unchanged -> not rewritten
    assert leads.update(path, [], "2026-12-20", set()) == []          # older than 30 days -> dropped


def test_feed_failure_is_reported_not_fatal(tmp_path):
    class Boom:
        def get(self, url):
            raise OSError("down")
    found_leads, errors = leads.run([{"name": "X", "url": "https://x"}], VENDORS, [], Boom(), tmp_path / "l.json", "2026-11-14")
    assert found_leads == [] and errors == ["X: OSError"]


def test_page_shows_leads_escaped(tmp_path):
    (tmp_path / "vendors").mkdir()
    (tmp_path / "vendors" / "asana.json").write_text(json.dumps(VENDORS[0]))
    lead = {"id": "1", "subprocessor_id": "fireworks-ai", "name": "Fireworks AI", "vendors": ["Asana"],
            "title": "<script>x</script> breach", "link": "javascript:alert(1)", "feed": "T", "published": "2026-11-09",
            "words": ["breach"], "first_seen": "2026-11-14", "on_watchlist": False}
    html = site.render(tmp_path, "2026-11-14", [], [lead])
    assert "incident-leads --to-review" in html and "&lt;script&gt;x" in html
    assert 'href="javascript' not in html
