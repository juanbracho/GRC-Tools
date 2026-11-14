"""Incident leads: scan security-news feeds for our fourth parties.

A lead = a recent article that names a company on some watched vendor's list
AND uses incident words (breach, hacked, ransomware...). Leads are shown for a
human to review; they never flag a vendor by themselves. Confirmed incidents
go into incidents.yaml by hand, with a source.

Noise control (name matching is the hard part):
- names that are ordinary words ("Plain", "Front", "Warp") are skipped unless
  incidents.yaml gives explicit match terms for them;
- very large companies (Google, Microsoft...) are in the news daily, so they
  only match when the name AND a strong incident word are in the headline.
"""

import datetime as dt
import hashlib
import json
import re
from email.utils import parsedate_to_datetime
from pathlib import Path

import defusedxml.ElementTree as ET
from bs4 import BeautifulSoup

from .normalize import slugify

KEEP_DAYS = 30

INCIDENT_WORDS = ["breach", "breached", "hacked", "hack", "hackers", "compromised", "compromise", "ransomware",
                  "data leak", "leaked", "exposed", "unauthorized access", "security incident", "stolen",
                  "extortion", "cyberattack", "intrusion"]
STRONG_WORDS = ["breach", "breached", "hacked", "compromised", "ransomware", "security incident", "data leak"]

# Ordinary words or very short names: too noisy to match on their own.
AMBIGUOUS = {"plain", "front", "warp", "modal", "exa", "hex", "omni", "reveal", "sphere", "census", "knock",
             "courier", "elastic", "retool", "segment", "apple", "box", "mux", "persona", "sift", "pusher",
             "braintrust", "turbopuffer", "agora", "telus", "nutun", "boldr", "yoti", "intercom", "zendesk"}
# Always in the news; require name + strong word in the headline.
GIANTS = {"google", "amazon-web-services", "microsoft", "apple", "oracle", "salesforce", "cloudflare", "ibm",
          "meta-platforms", "openai", "anthropic", "stripe", "twilio", "snowflake"}

_PARENS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_SUFFIX = re.compile(r"[,\s]+(inc|llc|ltd|limited|pbc|corp|corporation|gmbh|b\.?v|s\.?a\.?s?|plc|co)\.?\**$", re.I)


def display_names(name: str) -> str:
    """'Amazon Web Services, Inc.' -> 'Amazon Web Services' (for matching in prose)."""
    n = _PARENS.sub(" ", name).strip().rstrip("*† ")
    for _ in range(3):
        n = _SUFFIX.sub("", n).strip(" ,.")
    return " ".join(n.split())


def build_terms(vendors: list[dict], incidents: list[dict]) -> dict[str, dict]:
    """subprocessor_id -> {name, terms[], vendors[]} for every fourth party and watchlist company."""
    terms: dict[str, dict] = {}
    for v in vendors:
        for e in v["subprocessors"]:
            t = terms.setdefault(e["subprocessor_id"], {"name": display_names(e["name_as_listed"]),
                                                         "terms": set(), "vendors": []})
            if v["name"] not in t["vendors"]:
                t["vendors"].append(v["name"])
            t["terms"].add(display_names(e["name_as_listed"]))
            if len(display_names(e["name_as_listed"])) < len(t["name"]):
                t["name"] = display_names(e["name_as_listed"])
    for inc in incidents:
        t = terms.setdefault(inc["subprocessor_id"], {"name": inc["name"], "terms": set(), "vendors": []})
        t["terms"].add(inc["name"])
        t["terms"] |= set(inc.get("match_terms") or [])
        t["explicit"] = bool(inc.get("match_terms"))
    for sid, t in terms.items():
        if not t.get("explicit"):
            t["terms"] = {x for x in t["terms"] if len(x) >= 3 and slugify(x) not in AMBIGUOUS and sid not in AMBIGUOUS}
        t["patterns"] = [re.compile(rf"(?<![\w.-]){re.escape(x)}(?![\w-])", re.I if len(x) > 4 else 0)
                         for x in sorted(t["terms"])]
    return {sid: t for sid, t in terms.items() if t["patterns"]}


def parse_feed(xml_text: str, feed_name: str) -> list[dict]:
    """RSS 2.0 or Atom -> [{title, link, summary, published}]. defusedxml blocks XML bombs."""
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    items = []
    atom = "{http://www.w3.org/2005/Atom}"
    for it in root.iter("item"):
        items.append({"title": (it.findtext("title") or "").strip(), "link": (it.findtext("link") or "").strip(),
                      "summary": it.findtext("description") or "", "published": _date(it.findtext("pubDate")),
                      "feed": feed_name})
    for it in root.iter(f"{atom}entry"):
        link = it.find(f"{atom}link")
        items.append({"title": (it.findtext(f"{atom}title") or "").strip(),
                      "link": (link.get("href") if link is not None else "") or "",
                      "summary": it.findtext(f"{atom}summary") or it.findtext(f"{atom}content") or "",
                      "published": _date(it.findtext(f"{atom}updated"), iso=True), "feed": feed_name})
    for i in items:
        i["summary"] = " ".join(BeautifulSoup(i["summary"], "html.parser").get_text(" ").split())[:600]
    return [i for i in items if i["title"] and i["link"].startswith("https://")]


def _date(text: str | None, iso: bool = False) -> str | None:
    if not text:
        return None
    try:
        d = dt.datetime.fromisoformat(text.replace("Z", "+00:00")) if iso else parsedate_to_datetime(text)
        return d.astimezone(dt.UTC).date().isoformat()
    except (TypeError, ValueError):
        return None


def _has(words: list[str], text: str) -> list[str]:
    low = text.lower()
    return [w for w in words if re.search(rf"\b{re.escape(w)}\b", low)]


def match(items: list[dict], terms: dict[str, dict]) -> list[dict]:
    leads = []
    for it in items:
        text = f"{it['title']} {it['summary']}"
        words = _has(INCIDENT_WORDS, text)
        if not words:
            continue
        for sid, t in terms.items():
            in_title = any(p.search(it["title"]) for p in t["patterns"])
            if sid in GIANTS:
                if not (in_title and _has(STRONG_WORDS, it["title"])):
                    continue
            elif not (in_title or any(p.search(it["summary"]) for p in t["patterns"])):
                continue
            leads.append({"id": hashlib.sha1(f"{it['link']}|{sid}".encode()).hexdigest()[:12],
                          "subprocessor_id": sid, "name": t["name"], "vendors": sorted(t["vendors"]),
                          "title": it["title"], "link": it["link"], "feed": it["feed"],
                          "published": it["published"], "words": words[:4]})
    return leads


def update(leads_path: Path, new: list[dict], today: str, watchlist_ids: set[str]) -> list[dict]:
    """Merge with stored leads (keep first_seen), drop ones older than KEEP_DAYS, write only on change."""
    old = json.loads(leads_path.read_text(encoding="utf-8")) if leads_path.exists() else []
    by_id = {l["id"]: l for l in old}
    for l in new:
        if l["id"] not in by_id:
            by_id[l["id"]] = {**l, "first_seen": today}
    cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=KEEP_DAYS)).isoformat()
    kept = [l for l in by_id.values() if l["first_seen"] >= cutoff]
    for l in kept:
        l["on_watchlist"] = l["subprocessor_id"] in watchlist_ids
    kept.sort(key=lambda l: (l["first_seen"], l.get("published") or "", l["id"]), reverse=True)
    if kept != old:
        leads_path.parent.mkdir(parents=True, exist_ok=True)
        leads_path.write_text(json.dumps(kept, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return kept


def run(feeds: list[dict], vendors: list[dict], incidents: list[dict], client, leads_path: Path,
        today: str) -> tuple[list[dict], list[str]]:
    """Fetch every feed (failures are reported, not fatal), match, store. Returns (leads, errors)."""
    terms = build_terms(vendors, incidents)
    items, errors = [], []
    for f in feeds:
        try:
            resp = client.get(f["url"])
            resp.raise_for_status()
            items += parse_feed(resp.content, f["name"])
        except Exception as exc:  # network, HTTP, malformed XML
            errors.append(f"{f['name']}: {type(exc).__name__}")
    leads = update(leads_path, match(items, terms), today, {i["subprocessor_id"] for i in incidents})
    return leads, errors
