#!/usr/bin/env python3
"""Score baseline candidate sets without breaking any tie.

gm-design-zwy ranked equal scores by id, and on linked data the linked target is the
lowest Discogs id in 87-91% of tie groups, so its recall@1 partly measured how the data
was linked. ADR 0014 section 4 bans that. Every metric here is a function of score
groups only:

- ``unique_top_recall@1``: the target is the only candidate at the top score;
- ``expected_recall@k``: the probability the target is in the first k under a uniformly
  random order within its score group (it gives 1/g credit for a target in a top group
  of g), which is what any tie-break unrelated to the edition would achieve on average;
- ``guaranteed_recall@k``: the target is in the first k under every order within its
  group (the pessimistic bound);
- ``top_group_recall``: the target is in the top score group.

Ambiguity follows ADR 0014 section 4, by field equality rather than score equality: two
candidates are indistinguishable when their comparison vectors (``matching.comparison``)
are equal, meaning they agree with the query on exactly the same fields at the same
level. A stricter variant also requires equal normalized *values* on every field the
query carries.

Nothing here reads the order of the candidate list or compares ids to rank. The one
place ids are compared is ``lowest_id_in_tie_groups``, a diagnostic that measures how
much an id tie-break *would* inflate recall on this population; it feeds no metric.

Usage:
    python3 evaluate.py --queries queries_test.jsonl --later later_records.jsonl.gz \
        --pool pool_releases.jsonl.gz pool_masters.jsonl.gz \
        --run baseline_test=runs/baseline_test.jsonl.gz --thresholds 6,8,10,12 --out metrics.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import statistics
from collections import Counter, defaultdict

from matching import View, view_of
from normalize import barcode_key, catno_key, country_keys, format_family, script_bucket, title_key, year_of

CLASSES = (
    "shared_barcode",
    "near_identical_title",
    "sibling_same_format",
    "sibling_diff_format",
    "namesake_artist",
)
AGREEMENT_FIELDS = ("barcode", "catno", "title", "year", "country", "format", "artist")


def iter_jsonl(path: str):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as f:
        for line in f:
            yield json.loads(line)


def load_jsonl(path: str) -> list[dict]:
    return list(iter_jsonl(path))


def pct(num: float, den: float) -> float | None:
    return round(100.0 * num / den, 2) if den else None


def summarize(values: list[int]) -> dict:
    if not values:
        return {"mean": 0, "median": 0, "p95": 0, "max": 0}
    s = sorted(values)
    return {
        "mean": round(statistics.fmean(s), 2),
        "median": s[len(s) // 2],
        "p95": s[min(len(s) - 1, int(0.95 * len(s)))],
        "max": s[-1],
    }


# --- tie-aware ranking ------------------------------------------------------------

def target_position(row: dict) -> tuple[int, int] | None:
    """(candidates strictly above the target, size of the target's score group), or
    None when the target was not generated. Order-free by construction."""
    tkey = f"discogs:release:{row['target']}"
    tscore = next((c[1] for c in row["candidates"] if c[0] == tkey), None)
    if tscore is None:
        return None
    above = sum(1 for c in row["candidates"] if c[1] > tscore)
    tied = sum(1 for c in row["candidates"] if c[1] == tscore)
    return above, tied


def expected_hit(pos: tuple[int, int] | None, k: int) -> float:
    if pos is None:
        return 0.0
    above, tied = pos
    return min(1.0, max(0.0, (k - above) / tied))


def expected_rr(pos: tuple[int, int] | None) -> float:
    if pos is None:
        return 0.0
    above, tied = pos
    return sum(1.0 / r for r in range(above + 1, above + tied + 1)) / tied


def top_group(row: dict) -> list[list]:
    if not row["candidates"]:
        return []
    top = max(c[1] for c in row["candidates"])
    return [c for c in row["candidates"] if c[1] == top]


def id_order_rank(row: dict) -> int | None:
    """Diagnostic only: the rank zwy's id-order tie-break would have given the target,
    to put this population's numbers on zwy's footing. Feeds no metric."""
    pos = target_position(row)
    if pos is None:
        return None
    tkey = f"discogs:release:{row['target']}"
    tscore = next(c[1] for c in row["candidates"] if c[0] == tkey)
    lower = sum(1 for c in row["candidates"] if c[1] == tscore and c[0] < tkey)
    return pos[0] + lower + 1


def lowest_id_in_tie(row: dict) -> bool | None:
    """Diagnostic only: in a top tie that contains the target, is the target the lowest
    Discogs id? None when the question does not apply."""
    group = top_group(row)
    tkey = f"discogs:release:{row['target']}"
    if len(group) < 2 or tkey not in {c[0] for c in group}:
        return None
    ids = [int(c[0].rsplit(":", 1)[1]) for c in group if c[0].startswith("discogs:release:")]
    return int(row["target"]) == min(ids)


# --- ADR 0014 section 4 ambiguity -------------------------------------------------

def carried(q: View) -> tuple[str, ...]:
    out = []
    if q.barcodes:
        out.append("barcode")
    if q.label_catnos or q.catnos:
        out.append("catno")
    if q.title:
        out.append("title")
    if q.artists:
        out.append("artist")
    if q.year:
        out.append("year")
    if q.formats:
        out.append("format")
    if q.countries:
        out.append("country")
    return tuple(out)


def value_projection(c: View, fields: tuple[str, ...]) -> tuple:
    get = {
        "barcode": lambda v: v.barcodes, "catno": lambda v: (v.label_catnos, v.catnos),
        "title": lambda v: v.title, "artist": lambda v: v.artists, "year": lambda v: v.year,
        "format": lambda v: v.formats, "country": lambda v: v.countries,
    }
    return tuple(get[f](c) for f in fields)


def groups_of(cands: list[list], q: View | None, views: dict[str, View], strict: bool) -> dict:
    """Partition candidates into ADR 0014 section 4 groups: equal comparison vector, and
    for ``strict`` also equal values on every field the query carries."""
    fields = carried(q) if (strict and q is not None) else ()
    out: dict[tuple, list[str]] = defaultdict(list)
    for key, _score, vec in cands:
        k = (tuple(vec),)
        if strict:
            v = views.get(key)
            k += (value_projection(v, fields) if v is not None else (key,),)
        out[k].append(key)
    return out


# --- per-run evaluation -----------------------------------------------------------

def evaluate_run(rows: list[dict], views: dict[str, View], qviews: dict[str, View], present: dict,
                 thresholds: list[float], qmeta: dict[str, dict]) -> dict:
    n = len(rows)
    reachable = [r for r in rows if f"discogs:release:{r['target']}" in views]
    res: dict = {"n": n, "target_in_pool": len(reachable), "target_missing_from_dump": n - len(reachable)}
    for label, rs in (("all", rows), ("reachable", reachable)):
        m = len(rs)
        pos = [target_position(r) for r in rs]
        block = {
            "n": m,
            "coverage_pct": pct(sum(1 for p in pos if p), m),
            "unique_top_recall@1_pct": pct(sum(1 for p in pos if p and p == (0, 1)), m),
            "top_group_recall_pct": pct(sum(1 for p in pos if p and p[0] == 0), m),
            # Of the queries whose top score is held by one candidate, how often it is
            # the target: the precision a "unique top" auto-accept would have.
            "unique_top_queries": sum(1 for r in rs if len(top_group(r)) == 1),
            "unique_top_precision_pct": pct(sum(1 for p in pos if p == (0, 1)),
                                            sum(1 for r in rs if len(top_group(r)) == 1)),
            "expected_mrr": round(sum(expected_rr(p) for p in pos) / m, 4) if m else None,
        }
        for k in (1, 5, 10):
            block[f"expected_recall@{k}_pct"] = pct(sum(expected_hit(p, k) for p in pos), m)
            block[f"guaranteed_recall@{k}_pct"] = pct(sum(1 for p in pos if p and p[0] + p[1] <= k), m)
        res[label] = block
    res["candidates_per_query"] = summarize([len(r["candidates"]) for r in rows])
    res["zero_candidate_queries"] = sum(1 for r in rows if not r["candidates"])
    res["stop_key_queries"] = sum(1 for r in rows if r.get("diag", {}).get("stop_keys"))
    res["tied_top_queries"] = sum(1 for r in rows if len(top_group(r)) > 1)
    res["target_in_tied_top"] = sum(1 for r in rows if (p := target_position(r)) and p[0] == 0 and p[1] > 1)
    lows = [x for x in (lowest_id_in_tie(r) for r in rows) if x is not None]
    res["diagnostic_lowest_id_in_tie_groups"] = {
        "tie_groups_with_target": len(lows),
        "target_is_lowest_id": sum(lows),
        "pct": pct(sum(lows), len(lows)),
        "note": "diagnostic only: how often an id-order tie-break would pick the target; feeds no metric",
    }
    id_ranks = [id_order_rank(r) for r in reachable]
    res["diagnostic_id_order_reachable"] = {
        f"recall@{k}_pct": pct(sum(1 for x in id_ranks if x and x <= k), len(reachable)) for k in (1, 5, 10)
    }

    # Section 4 ambiguity of the leading group and of the target's own group.
    amb = {"queries_with_candidates": 0}
    for strict in (False, True):
        tag = "strict_values" if strict else "comparison_vector"
        lead_amb = target_amb = target_amb_top = 0
        for r in rows:
            if not r["candidates"]:
                continue
            q = qviews.get(r["q"])
            top = top_group(r)
            lead = groups_of(top, q, views, strict)
            if any(len(m) > 1 for m in lead.values()):
                lead_amb += 1
            tkey = f"discogs:release:{r['target']}"
            for members in groups_of(r["candidates"], q, views, strict).values():
                if tkey in members and len(members) > 1:
                    target_amb += 1
                    if tkey in {c[0] for c in top}:
                        target_amb_top += 1
        amb[tag] = {
            "leading_group_ambiguous": lead_amb,
            "target_in_ambiguous_group": target_amb,
            "target_in_ambiguous_top_group": target_amb_top,
        }
    amb["queries_with_candidates"] = sum(1 for r in rows if r["candidates"])
    for tag in ("comparison_vector", "strict_values"):
        a = amb[tag]
        a["leading_group_ambiguous_pct"] = pct(a["leading_group_ambiguous"], amb["queries_with_candidates"])
        a["target_in_ambiguous_top_group_pct"] = pct(a["target_in_ambiguous_top_group"], n)
    res["ambiguity"] = amb

    review = {}
    for t in thresholds:
        queue, gqueue, conf = [], [], Counter()
        hits = ghits = 0
        amb_groups = 0
        for r in rows:
            inq = [c for c in r["candidates"] if c[1] >= t]
            queue.append(len(inq))
            groups = groups_of(inq, qviews.get(r["q"]), views, strict=False)
            gqueue.append(len(groups))
            amb_groups += sum(1 for m in groups.values() if len(m) > 1)
            pos = target_position(r)
            tkey = f"discogs:release:{r['target']}"
            in_queue = any(c[0] == tkey for c in inq)
            hits += in_queue
            ghits += in_queue
            if in_queue and pos == (0, 1):
                conf["unique_top_is_correct"] += 1
            elif in_queue and pos[0] == 0:
                conf["correct_in_tied_top"] += 1
            elif in_queue:
                conf["correct_in_queue_below_top"] += 1
            elif inq:
                conf["only_wrong_candidates"] += 1
            else:
                conf["empty_queue"] += 1
        total, gtotal = sum(queue), sum(gqueue)
        review[str(t)] = {
            "queue_per_query": summarize(queue),
            "queue_groups_per_query": summarize(gqueue),
            "false_positives_per_query": round((total - hits) / n, 3) if n else None,
            "precision_of_queue_pct": pct(hits, total),
            "precision_of_queue_groups_pct": pct(ghits, gtotal),
            "ambiguous_groups_in_queue_pct": pct(amb_groups, gtotal),
            "target_in_queue_pct": pct(hits, n),
            "confusion": {k: conf[k] for k in ("unique_top_is_correct", "correct_in_tied_top",
                                                "correct_in_queue_below_top", "only_wrong_candidates",
                                                "empty_queue")},
        }
    res["review"] = review

    hard = {cls: {"queries_with_class_in_pool": 0, "outranks_target": 0, "ties_target": 0,
                  "in_top_group": 0} for cls in CLASSES}
    for r in rows:
        pres = present.get(r["q"], {})
        for cls in CLASSES:
            if pres.get(cls):
                hard[cls]["queries_with_class_in_pool"] += 1
        tkey = f"discogs:release:{r['target']}"
        t = views.get(tkey)
        pos = target_position(r)
        if t is None:
            continue
        tscore = next((c[1] for c in r["candidates"] if c[0] == tkey), None)
        top = max((c[1] for c in r["candidates"]), default=None)
        above, tie, attop = set(), set(), set()
        for key, score, _vec in r["candidates"]:
            c = views.get(key)
            if c is None or key == tkey:
                continue
            classes = classify(c, t)
            if pos is None or score > tscore:
                above |= classes
            elif score == tscore:
                tie |= classes
            if score == top:
                attop |= classes
        for cls in above:
            hard[cls]["outranks_target"] += 1
        for cls in tie:
            hard[cls]["ties_target"] += 1
        for cls in attop:
            hard[cls]["in_top_group"] += 1
    res["hard_negatives"] = hard

    slices = defaultdict(list)
    for r in rows:
        m = qmeta[r["q"]]
        for name in ("script", "barcode_on_query", "catno_on_query", "format", "decade"):
            slices[f"{name}={m[name]}"].append(r)
    res["slices"] = {}
    for name, rs in sorted(slices.items()):
        pos = [target_position(r) for r in rs]
        res["slices"][name] = {
            "n": len(rs),
            "coverage_pct": pct(sum(1 for p in pos if p), len(rs)),
            "unique_top_recall@1_pct": pct(sum(1 for p in pos if p == (0, 1)), len(rs)),
            "expected_recall@1_pct": pct(sum(expected_hit(p, 1) for p in pos), len(rs)),
            "expected_recall@10_pct": pct(sum(expected_hit(p, 10) for p in pos), len(rs)),
            "target_in_pool": sum(1 for r in rs if f"discogs:release:{r['target']}" in views),
        }
    return res


def classify(c: View, t: View) -> set[str]:
    """Hard-negative classes a non-target release falls in, relative to the target.
    zwy's classes minus release-vs-master, which kind-aware blocking never generates."""
    out: set[str] = set()
    if c.entity_kind == "master" or c.native_id == t.native_id:
        return out
    if c.barcodes & t.barcodes:
        out.add("shared_barcode")
    if t.master_id and c.master_id == t.master_id:
        if (c.formats & t.formats) or (not c.formats and not t.formats):
            out.add("sibling_same_format")
        else:
            out.add("sibling_diff_format")
    elif c.title and c.title == t.title:
        out.add("near_identical_title")
    t_ids: dict[str, set] = defaultdict(set)
    for name, aid in t.extra.get("artist_pairs", ()):
        t_ids[name].add(aid)
    for name, aid in c.extra.get("artist_pairs", ()):
        if name in t_ids and name != "various" and aid not in t_ids[name]:
            out.add("namesake_artist")
            break
    return out


# --- copy bias --------------------------------------------------------------------

def field_values(v: View) -> dict:
    return {"barcode": v.barcodes, "catno": v.catnos, "title": v.title, "year": v.year,
            "country": v.countries, "format": v.formats, "artist": v.artists}


def agrees(a, b) -> bool:
    if isinstance(a, frozenset):
        return bool(a & b)
    return a == b


def field_agreement(qviews: dict[str, View], targets: dict[str, str], views: dict[str, View]) -> dict:
    """zwy's copy-bias measure: among queries whose target exists, how often each field
    agrees with the target where both sides carry it."""
    out = {f: {"both_carry": 0, "equal": 0} for f in AGREEMENT_FIELDS}
    for mbid, q in qviews.items():
        t = views.get(f"discogs:release:{targets[mbid]}")
        if t is None:
            continue
        qv, tv = field_values(q), field_values(t)
        for f in AGREEMENT_FIELDS:
            if qv[f] and tv[f]:
                out[f]["both_carry"] += 1
                out[f]["equal"] += agrees(qv[f], tv[f])
    for f in out.values():
        f["equal_pct"] = pct(f["equal"], f["both_carry"])
    return out


def edit_census(early: list[dict], later_path: str) -> dict:
    """What editors changed on the query releases between the two snapshots, per field:
    added (absent before), changed, removed. Edits made alongside the link are exactly
    the copy the time-split keeps out of the query."""
    later = {r["native_id"]: r for r in iter_jsonl(later_path)}
    keyers = {
        "barcode": lambda r: barcode_key(r.get("barcode")),
        "catno": lambda r: frozenset(filter(None, (catno_key(li.get("catno")) for li in r.get("labels") or []))),
        "title": lambda r: title_key(r.get("title")),
        "year": lambda r: year_of(r.get("date")),
        "country": lambda r: frozenset(country_keys(r.get("country"), "musicbrainz")),
        "format": lambda r: frozenset(filter(None, (format_family(x) for x in r.get("formats") or []))),
    }
    out = {f: Counter() for f in keyers}
    n = 0
    for r in early:
        lr = later.get(r["native_id"])
        if lr is None:
            continue
        n += 1
        for f, key in keyers.items():
            a, b = key(r), key(lr)
            if a == b:
                continue
            out[f]["added" if not a else "removed" if not b else "changed"] += 1
    return {"queries": n, **{f: {**dict(c), "any_pct": pct(sum(c.values()), n)} for f, c in out.items()}}


# --- loading ----------------------------------------------------------------------

def load_pool(pool_paths: list[str]) -> dict:
    views: dict[str, View] = {}
    idx = {"barcode": defaultdict(list), "master": defaultdict(list), "title": defaultdict(list)}
    for path in pool_paths:
        for rec in iter_jsonl(path):
            v = view_of(rec, keep_raw=False)
            views[v.key] = v
            for b in v.barcodes:
                idx["barcode"][b].append(v.key)
            if v.master_id:
                idx["master"][v.master_id].append(v.key)
            if v.title:
                idx["title"][v.title].append(v.key)
    return {"views": views, "idx": idx}


def decade_of(date: str | None) -> str:
    y = year_of(date)
    if not y:
        return "none"
    return "pre1980" if int(y) < 1980 else f"{y[:3]}0s" if int(y) < 2020 else "2020s"


def query_context(qrecs: list[dict], pool: dict) -> dict:
    views, idx = pool["views"], pool["idx"]
    qviews = {r["native_id"]: view_of(r) for r in qrecs}
    qmeta = {}
    for r in qrecs:
        fams = sorted({format_family(x) for x in r.get("formats") or []} - {None})
        qmeta[r["native_id"]] = {
            "script": script_bucket(r["title"]),
            "barcode_on_query": "yes" if barcode_key(r.get("barcode")) else "no",
            "catno_on_query": "yes" if any(catno_key(li.get("catno")) for li in r.get("labels") or []) else "no",
            "format": fams[0] if len(fams) == 1 else ("none" if not fams else "mixed"),
            "decade": decade_of(r.get("date")),
        }
    present: dict[str, dict[str, int]] = {}
    for r in qrecs:
        t = views.get(f"discogs:release:{r['target_discogs_id']}")
        if t is None:
            continue
        near = set()
        for b in t.barcodes:
            near.update(idx["barcode"][b])
        if t.master_id:
            near.update(idx["master"][t.master_id])
        near.update(idx["title"][t.title])
        counts = Counter()
        for key in near:
            for cls in classify(views[key], t):
                counts[cls] += 1
        present[r["native_id"]] = dict(counts)
    return {"qviews": qviews, "qmeta": qmeta, "present": present,
            "targets": {r["native_id"]: r["target_discogs_id"] for r in qrecs}}


def evaluate_runs(pool: dict, qctx: dict, runs: dict[str, list[dict]], thresholds: list[float]) -> dict:
    return {"runs": {name: evaluate_run(rows, pool["views"], qctx["qviews"], qctx["present"], thresholds,
                                        qctx["qmeta"]) for name, rows in runs.items()}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", required=True)
    ap.add_argument("--later")
    ap.add_argument("--pool", nargs="+", required=True)
    ap.add_argument("--run", action="append", required=True, help="name=path")
    ap.add_argument("--thresholds", default="4,6,8,9,10,11,12,13,14")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    qrecs = load_jsonl(args.queries)
    pool = load_pool(args.pool)
    qctx = query_context(qrecs, pool)
    runs = {name: load_jsonl(path) for name, path in (s.split("=", 1) for s in args.run)}
    out = evaluate_runs(pool, qctx, runs, [float(x) for x in args.thresholds.split(",")])
    out["field_agreement"] = field_agreement(qctx["qviews"], qctx["targets"], pool["views"])
    if args.later:
        out["edit_census"] = edit_census(qrecs, args.later)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    for name, res in out["runs"].items():
        print(name, json.dumps(res["reachable"]))


if __name__ == "__main__":
    main()
