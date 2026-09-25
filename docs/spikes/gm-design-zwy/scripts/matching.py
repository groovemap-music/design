#!/usr/bin/env python3
"""Matching unit, deterministic baseline, and the Semantica entity encoding.

Both catalogs' compact records (see the extract_* scripts) are reduced to one
``View``: the fields a matcher may use, each already normalized, with the source,
native id, entity kind, and master / release-group distinction kept alongside so no
comparison can silently collapse them. ``FIELDS`` names the ablation units.

The baseline is GrooveMap-style keyed blocking plus an additive, hand-set rule score.
Nothing here writes anywhere: a score is a candidate ranking, never an identity
assertion.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass, field

from normalize import (
    barcode_digits,
    barcode_key,
    catno_adr,
    catno_key,
    country_keys,
    format_family,
    name_key,
    title_key,
    year_of,
)

# "descriptors" is year, format family, and country together.
FIELDS = ("barcode", "catno", "title", "artist", "descriptors")
VARIOUS = {"various", "various artists"}


@dataclass(slots=True)
class View:
    source: str
    entity_kind: str
    native_id: str
    title_raw: str
    title: str
    artist_raw: str
    artists: frozenset[str]
    artist_ids: tuple
    barcodes_raw: tuple
    barcodes: frozenset[str]
    catnos_raw: tuple
    catnos: frozenset[str]
    labels_raw: tuple
    labels: frozenset[str]
    label_catnos: frozenset[tuple[str, str]]
    year: str | None
    formats: frozenset[str]
    countries: frozenset[str]
    master_id: str | None = None
    release_group: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.entity_kind}:{self.native_id}"


_EMPTY: frozenset = frozenset()


def _fs(values) -> frozenset:
    """Interned frozenset; the shared empty set keeps a million-row pool small."""
    out = frozenset(sys.intern(v) if isinstance(v, str) else v for v in values)
    return out if out else _EMPTY


def _artist_keys(names) -> frozenset[str]:
    keys = set()
    for n in names:
        k = name_key(n)
        if k:
            keys.add("various" if k in VARIOUS else k)
    return _fs(keys)


def view_of(rec: dict, keep_raw: bool = True) -> View:
    if rec["source"] == "musicbrainz":
        artists_raw = rec.get("artists") or []
        artist_raw = rec.get("artist_display") or " & ".join(artists_raw)
        barcodes_raw = (rec["barcode"],) if rec.get("barcode") else ()
        labels = rec.get("labels") or []
        formats = frozenset(f for f in (format_family(x) for x in rec.get("formats") or []) if f)
        year = year_of(rec.get("date"))
        artist_ids = tuple(rec.get("artist_ids") or ())
        master_id, rg = None, (rec.get("release_group") or {}).get("id")
        extra = {}
    else:
        artists_raw = [a.get("name") or "" for a in rec.get("artists") or []]
        artists_raw += [a["anv"] for a in rec.get("artists") or [] if a.get("anv")]
        artist_raw = "".join(
            (a.get("anv") or a.get("name") or "") + (f" {a['join']} " if a.get("join") else " ")
            for a in rec.get("artists") or []
        ).strip()
        barcodes_raw = tuple(rec.get("barcodes") or ())
        labels = rec.get("labels") or []
        formats = frozenset(f for f in (format_family(x.get("name")) for x in rec.get("formats") or []) if f)
        year = year_of(rec.get("released"))
        artist_ids = tuple(a.get("id") for a in rec.get("artists") or [])
        master_id, rg = rec.get("master_id"), None
        extra = {"artist_pairs": tuple(
            (sys.intern(name_key(a.get("name"))), a.get("id")) for a in rec.get("artists") or [] if a.get("name")
        )}
    label_catnos = set()
    for lb in labels:
        lk, ck = name_key(lb.get("name")), catno_key(lb.get("catno"))
        if lk and ck:
            label_catnos.add((lk, ck))
    if not keep_raw:
        # Only the Semantica raw-string encoding reads these; dropping them roughly
        # halves a large pool's footprint.
        artist_raw, artist_ids = "", ()
    return View(
        source=rec["source"],
        entity_kind=rec["entity_kind"],
        native_id=sys.intern(str(rec["native_id"])),
        title_raw=(rec.get("title") or "") if keep_raw else "",
        title=sys.intern(title_key(rec.get("title"))),
        artist_raw=artist_raw,
        artists=_artist_keys(artists_raw),
        artist_ids=artist_ids,
        barcodes_raw=barcodes_raw if keep_raw else (),
        barcodes=_fs(b for b in (barcode_key(x) for x in barcodes_raw) if b),
        catnos_raw=tuple(lb.get("catno") for lb in labels if lb.get("catno")) if keep_raw else (),
        catnos=_fs(c for c in (catno_key(lb.get("catno")) for lb in labels) if c),
        labels_raw=tuple(lb.get("name") for lb in labels if lb.get("name")) if keep_raw else (),
        labels=_fs(k for k in (name_key(lb.get("name")) for lb in labels) if k),
        label_catnos=_fs(label_catnos),
        year=year,
        formats=_fs(formats),
        countries=_fs(country_keys(rec.get("country"), rec["source"])),
        master_id=sys.intern(master_id) if master_id else None,
        release_group=rg,
        extra=extra,
    )


# --- deterministic baseline -------------------------------------------------------

@dataclass
class BaselineConfig:
    drop: frozenset[str] = frozenset()
    kind_aware: bool = True
    max_block: int = 2000  # a key shared by more candidates than this is a stop-key


class BaselineIndex:
    """Inverted indexes over the Discogs pool: barcode, catalogue number, and
    (title, artist) keys."""

    def __init__(self, pool: list[View]):
        self.pool = pool
        self.barcode: dict[str, list[int]] = defaultdict(list)
        self.catno: dict[str, list[int]] = defaultdict(list)
        self.title_artist: dict[tuple[str, str], list[int]] = defaultdict(list)
        self.title: dict[str, list[int]] = defaultdict(list)
        for i, v in enumerate(pool):
            for b in v.barcodes:
                self.barcode[b].append(i)
            for c in v.catnos:
                self.catno[c].append(i)
            if v.title:
                self.title[v.title].append(i)
                for a in v.artists:
                    self.title_artist[(v.title, a)].append(i)

    def block(self, q: View, cfg: BaselineConfig) -> tuple[set[int], dict]:
        """Return candidate pool indexes for a query and per-rule diagnostics."""
        out: set[int] = set()
        diag = {"stop_keys": 0}

        def add(ids: list[int]) -> None:
            if len(ids) > cfg.max_block:
                diag["stop_keys"] += 1
                return
            out.update(ids)

        if "barcode" not in cfg.drop:
            for b in q.barcodes:
                add(self.barcode.get(b, []))
        if "catno" not in cfg.drop:
            for c in q.catnos:
                add(self.catno.get(c, []))
        if "title" not in cfg.drop and "artist" not in cfg.drop:
            for a in q.artists:
                add(self.title_artist.get((q.title, a), []))
        elif "artist" in cfg.drop and "title" not in cfg.drop:
            # Without an artist the title key alone is the only name block left.
            add(self.title.get(q.title, []))
        if cfg.kind_aware:
            out = {i for i in out if self.pool[i].entity_kind == q.entity_kind}
        return out, diag


def _token_jaccard(a: str, b: str) -> float:
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def baseline_score(q: View, c: View, drop: frozenset[str] = frozenset()) -> float:
    """Additive rule score. Weights are hand-set to reflect identifier strength
    (a shared barcode outranks a shared catalogue number, which outranks a shared
    name) and were not fitted to the test split."""
    s = 0.0
    if "barcode" not in drop and q.barcodes & c.barcodes:
        s += 8
    if "catno" not in drop:
        if q.label_catnos & c.label_catnos:
            s += 4
        elif q.catnos & c.catnos:
            s += 2
    if "title" not in drop:
        if q.title and q.title == c.title:
            s += 3
        elif _token_jaccard(q.title, c.title) >= 0.5:
            s += 1
    if "artist" not in drop and q.artists & c.artists:
        s += 3
    if "descriptors" not in drop:
        if q.year and q.year == c.year:
            s += 1
        if q.formats & c.formats:
            s += 1
        if q.countries & c.countries:
            s += 1
    return s


# --- Semantica encoding -----------------------------------------------------------

def semantica_entity(v: View, drop: frozenset[str] = frozenset(), normalized: bool = True,
                     with_type: bool = True) -> dict:
    """Encode a View as a Semantica entity dict.

    ``name`` is the release title (Semantica's string component, 0.6 of the default
    weight, compares only ``name``). Identifiers and descriptors go in ``properties``;
    artist and label keys go in ``relationships`` (Jaccard). ``normalized=False``
    passes the raw source strings so Semantica's own lower()/strip() is the only
    normalization.
    """
    def first(values) -> str | None:
        values = sorted(x for x in values if x)
        return values[0] if values else None

    props: dict[str, str] = {}
    rels: list[dict] = []
    if "title" not in drop:
        name = v.title if normalized else v.title_raw
    else:
        name = ""
    if "artist" not in drop:
        artist = " ".join(sorted(v.artists)) if normalized else v.artist_raw
        if artist:
            props["artist"] = artist
        rels.extend({"artist": a} for a in sorted(v.artists))
    if "barcode" not in drop:
        b = first(v.barcodes) if normalized else first(barcode_digits(x) or x for x in v.barcodes_raw)
        if b:
            props["barcode"] = b
    if "catno" not in drop:
        c = first(v.catnos) if normalized else first(catno_adr(x) for x in v.catnos_raw)
        if c:
            props["catno"] = c
        lab = first(v.labels) if normalized else first(v.labels_raw)
        if lab:
            props["label"] = lab
        rels.extend({"label": lb} for lb in sorted(v.labels))
    if "descriptors" not in drop:
        if v.year:
            props["year"] = v.year
        fmt = first(v.formats)
        if fmt:
            props["format"] = fmt
        # Semantica compares a property as one scalar; the most specific country name
        # (the MusicBrainz side has one, a compound Discogs value its full spelling).
        ctry = max(v.countries, key=len) if v.countries else None
        if ctry:
            props["country"] = ctry
    ent = {"id": v.key, "name": name, "properties": props, "relationships": rels}
    if with_type:
        ent["type"] = v.entity_kind
    return ent
