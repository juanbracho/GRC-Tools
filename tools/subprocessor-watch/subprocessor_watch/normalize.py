"""Turn the many ways a company name is written into one stable ID.

"Amazon Web Services, Inc.", "Amazon Web Services Inc (AWS)" and
"Amazon Web Services EMEA SARL" should all become ``amazon-web-services``.
"""

import re
import unicodedata

# Legal-entity words that don't identify the company itself.
_LEGAL_SUFFIXES = {
    "inc", "incorporated", "llc", "l.l.c", "ltd", "limited", "plc", "pbc", "corp",
    "corporation", "co", "company", "gmbh", "ag", "bv", "b.v", "nv", "sa", "sas",
    "sarl", "s.a.r.l", "srl", "spa", "ab", "as", "oy", "pty", "kk", "kft", "sro",
    "llp", "lp", "ulc", "ltda", "pte", "sl", "kg", "emea", "the",
}

_PARENS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_NON_ALNUM = re.compile(r"[^a-z0-9.]+")


def clean_text(text: str | None) -> str | None:
    """Collapse whitespace; empty becomes None (shared-schema rule)."""
    if text is None:
        return None
    text = " ".join(text.split())
    return text or None


def slugify(name: str) -> str:
    """Company name -> lowercase slug without legal suffixes or bracketed notes."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = _PARENS.sub(" ", text.lower())
    text = text.replace("&", " and ")
    words = [w.strip(".") for w in _NON_ALNUM.split(text)]
    words = [w for w in words if w and w not in _LEGAL_SUFFIXES and w.replace(".", "") not in _LEGAL_SUFFIXES]
    return "-".join(w.replace(".", "") for w in words if w.replace(".", ""))


def subprocessor_id(name: str, aliases: dict[str, str]) -> str:
    """Slug, then map known aliases (e.g. ``aws`` -> ``amazon-web-services``)."""
    slug = slugify(name)
    return aliases.get(slug, slug)
