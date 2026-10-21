"""Forgiving readers for values in downloaded CSV files.

Every function returns None for anything it cannot read: an empty cell, text that is not a
number, infinity, or NaN. A CSV row with fewer fields than the header makes the reader give
None for the missing cells, so None is accepted as input too.
"""

import math


def words(text: str | None) -> str:
    """Text with runs of whitespace collapsed to single spaces; empty for None."""
    return " ".join((text or "").split())


def number(text: str | None) -> float | None:
    """A finite number, or None."""
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def positive(text: str | None) -> float | None:
    """A finite number above zero, or None."""
    value = number(text)
    return value if value is not None and value > 0 else None


def integer(text: str | None) -> int | None:
    """A whole number written with the digits 0 to 9 only, or None."""
    if text is None:
        return None
    text = text.strip()
    return int(text) if text.isascii() and text.isdigit() else None


def prefixed_integer(text: str | None, prefix: str) -> int | None:
    """The number in text such as "Gaia DR3 1234" or "HIP 70890", or None."""
    if text is None:
        return None
    text = text.strip()
    return integer(text.removeprefix(prefix)) if text.startswith(prefix) else None
