#!/usr/bin/env python3
"""GrooveMap-style normalization and blocking keys for release-edition matching.

The identifier rules follow ADR 0011's alias namespaces: barcodes keep their digits
only, catalogue numbers are upper-cased with internal whitespace collapsed. Two
spike-local extensions are layered on top and named as such, never folded into the
ADR rule silently:

- ``barcode_key`` also widens a 12-digit UPC-A to its 13-digit EAN form (a leading
  zero), so the same printed code entered as UPC on one side and EAN on the other
  lands in one block.
- ``catno_key`` also drops punctuation and spaces (``SK 032`` / ``SK-032`` /
  ``SK032`` block together). ``catno_adr`` is the unextended ADR 0011 value.

Name folding (NFKD, drop combining marks, casefold, strip the Discogs `` (N)``
disambiguator) is the same rule gm-design-chw.3 and gm-design-e0b.1 use.
``script_of`` is copied from gm-design-e0b.1's ``script_util.py`` (same design
repository, bead gm-design-e0b.1) so this harness has no runtime dependency on
that worktree.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

DISCOGS_DISAMBIGUATOR = re.compile(r"\s*\(\d+\)$")
_WS = re.compile(r"\s+")
# Values both catalogs use to say "there is no catalogue number".
_NO_CATNO = {"NONE", "NA", "N/A", "NOCATNO", "NOTONLABEL", "UNKNOWN", ""}


def strip_disambiguator(name: str | None) -> str:
    return DISCOGS_DISAMBIGUATOR.sub("", name or "")


def fold(text: str | None) -> str:
    """NFKD-fold, drop combining marks, casefold, turn punctuation/symbols into
    spaces, collapse whitespace."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    out = []
    for ch in decomposed:
        if unicodedata.combining(ch):
            continue
        cat = unicodedata.category(ch)
        out.append(" " if cat[0] in ("P", "S") else ch)
    return _WS.sub(" ", "".join(out).casefold()).strip()


def name_key(name: str | None) -> str:
    """Artist or label name key: Discogs disambiguator stripped, then folded."""
    return fold(strip_disambiguator(name))


def title_key(title: str | None) -> str:
    return fold(title)


def barcode_digits(value: str | None) -> str:
    """ADR 0011 barcode namespace rule: digits only."""
    return "".join(c for c in (value or "") if c.isdigit())


def barcode_key(value: str | None) -> str | None:
    digits = barcode_digits(value)
    if len(digits) == 14 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 12:
        digits = "0" + digits
    if len(digits) not in (8, 13):
        return None
    if set(digits) == {"0"}:
        return None
    return digits


def catno_adr(value: str | None) -> str:
    """ADR 0011 catalogue-number namespace rule: upper-case, collapse whitespace."""
    return _WS.sub(" ", (value or "").upper()).strip()


def catno_key(value: str | None) -> str | None:
    compact = "".join(c for c in catno_adr(value) if c.isalnum())
    if compact in _NO_CATNO or len(compact) < 2:
        return None
    return compact


def year_of(date: str | None) -> str | None:
    m = re.match(r"(\d{4})", date or "")
    if not m or m.group(1) == "0000":
        return None
    return m.group(1)


_FORMAT_FAMILIES = (
    ("vinyl", ("vinyl", "lp", "7\"", "10\"", "12\"", "acetate", "flexi", "shellac", "lathe")),
    ("cd", ("cd", "sacd", "hdcd", "blu-spec", "shm-cd", "minidisc")),
    ("digital", ("digital", "file", "download")),
    ("cassette", ("cassette", "tape", "8-track", "reel", "dat", "dcc")),
    ("video", ("dvd", "blu-ray", "vhs", "laserdisc", "vcd", "umd")),
)


def format_family(fmt: str | None) -> str | None:
    f = (fmt or "").casefold()
    if not f:
        return None
    for family, needles in _FORMAT_FAMILIES:
        if any(n in f for n in needles):
            return family
    return "other"


# MusicBrainz release countries are ISO 3166 codes plus XE (Europe) and XW
# (Worldwide); Discogs uses English names, sometimes compound ("UK & Europe"). Both
# map onto the Discogs spelling. Unmapped values give no signal rather than a guess.
_MB_COUNTRY = {
    "US": "us", "GB": "uk", "DE": "germany", "FR": "france", "JP": "japan", "NL": "netherlands",
    "XE": "europe", "SE": "sweden", "CA": "canada", "AU": "australia", "IT": "italy", "FI": "finland",
    "BE": "belgium", "ES": "spain", "XW": "worldwide", "RU": "russia", "DK": "denmark", "NO": "norway",
    "PL": "poland", "AT": "austria", "CH": "switzerland", "BR": "brazil", "NZ": "new zealand",
    "AR": "argentina", "CZ": "czech republic", "GR": "greece", "IL": "israel", "PT": "portugal",
    "TR": "turkey", "ZA": "south africa", "HU": "hungary", "MX": "mexico", "IE": "ireland",
    "HK": "hong kong", "RO": "romania", "YU": "yugoslavia", "SK": "slovakia", "KR": "south korea",
    "EE": "estonia", "SI": "slovenia", "LV": "latvia", "IS": "iceland", "TW": "taiwan", "CL": "chile",
    "UA": "ukraine", "JM": "jamaica", "SU": "ussr", "XC": "czechoslovakia", "CS": "serbia and montenegro",
    "RS": "serbia", "HR": "croatia", "BG": "bulgaria", "LT": "lithuania", "CO": "colombia",
    "VE": "venezuela", "PH": "philippines", "MY": "malaysia", "SG": "singapore", "IN": "india",
    "CN": "china", "TH": "thailand", "ID": "indonesia", "PE": "peru", "UY": "uruguay",
}
_COUNTRY_SPLIT = re.compile(r"\s*(?:,|&|\band\b)\s*")


def country_keys(value: str | None, source: str) -> frozenset[str]:
    if not value:
        return frozenset()
    if source == "musicbrainz":
        name = _MB_COUNTRY.get(value.upper())
        return frozenset({name}) if name else frozenset()
    v = value.casefold().strip()
    return frozenset({v} | {p for p in _COUNTRY_SPLIT.split(v) if p})


# --- script classifier, copied from gm-design-e0b.1 scripts/script_util.py -----

BLOCKS: tuple[tuple[int, int, str], ...] = (
    (0x0041, 0x024F, "latin"),
    (0x1E00, 0x1EFF, "latin"),
    (0x0370, 0x03FF, "greek"),
    (0x1F00, 0x1FFF, "greek"),
    (0x0400, 0x04FF, "cyrillic"),
    (0x0500, 0x052F, "cyrillic"),
    (0x0590, 0x05FF, "hebrew"),
    (0x0600, 0x06FF, "arabic"),
    (0x0750, 0x077F, "arabic"),
    (0xFB50, 0xFDFF, "arabic"),
    (0xFE70, 0xFEFF, "arabic"),
    (0x0900, 0x097F, "devanagari"),
    (0x0E00, 0x0E7F, "thai"),
    (0x3040, 0x309F, "japanese_kana"),
    (0x30A0, 0x30FF, "japanese_kana"),
    (0xAC00, 0xD7A3, "korean_hangul"),
    (0x1100, 0x11FF, "korean_hangul"),
    (0x4E00, 0x9FFF, "han"),
    (0x3400, 0x4DBF, "han"),
    (0xF900, 0xFAFF, "han"),
)


def block_of(ch: str) -> str | None:
    cp = ord(ch)
    for lo, hi, label in BLOCKS:
        if lo <= cp <= hi:
            return label
    return None


def script_of(name: str | None) -> str:
    counts: Counter[str] = Counter()
    has_alpha = False
    for ch in name or "":
        if not ch.isalpha():
            continue
        has_alpha = True
        counts[block_of(ch) or "other_non_latin"] += 1
    if not has_alpha:
        return "unknown"
    return counts.most_common(1)[0][0]


def script_bucket(name: str | None) -> str:
    s = script_of(name)
    return s if s in ("latin", "unknown") else "non_latin"
