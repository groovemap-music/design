"""The lifecycle rule on invented yearly series."""
import numpy as np

from lifecycle import ABSENT, DECLINING, EMERGING, ESTABLISHED, REVIVING, Rule, flip_share, stages


def series(*values):
    return np.array([values], dtype=float)


def test_rise_plateau_decline_revival():
    counts = series(0, 0, 10, 20, 30, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 10, 5, 5, 5, 5, 20, 30, 30)
    s = stages(counts, Rule(window=1))[0]
    assert s[0] == ABSENT and s[1] == ABSENT
    assert s[3] == EMERGING  # cum 30 >= 25 first at index 3
    assert s[13] == ESTABLISHED  # 10 years after emergence
    assert s[15] == DECLINING  # 10 < 0.5 * 40
    assert s[19] == DECLINING
    assert s[20] == ESTABLISHED  # 20 >= 0.5 * 40 again
    s2 = stages(series(0, 0, 10, 20, 30, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 4, 4, 4, 12, 4), Rule(window=1))[0]
    assert s2[17] == DECLINING and s2[18] == REVIVING  # 12 >= 1.5 * 4 and >= 0.25 * 40


def test_causal():
    counts = np.array([[0, 5, 30, 30, 30, 0, 0, 0]], dtype=float)
    full = stages(counts)
    for y in range(1, counts.shape[1]):
        assert (stages(counts[:, : y + 1])[0] == full[0, : y + 1]).all()


def test_perturbed_rules_scale_one_threshold_each():
    names = [name for name, _ in Rule().perturbed(1.1)]
    assert names == ["emerge_total", "active_share", "establish_years", "revive_ratio", "revive_floor"]
    eleven = dict(Rule().perturbed(1.1))["establish_years"]
    nine = dict(Rule().perturbed(0.9))["establish_years"]
    assert (eleven.establish_years, nine.establish_years) == (11.0, 9.0)


def test_flip_share_ignores_cells_absent_on_both_sides():
    a = np.array([[ABSENT, EMERGING, ESTABLISHED]])
    b = np.array([[ABSENT, EMERGING, DECLINING]])
    assert flip_share(a, b) == 0.5
