"""Small security helpers: spreadsheet formula-injection protection and filename sanitising."""
from __future__ import annotations

import re
from typing import Any

from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")
_PHONE_LIKE = re.compile(r"\+?[\d\s().\-]{7,}")  # "+1 (555) 123-4567" is data, not a formula


def sanitize_cell(value: Any) -> Any:
    """Make a value safe to write to a spreadsheet cell.

    * strings that could be interpreted as a formula (=, +, -, @, tab, CR) get a leading apostrophe
      so Excel/LibreOffice treat them as text (OWASP "CSV injection" guidance);
    * characters that are illegal in XML (and make openpyxl raise) are removed."""
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    text = ILLEGAL_CHARACTERS_RE.sub("", text)
    if text.startswith(_FORMULA_PREFIXES) and not _PHONE_LIKE.fullmatch(text):
        text = "'" + text
    if len(text) > 32000:  # Excel hard limit is 32,767 chars per cell
        text = text[:32000] + "…"
    return text


def safe_display_filename(name: str | None, fallback: str = "upload") -> str:
    """Strip any path components/control characters from a user-supplied filename (display only -
    uploads are always stored under a random server-generated name)."""
    if not name:
        return fallback
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
    return name[:200] or fallback
