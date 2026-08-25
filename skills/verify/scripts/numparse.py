"""Number recognition: displayed value -> parsed value, precision, envelope,
unit and scale.

Vendored from summationai/alg extractor/numparse.py. Do not invent a second
number parser.

`displayed_precision` and `rounding_envelope` are the load-bearing outputs.
Every arithmetic check downstream is only as good as these two, so the rules
are spelled out rather than inferred:

*   `displayed_precision` is the count of decimal digits **actually rendered**
    in the literal, after stripping sign, currency symbol, parentheses,
    thousands separators and any scale or unit suffix.
    ``$1,240`` -> 0. ``41.9%`` -> 1. ``1.32%`` -> 2. ``$1.2M`` -> 1.
*   `rounding_envelope` is the largest absolute error the display can hide,
    expressed in units of `value_parsed`:
    ``0.5 * 10 ** -displayed_precision * scale_factor``.
    ``$1,240`` -> 0.5. ``41.9%`` -> 0.05. ``$1.2M`` -> 50000.0.

A declared scale is applied to `value_parsed`. Whether the underlying values
honour the declaration is a downstream check, not an extraction decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# Unicode minus (U+2212) and en dash (U+2013) are both used as minus signs in
# rendered analyst output. Treat them as such; never as a hyphen.
MINUSES = "-−–"
CURRENCY_SYMBOLS = {"$": "USD", "£": "GBP", "€": "EUR"}

# Longest first: "percentage points" must win over "percent".
UNIT_SUFFIXES = [
    ("percentage points", "points"),
    ("percentage point", "points"),
    ("basis points", "basis_points"),
    ("basis point", "basis_points"),
    ("percent", "percent"),
    ("points", "points"),
    ("point", "points"),
    ("pts", "points"),
    ("pt", "points"),
    ("bps", "basis_points"),
    ("cents", "currency"),
    ("cent", "currency"),
    ("units", "units"),
    ("unit", "units"),
    ("weeks", "weeks"),
    ("week", "weeks"),
    ("days", "days"),
    ("day", "days"),
]

SCALE_FACTOR = {
    "ones": 1.0,
    "thousands": 1e3,
    "millions": 1e6,
    "billions": 1e9,
    "unknown": 1.0,
}

_SUFFIX_ALT = "|".join(re.escape(s) for s, _ in UNIT_SUFFIXES)

NUM_RE = re.compile(
    r"""
    (?P<open>\()?
    (?P<sign1>[+\-−–])?\s?
    (?P<cur>[$£€])?
    (?P<sign2>[+\-−–])?
    (?P<int>\d{1,3}(?:,\d{3})+|\d+)
    (?:\.(?P<frac>\d+))?
    (?P<mag>[MKkBb](?![A-Za-z]))?
    (?P<close>\))?
    (?:\s?(?P<pct>%))?
    (?P<close2>\))?
    (?:\s(?P<suffix>""" + _SUFFIX_ALT + r""")\b)?
    """,
    re.VERBOSE,
)

# Patterns masked out before number scanning, because they are calendar
# references rather than measured quantities. Masking preserves offsets.
_DATE_PATTERNS = [
    re.compile(r"\d{4}-\d{2}-\d{2}"),
    re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\b"),
    re.compile(
        r"\b\d{1,2}\s+(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+\d{4}\b"),
    re.compile(
        r"\b(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},?\s+\d{4}\b"),
    re.compile(r"\b(19|20)\d{2}W\d{1,2}\b"),
]
_BARE_YEAR_RE = re.compile(
    r"(?<![\d,.$£€])\b(?:19|20)\d{2}\b(?![,.]?\d)(?!\s*%)")

MASK_CHAR = "\x00"

SPELLED = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}
_TENS = {"twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty",
         "ninety"}
_SPELLED_RE = re.compile(
    r"\b(" + "|".join(sorted(SPELLED, key=len, reverse=True)) + r")"
    r"(?:[-\s](" + "|".join(sorted(SPELLED, key=len, reverse=True)) + r"))?\b",
    re.IGNORECASE,
)


def mask_calendar(text: str):
    """Replace date/time literals with NULs, preserving length and offsets.

    Returns ``(masked_text, count)``.
    """
    chars = list(text)
    count = 0

    def blank(m):
        nonlocal count
        for i in range(m.start(), m.end()):
            chars[i] = MASK_CHAR
        count += 1

    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            blank(m)
    partial = "".join(chars)
    for m in _BARE_YEAR_RE.finditer(partial):
        blank(m)
    return "".join(chars), count


@dataclass
class NumberToken:
    """One recognised numeric literal inside a run of text."""

    start: int
    end: int
    value_displayed: str
    value_parsed: Optional[float]
    displayed_precision: Optional[int]
    unit: str
    scale: str
    scale_source: str
    currency_code: Optional[str] = None
    #: `major` (dollars), `minor` (cents), or None when the literal does not say.
    #:
    #: Only ever set from evidence in the literal itself: a `cents` suffix, or a currency symbol.
    #: A currency unit inherited from a column header is deliberately left as None, because the
    #: header says which *quantity* the column holds and not which denomination it is written in
    #: — and guessing `major` there is precisely the assumption this field exists to prevent.
    #: Consumers read an absent value as `major`, which is what they did before this field was
    #: emitted at all, so an omission changes nothing and claims nothing.
    denomination: Optional[str] = None
    is_null_marker: bool = False
    spelled: bool = False
    parenthesised_negative: bool = False
    notes: list = field(default_factory=list)

    @property
    def value_in_major_units(self):
        """``value_parsed`` converted to the major unit, when the denomination is known."""
        if self.value_parsed is None or self.unit != "currency":
            return self.value_parsed
        if self.denomination == "minor":
            return self.value_parsed / 100.0
        return self.value_parsed

    @property
    def rounding_envelope(self):
        return envelope_for(self.displayed_precision, self.scale)


def envelope_for(precision, scale="ones"):
    """Maximum absolute error the display can hide, in units of value_parsed."""
    if precision is None:
        return None
    return 0.5 * (10.0 ** -precision) * SCALE_FACTOR.get(scale, 1.0)


def precision_of(literal: str):
    """Decimal places rendered in a numeric literal.

    Accepts the literal with or without sign, currency, separators, scale
    suffix and unit suffix. Returns ``None`` if no digits are present.
    """
    m = re.search(r"\d(?:[\d,]*\d)?(?:\.(\d+))?", literal)
    if not m:
        return None
    return len(m.group(1)) if m.group(1) else 0


def _scale_from_mag(mag):
    if not mag:
        return None
    return {"K": "thousands", "k": "thousands", "M": "millions",
            "B": "billions", "b": "billions"}.get(mag)


def parse_match(m, text, header_scale=None, header_scale_source=None,
                header_unit=None, currency_default="USD"):
    """Turn a NUM_RE match into a NumberToken, or None if it should be skipped."""
    g = m.groupdict()
    intpart = g["int"]
    frac = g["frac"]
    mag = g["mag"]
    pct = g["pct"]
    suffix = g["suffix"]
    cur = g["cur"]
    sign = g["sign1"] or g["sign2"] or ""
    # Accounting parentheses mean "negative" only when no sign is printed.
    # "(−3.5%)" is a bracketed negative, not a double negative.
    closed = bool(g["close"] or g["close2"])
    paren_neg = bool(g["open"] and closed and not sign)

    # A bare integer glued to letters ("1P", "3P", "26in") is an identifier,
    # not a measurement.
    if not (cur or pct or suffix or mag or frac):
        nxt = text[m.end():m.end() + 1]
        if nxt.isalpha():
            return None

    literal = m.group(0)
    # Trim a trailing space that the suffix group may have absorbed oddly.
    value_displayed = literal.strip()

    digits = intpart.replace(",", "")
    numeric = float(digits)
    if frac:
        numeric = float(digits + "." + frac)
    negative = (sign in MINUSES and sign != "") or paren_neg
    if negative:
        numeric = -numeric

    precision = len(frac) if frac else 0

    # ---- unit ------------------------------------------------------------
    unit = None
    currency_code = None
    if suffix:
        smap = dict(UNIT_SUFFIXES)
        unit = smap[suffix.lower()]
        if unit == "currency":
            currency_code = currency_default
    elif pct:
        unit = "percent"
    elif cur:
        unit = "currency"
        currency_code = CURRENCY_SYMBOLS.get(cur, currency_default)
    elif header_unit:
        unit = header_unit
        if unit == "currency":
            currency_code = currency_default
    else:
        unit = "unknown"

    # ---- scale -----------------------------------------------------------
    # An inline magnitude suffix always wins. A header or caption scale
    # declaration only governs the unit it was written about: "($000)" and
    # "Whole dollars" are statements about money, not about percentages,
    # point moves or unit counts.
    mag_scale = _scale_from_mag(mag)
    # "($000)" and "Whole dollars" are declarations about money. Applying them
    # to unit counts, ranks or rates would manufacture a declaration the
    # document never made.
    scalable = unit in ("currency", "index", "unknown")
    if mag_scale:
        scale, scale_source = mag_scale, "inline_suffix"
    elif header_scale and scalable:
        scale = header_scale
        scale_source = header_scale_source or "column_header"
    else:
        scale, scale_source = "ones", "absent"

    value_parsed = numeric * SCALE_FACTOR.get(scale, 1.0)

    # ---- denomination ----------------------------------------------------
    # Written only from evidence in the literal. `34 cents` and `$42.96` both parse to a plain
    # number, and a consumer that reads the first as dollars is wrong by a factor of a hundred
    # with no symptom at all — the arithmetic simply disagrees and blames the wrong figure.
    # A currency unit inherited from a column header says which quantity the column holds, not
    # which denomination it is written in, so those stay unset rather than guessing `major`.
    denomination = None
    if unit == "currency":
        if suffix and suffix.lower().startswith(("cent", "pence")):
            denomination = "minor"
        elif cur:
            denomination = "major"

    tok = NumberToken(
        start=m.start(), end=m.end(),
        value_displayed=value_displayed,
        value_parsed=value_parsed,
        displayed_precision=precision,
        unit=unit, scale=scale, scale_source=scale_source,
        currency_code=currency_code,
        denomination=denomination,
        parenthesised_negative=paren_neg,
    )
    if denomination == "minor":
        tok.notes.append(
            "displayed in cents; value_parsed is the displayed magnitude, and "
            "denomination=minor is what converts it")
    return tok


def iter_numbers(text, header_scale=None, header_scale_source=None,
                 header_unit=None, require_marker=False, mask_dates=True):
    """Yield NumberTokens found in ``text``.

    ``require_marker`` keeps only numbers carrying a currency symbol, a percent
    sign, a unit suffix or a magnitude suffix. Used inside cells that are
    mostly prose, where a bare integer is usually part of a name.
    """
    scan = text
    if mask_dates:
        scan, _ = mask_calendar(text)
    pos = 0
    while pos < len(scan):
        m = NUM_RE.search(scan, pos)
        if not m:
            break
        pos = max(m.end(), m.start() + 1)
        if not m.group("int"):
            continue
        if require_marker and not (m.group("cur") or m.group("pct")
                                   or m.group("suffix") or m.group("mag")):
            continue
        tok = parse_match(m, scan, header_scale, header_scale_source,
                          header_unit)
        if tok is None:
            continue
        # Report the *rendered* literal from the unmasked text.
        tok.value_displayed = text[tok.start:tok.end].strip()
        yield tok


_SPELLED_UNIT_TAIL = ("-week", " weeks", " week", "-day", " days", " day",
                      " percent", " points", " point")


def iter_spelled(text):
    """Yield NumberTokens for spelled-out cardinals ("sixty-two", "three").

    Cardinals below two are skipped unless they carry an explicit unit word.
    "a pricing one" and "every one of" are pronouns, not quantities, and
    claiming a value of 1 for them would be inventing a number.
    """
    for m in _SPELLED_RE.finditer(text):
        w1 = m.group(1).lower()
        w2 = (m.group(2) or "").lower()
        if w2 and w1 in _TENS and SPELLED.get(w2, 99) < 10:
            value = SPELLED[w1] + SPELLED[w2]
            end = m.end()
        elif w2 and w1 not in _TENS:
            value = SPELLED[w1]
            end = m.end(1)
        else:
            value = SPELLED[w1]
            end = m.end(1) if not (w2 and w1 in _TENS) else m.end()
        tail = text[end:end + 12].lower()
        unit = "unknown"
        for word in _SPELLED_UNIT_TAIL:
            if tail.startswith(word):
                unit = {"-week": "weeks", " weeks": "weeks", " week": "weeks",
                        "-day": "days", " days": "days", " day": "days",
                        " percent": "percent", " points": "points",
                        " point": "points"}[word]
                end = end + len(word)
                break
        if value < 2 and unit == "unknown":
            continue
        yield NumberToken(
            start=m.start(), end=end,
            value_displayed=text[m.start():end],
            value_parsed=float(value),
            displayed_precision=0,
            unit=unit, scale="ones", scale_source="absent",
            spelled=True,
            notes=["spelled-out cardinal"],
        )


NULL_MARKERS = {"—", "–", "-", "n/a", "N/A", "na", "——", ""}


def is_null_marker(cell_text: str) -> bool:
    t = cell_text.strip()
    return t in NULL_MARKERS or t.lower() in {"n/a", "na", "none", "null"}
