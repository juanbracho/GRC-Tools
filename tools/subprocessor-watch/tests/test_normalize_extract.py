from pathlib import Path

import pytest

from subprocessor_watch.__main__ import load_config
from subprocessor_watch.extract import ExtractError, extract, merge_duplicates
from subprocessor_watch.normalize import slugify, subprocessor_id

FIX = Path(__file__).parent / "fixtures"
VENDORS, ALIASES = load_config()
BY_ID = {v["vendor_id"]: v for v in VENDORS}


@pytest.mark.parametrize("name, slug", [
    ("Amazon Web Services, Inc.", "amazon-web-services"),
    ("Amazon Web Services Inc (AWS)", "amazon-web-services"),
    ("Amazon Web Services EMEA SARL", "amazon-web-services"),
    ("OpenAI, L.L.C.", "openai"),
    ("Anthropic, PBC", "anthropic"),
    ("Tray.io", "trayio"),
    ("Atlassian B.V.", "atlassian"),
    ("Soluções Ltda.", "solucoes"),
])
def test_slugify(name, slug):
    assert slugify(name) == slug


def test_aliases_map_variants_to_one_id():
    assert subprocessor_id("AWS", ALIASES) == "amazon-web-services"
    assert subprocessor_id("OpenAI OpCo, LLC", ALIASES) == "openai"
    assert subprocessor_id("Google Cloud Platform (GCP)", ALIASES) == "google"


@pytest.mark.parametrize("vendor_id, unique", [
    ("github", 23), ("atlassian", 25), ("asana", 16), ("openai", 16), ("hubspot", 18), ("figma", 44),
    ("zoom", 22), ("airtable", 23), ("stripe", 34), ("cloudflare", 12), ("monday", 27),
    # rendered in a browser (Vanta trust centers, Notion); fixtures saved after rendering
    ("anthropic", 22), ("fathom", 30), ("granola", 17), ("notion", 29)])
def test_real_page_fixtures(vendor_id, unique):
    rows = extract((FIX / f"{vendor_id}.html").read_text(encoding="utf-8"), BY_ID[vendor_id], ALIASES)
    merged = merge_duplicates(rows)
    assert len(merged) == unique
    assert {"amazon-web-services", "google"} & merged.keys()  # every vendor runs on a big cloud
    # No header text or category labels leaked in as companies.
    assert not any(k in merged for k in ("name-of-subprocessor", "sub-processor", "entity-name",
                                         "hosting-and-infrastructure-service"))


def test_asana_skips_affiliates_and_updates_tables():
    merged = merge_duplicates(extract((FIX / "asana.html").read_text(encoding="utf-8"), BY_ID["asana"], ALIASES))
    assert not any(k.startswith("asana") for k in merged)
    assert not any("changed" in (e["name_as_listed"] or "").lower() for e in merged.values())


def test_atlassian_skips_continuation_rows():
    merged = merge_duplicates(extract((FIX / "atlassian.html").read_text(encoding="utf-8"), BY_ID["atlassian"], ALIASES))
    assert not any(k.startswith("applicable-cloud-products") for k in merged)


def test_duplicates_merge_purposes():
    rows = [
        {"subprocessor_id": "anthropic", "name_as_listed": "Anthropic, PBC", "purpose": "LLM", "location": "US"},
        {"subprocessor_id": "anthropic", "name_as_listed": "Anthropic, PBC", "purpose": "Support AI", "location": "US"},
        {"subprocessor_id": "anthropic", "name_as_listed": "Anthropic, PBC", "purpose": "LLM", "location": "US"},
    ]
    assert merge_duplicates(rows)["anthropic"]["purpose"] == "LLM; Support AI"
    assert merge_duplicates(rows)["anthropic"]["location"] == "US"


def test_missing_table_is_a_parse_error():
    with pytest.raises(ExtractError):
        extract("<html><h2>We redesigned!</h2><p>no tables</p></html>", BY_ID["github"], ALIASES)


def test_every_configured_vendor_has_a_fixture():
    assert {v["vendor_id"] for v in VENDORS} <= {p.stem for p in FIX.glob("*.html")}


def test_nth_table_header_cells_and_multi_column_location():
    html = """<html><h2>Subs</h2>
    <table><tr><td>Name</td><td>Purpose</td><td>US</td><td>EU</td></tr>
           <tr><td>Acme Inc.</td><td>Hosting</td><td>United States</td><td>Germany</td></tr>
           <tr><td>Beta</td><td>Email</td><td>United States</td><td>United States</td></tr></table>
    <table><tr><td>Our Own Entity Ltd</td><td>x</td><td>y</td><td>z</td></tr></table></html>"""
    vendor = {"tables": [{"heading": "Subs", "nth": 0, "columns": {"name": 0, "purpose": 1, "location": [2, 3]}}]}
    merged = merge_duplicates(extract(html, vendor, {}))
    assert list(merged) == ["acme", "beta"]  # "Name" header row and the 2nd table skipped
    assert merged["acme"]["location"] == "United States; Germany"
    assert merged["beta"]["location"] == "United States"  # duplicates within a row dropped


def test_tables_without_heading_by_position():
    html = "<table><tr><th>Sub</th></tr><tr><td>Acme</td></tr></table><table><tr><td>Other</td></tr></table>"
    merged = merge_duplicates(extract(html, {"tables": [{"nth": 1, "columns": {"name": 0}}]}, {}))
    assert list(merged) == ["other"]


def test_hubspot_unnamed_ai_provider_is_kept_as_listed():
    merged = merge_duplicates(extract((FIX / "hubspot.html").read_text(encoding="utf-8"), BY_ID["hubspot"], ALIASES))
    assert merged["ai-service-provider"]["name_as_listed"] == "AI Service Provider"


def test_notion_reads_all_sections_but_not_own_entities():
    merged = merge_duplicates(extract((FIX / "notion.html").read_text(encoding="utf-8"), BY_ID["notion"], ALIASES))
    assert {"customerio", "fivetran", "mailgun-technologies"} <= merged.keys()          # Business Operations (behind a toggle)
    assert not any(k.startswith("notion-labs") for k in merged)  # Notion's own companies skipped
