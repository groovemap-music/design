#!/usr/bin/env python3
"""Shared Unicode-script classifier for gm-design-e0b.1.

Unlike gm-design-chw.3's binary latin/non_latin split (adequate there because
non-Latin was one thin slice among many), this spike's whole query population
is non-Latin by construction, so "sliced by script" (acceptance criterion)
needs a finer breakdown -- otherwise it collapses to a single row. Classifies
by the dominant Unicode block among a name's alphabetic characters.
"""
from __future__ import annotations

# (low, high, label) -- checked in order; first match wins per character.
BLOCKS: tuple[tuple[int, int, str], ...] = (
    (0x0041, 0x024F, "latin"),   # Basic Latin + Latin-1 Supplement + Extended A/B
    (0x1E00, 0x1EFF, "latin"),   # Latin Extended Additional
    (0x0370, 0x03FF, "greek"),
    (0x1F00, 0x1FFF, "greek"),   # Greek Extended
    (0x0400, 0x04FF, "cyrillic"),
    (0x0500, 0x052F, "cyrillic"),  # Cyrillic Supplement
    (0x0590, 0x05FF, "hebrew"),
    (0x0600, 0x06FF, "arabic"),
    (0x0750, 0x077F, "arabic"),   # Arabic Supplement
    (0xFB50, 0xFDFF, "arabic"),   # Arabic Presentation Forms-A
    (0xFE70, 0xFEFF, "arabic"),   # Arabic Presentation Forms-B
    (0x0900, 0x097F, "devanagari"),
    (0x0E00, 0x0E7F, "thai"),
    (0x3040, 0x309F, "japanese_kana"),  # Hiragana
    (0x30A0, 0x30FF, "japanese_kana"),  # Katakana
    (0xAC00, 0xD7A3, "korean_hangul"),
    (0x1100, 0x11FF, "korean_hangul"),  # Hangul Jamo
    (0x4E00, 0x9FFF, "han"),      # CJK Unified Ideographs (zh/ja/ko shared)
    (0x3400, 0x4DBF, "han"),      # CJK Extension A
    (0xF900, 0xFAFF, "han"),      # CJK Compatibility Ideographs
)


def block_of(ch: str) -> str | None:
    cp = ord(ch)
    for lo, hi, label in BLOCKS:
        if lo <= cp <= hi:
            return label
    return None


def script_of(name: str) -> str:
    """Return the dominant script label for a name, or 'latin'/'unknown'."""
    from collections import Counter

    counts: Counter[str] = Counter()
    has_alpha = False
    for ch in name or "":
        if not ch.isalpha():
            continue
        has_alpha = True
        label = block_of(ch)
        counts[label or "other_non_latin"] += 1
    if not has_alpha:
        return "unknown"
    return counts.most_common(1)[0][0]


def is_non_latin(name: str) -> bool:
    s = script_of(name)
    return s not in ("latin", "unknown")
