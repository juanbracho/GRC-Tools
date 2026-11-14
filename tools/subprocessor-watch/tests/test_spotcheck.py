from subprocessor_watch.spotcheck import check

VENDOR = {"vendor_id": "acme", "tables": [{"heading": "Subprocessors", "columns": {"name": 0}}]}
INC = [{"subprocessor_id": "fireworks-ai", "name": "Fireworks AI"}]


def test_clean_page_has_no_warnings():
    html = "<h2>Subprocessors</h2><table><tr><th>Name</th></tr><tr><td>AWS</td></tr></table>"
    assert check(html, VENDOR, {}, INC)["warnings"] == []


def test_flags_unread_table_and_watchlist_mention():
    html = ("<h2>Subprocessors</h2><table><tr><th>Name</th></tr><tr><td>AWS</td></tr></table>"
            "<h2>More vendors (collapsed)</h2><table><tr><th>Name</th></tr><tr><td>Customer.io</td></tr>"
            "<tr><td>Fivetran</td></tr></table><p>We also use Fireworks AI for some features.</p>")
    w = check(html, VENDOR, {}, INC)["warnings"]
    assert any("table 1 not read" in x for x in w)
    assert any("Fireworks AI" in x for x in w)


def test_failed_extraction_is_reported():
    assert "extract failed" in check("<p>redesigned</p>", VENDOR, {}, [])["warnings"][0]


def test_reviewed_skip_silences_known_tables():
    html = ("<h2>Subprocessors</h2><table><tr><th>Name</th></tr><tr><td>AWS</td></tr></table>"
            "<h2>Our entities</h2><table><tr><th>Entity</th></tr><tr><td>Acme Ltd</td></tr><tr><td>Acme GmbH</td></tr></table>")
    assert check(html, {**VENDOR, "reviewed_skip": [1]}, {}, [])["warnings"] == []
    assert check(html, VENDOR, {}, [])["warnings"]
