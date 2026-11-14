"""Pull the subprocessor rows out of a vendor's HTML page.

Each vendor's config says which tables to read (by the heading above them)
and which column holds the name, purpose and location. Rows with fewer
cells than the table's header (category labels, continuation rows) are skipped.
"""

from bs4 import BeautifulSoup

from .normalize import clean_text, subprocessor_id


class ExtractError(Exception):
    """The page no longer looks like the config expects (parser broke)."""


def _cell_text(cell) -> str:
    for br in cell.find_all("br"):
        br.replace_with(" ")
    return cell.get_text(" ", strip=True)


# Header rows some pages write as ordinary cells instead of <th>.
_HEADER_WORDS = {"name", "entity", "entity name", "sub-processor", "sub‑processor", "subprocessor",
                 "sub-processors", "subprocessors", "vendor", "third party"}


def _find_tables(soup, spec: dict):
    """Tables under a heading containing spec['heading'] (or all tables if no heading),
    optionally narrowed to the nth match (0-based) when a heading covers several tables."""
    wanted = (spec.get("heading") or "").lower()
    found = []
    for table in soup.find_all("table"):
        if wanted:
            h = table.find_previous(["h1", "h2", "h3", "h4", "h5"])
            if not (h and wanted in h.get_text(" ", strip=True).lower()):
                continue
        found.append(table)
    if "nth" in spec:
        return found[spec["nth"]:spec["nth"] + 1]
    return found


def _column(texts: list[str], col) -> str | None:
    """A column is an index or a list of indexes (joined with '; ', duplicates dropped)."""
    idxs = col if isinstance(col, list) else [col]
    values = []
    for i in idxs:
        v = clean_text(texts[i]) if i < len(texts) else None
        if v and v not in values:
            values.append(v)
    return "; ".join(values) or None


def extract(html: str, vendor: dict, aliases: dict[str, str]) -> list[dict]:
    """Return one raw row per subprocessor listed (duplicates not merged yet)."""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict] = []
    for spec in vendor["tables"]:
        tables = _find_tables(soup, spec)
        if not tables:
            raise ExtractError(f"no table matching {spec.get('heading')!r} (nth={spec.get('nth')})")
        cols = spec["columns"]
        min_cells = spec.get("min_cells", cols["name"] + 1)
        for table in tables:
            continuation = 0  # rows still covered by a merged (rowspan) name cell above
            for tr in table.find_all("tr"):
                cells = tr.find_all(["td", "th"])
                if continuation:
                    continuation -= 1
                    continue  # extra row of the company above (its name cell spans down)
                if not cells or all(c.name == "th" for c in cells):
                    continue  # header row
                name_cell = cells[cols["name"]] if cols["name"] < len(cells) else None
                if name_cell is not None:
                    try:
                        continuation = max(int(name_cell.get("rowspan") or 1), 1) - 1
                    except ValueError:
                        continuation = 0
                if len(cells) < min_cells:
                    continue  # category label or continuation row
                texts = [_cell_text(c) for c in cells]
                name = clean_text(texts[cols["name"]])
                if not name or name.lower().rstrip(":") in _HEADER_WORDS:
                    continue
                rows.append({
                    "subprocessor_id": subprocessor_id(name, aliases),
                    "name_as_listed": name,
                    "purpose": _column(texts, cols["purpose"]) if "purpose" in cols else None,
                    "location": _column(texts, cols["location"]) if "location" in cols else None,
                })
    return rows


def merge_duplicates(rows: list[dict]) -> dict[str, dict]:
    """One entry per subprocessor_id; several purposes/locations are joined with '; '."""
    merged: dict[str, dict] = {}
    for row in rows:
        sid = row["subprocessor_id"]
        if sid not in merged:
            merged[sid] = dict(row)
            continue
        entry = merged[sid]
        for field in ("purpose", "location"):
            new = row[field]
            if new and new not in (entry[field] or "").split("; "):
                entry[field] = f"{entry[field]}; {new}" if entry[field] else new
    return merged
