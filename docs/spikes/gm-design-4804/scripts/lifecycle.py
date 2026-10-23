"""Lifecycle stages over yearly release counts: the rule, and its stability measures.

The rule is causal: the stage of a style in year ``y`` reads only counts from years up to
``y``, so the Genre Atlas can scrub valid time without knowing the future.

    c(y)   trailing mean of the yearly count over ``window`` years ending at y
    cum(y) releases up to and including y
    y0     first year with cum >= emerge_total
    P(y)   max of c over years <= y (the peak so far)
    T(y)   min of c since the last year the style was active (the trough)

    absent       y < y0
    emerging     c >= active_share * P and y - y0 <  establish_years
    established  c >= active_share * P and y - y0 >= establish_years
    reviving     c <  active_share * P and c >= revive_ratio * T and c >= revive_floor * P
    declining    otherwise

Every threshold is a field of :class:`Rule`, so a +/-10% sensitivity run is a
``dataclasses.replace`` of one field.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace

import numpy as np

ABSENT, EMERGING, ESTABLISHED, DECLINING, REVIVING = range(5)
STAGES = ("absent", "emerging", "established", "declining", "reviving")


@dataclass(frozen=True)
class Rule:
    emerge_total: float = 25.0
    active_share: float = 0.5
    establish_years: float = 10.0
    revive_ratio: float = 1.5
    revive_floor: float = 0.25
    window: int = 3  # fixed smoothing, not a stage threshold

    def perturbed(self, scale: float) -> list[tuple[str, "Rule"]]:
        """One rule per threshold, that threshold scaled by ``scale`` (window excluded).

        ``establish_years`` is a whole number of years, so it is rounded to the nearest
        year away from the base (10 * 0.9 = 9, 10 * 1.1 = 11).
        """
        out = []
        for f in fields(self):
            if f.name == "window":
                continue
            value = getattr(self, f.name) * scale
            if f.name == "establish_years":
                value = float(np.floor(value) if scale < 1 else np.ceil(value))
            out.append((f.name, replace(self, **{f.name: value})))
        return out


def trailing_mean(counts: np.ndarray, window: int) -> np.ndarray:
    """Mean over the ``window`` years ending at each year (fewer at the start)."""
    csum = np.cumsum(counts, axis=-1, dtype=np.float64)
    out = csum.copy()
    out[..., window:] = csum[..., window:] - csum[..., :-window]
    n = np.minimum(np.arange(1, counts.shape[-1] + 1), window)
    return out / n


def stages(counts: np.ndarray, rule: Rule = Rule()) -> np.ndarray:
    """Stage per (row, year) for an R x Y matrix of yearly counts."""
    counts = np.asarray(counts, dtype=np.float64)
    rows, years = counts.shape
    c = trailing_mean(counts, rule.window)
    cum = np.cumsum(counts, axis=1)
    emerged = cum >= rule.emerge_total
    y0 = np.where(emerged.any(axis=1), emerged.argmax(axis=1), years)
    peak = np.maximum.accumulate(c, axis=1)
    out = np.full((rows, years), ABSENT, dtype=np.int8)
    trough = np.full(rows, np.inf)
    for y in range(years):
        live = y >= y0
        active = live & (c[:, y] >= rule.active_share * peak[:, y])
        young = (y - y0) < rule.establish_years
        out[active & young, y] = EMERGING
        out[active & ~young, y] = ESTABLISHED
        trough = np.where(active | ~live, np.inf, np.minimum(trough, c[:, y]))
        low = live & ~active
        reviving = low & (c[:, y] >= rule.revive_ratio * trough) & (c[:, y] >= rule.revive_floor * peak[:, y])
        out[low & ~reviving, y] = DECLINING
        out[reviving, y] = REVIVING
    return out


def flip_share(a: np.ndarray, b: np.ndarray, mask: np.ndarray | None = None) -> float:
    """Share of cells whose stage differs, among cells where either side is not absent."""
    considered = (a != ABSENT) | (b != ABSENT)
    if mask is not None:
        considered &= mask
    n = int(considered.sum())
    return float(((a != b) & considered).sum() / n) if n else 0.0


def stage_histogram(s: np.ndarray) -> dict[str, int]:
    return {name: int((s == i).sum()) for i, name in enumerate(STAGES)}


def parent_order_violations(first: np.ndarray, parent_first: list[np.ndarray]) -> int:
    """Rows that emerge before at least one parent has emerged (the B edge rule)."""
    n = 0
    for f, parents in zip(first, parent_first):
        if len(parents) and f < parents.max():
            n += 1
    return n
