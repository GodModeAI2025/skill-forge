"""Die Entscheidungsfunktion. Jeder Test hier pinnt einen Fehler aus v2.

Der zentrale Befund: in der alten Kaskade (SKILL.md:399-408) war der
NEUTRAL-Zweig unerreichbar. Über 4001 Deltas in [-0.20, +0.20] ergaben sich
KEEP 1800, REVERT 1500, NEAR_MISS 700 und NEUTRAL genau 1, nämlich bei Delta
exakt +0.02. NEAR_MISS fing das gesamte mittlere Band ab, und weil das
Plateau-Kriterium NEAR_MISS nicht mitzählte, brach ein Lauf im mittleren Band
nie ab.
"""

import json

import pytest

from scripts.composite_score import decide, is_plateau, load_thresholds


def test_keep_above_threshold():
    result = decide(0.84, 0.78)
    assert result["decision"] == "KEEP"
    assert result["near_miss"] is False


def test_revert_below_regression():
    result = decide(0.70, 0.80)
    assert result["decision"] == "REVERT"


def test_neutral_is_reachable_at_zero_delta():
    """Der Kern des alten Fehlers: NEUTRAL muss ein echtes Band abdecken."""
    result = decide(0.80, 0.80)
    assert result["decision"] == "NEUTRAL"
    assert result["delta"] == 0.0


def test_tie_is_not_a_keep():
    """Kein lateraler Zug. Sonst driftet der Loop über Null-Runden weg."""
    assert decide(0.5, 0.5)["decision"] != "KEEP"


def test_all_three_outcomes_reachable_across_the_band():
    outcomes = set()
    for i in range(-200, 201):
        delta = i / 1000.0
        outcomes.add(decide(0.50 + delta, 0.50)["decision"])
    assert outcomes == {"KEEP", "REVERT", "NEUTRAL"}


def test_neutral_band_is_not_a_single_point():
    """In v2 war NEUTRAL genau ein Punkt breit. Jetzt ist es ein Band."""
    neutrals = [
        i for i in range(-200, 201)
        if decide(0.50 + i / 1000.0, 0.50)["decision"] == "NEUTRAL"
    ]
    assert len(neutrals) > 50


def test_near_miss_is_a_flag_not_a_fourth_outcome():
    result = decide(0.81, 0.80)
    assert result["decision"] == "NEUTRAL"
    assert result["near_miss"] is True


def test_near_miss_only_below_the_keep_threshold():
    """Eine deutliche Verschlechterung ist kein Near-Miss."""
    result = decide(0.77, 0.80)
    assert result["decision"] == "NEUTRAL"
    assert result["near_miss"] is False


def test_noise_floor_raises_the_threshold():
    """Unterhalb der Rauschgrenze darf nichts mehr KEEP werden."""
    assert decide(0.84, 0.78)["decision"] == "KEEP"
    assert decide(0.84, 0.78, noise_floor=0.10)["decision"] == "NEUTRAL"


def test_noise_floor_below_improvement_changes_nothing():
    plain = decide(0.84, 0.78)
    with_floor = decide(0.84, 0.78, noise_floor=0.001)
    assert plain["decision"] == with_floor["decision"]
    assert with_floor["threshold"] == pytest.approx(0.02)


def test_lower_is_better_inverts_the_delta():
    """Bundle-Size von 120 auf 100 ist eine Verbesserung."""
    result = decide(100.0, 120.0, direction="lower_is_better", relative=True)
    assert result["decision"] == "KEEP"
    assert result["delta"] > 0


def test_lower_is_better_rejects_growth():
    result = decide(150.0, 120.0, direction="lower_is_better", relative=True)
    assert result["decision"] == "REVERT"


def test_unknown_direction_raises():
    with pytest.raises(ValueError):
        decide(1.0, 1.0, direction="sideways")


def test_relative_normalises_by_baseline():
    """Absolute Schwellen bedeuten nichts, wenn die Metrik in KB misst."""
    absolute = decide(1010.0, 1000.0)
    relative = decide(1010.0, 1000.0, relative=True)
    assert absolute["decision"] == "KEEP"      # +10 > 0.02, aber bedeutungslos
    assert relative["decision"] == "NEUTRAL"   # +1 Prozent, unter der Schwelle


def test_formula_is_human_readable():
    result = decide(0.84, 0.78)
    assert "0.8400" in result["formula"]
    assert "KEEP" in result["formula"]


def test_plateau_counts_every_non_keep():
    """NEAR_MISS und NEUTRAL zählen mit, sonst wird ein Plateau nie erkannt."""
    assert is_plateau(["KEEP", "NEUTRAL", "NEUTRAL", "NEUTRAL"]) is True
    assert is_plateau(["NEUTRAL", "REVERT", "NEUTRAL"]) is True
    assert is_plateau(["NEUTRAL", "NEUTRAL", "KEEP"]) is False
    assert is_plateau(["NEUTRAL", "NEUTRAL"]) is False


def test_config_beats_argparse_defaults(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "improvement_threshold": 0.10,
        "regression_threshold": 0.20,
        "noise_floor": 0.07,
    }))
    thresholds = load_thresholds(str(cfg))
    assert thresholds["improvement"] == 0.10
    assert thresholds["regression"] == 0.20
    assert thresholds["noise_floor"] == 0.07
    assert decide(0.84, 0.78, **thresholds)["decision"] == "NEUTRAL"


def test_missing_config_falls_back_to_defaults(tmp_path):
    thresholds = load_thresholds(str(tmp_path / "gibt-es-nicht.json"))
    assert thresholds["improvement"] == 0.02
    assert thresholds["regression"] == 0.05


# ─── SICHERHEIT: gefundene Fehler der ersten v3-Fassung ───────────────────


def test_nan_is_rejected_instead_of_becoming_neutral():
    """Mit NaN sind alle Vergleiche False, die Kaskade fiel still auf NEUTRAL.
    Ein kaputtes Scoring wurde damit als "kein Unterschied gemessen"
    protokolliert."""
    with pytest.raises(ValueError):
        decide(float("nan"), 0.80)
    with pytest.raises(ValueError):
        decide(0.80, float("nan"))
    with pytest.raises(ValueError):
        decide(float("inf"), 0.80)


def test_relative_with_zero_baseline_does_not_explode():
    """Die Division durch 1e-10 erzeugte Deltas der Groessenordnung 1e10 und
    damit garantiert KEEP, etwa bei der Metrik "0 Lint-Fehler"."""
    result = decide(0.001, 0.0, relative=True)
    assert result["relative_fallback"] is True
    assert abs(result["delta"]) < 1.0
    assert result["decision"] == "NEUTRAL"


def test_relative_fallback_is_visible_in_the_formula():
    result = decide(0.001, 0.0, relative=True)
    assert "Baseline ist 0" in result["formula"]


def test_relative_with_normal_baseline_has_no_fallback():
    result = decide(110.0, 100.0, relative=True)
    assert result["relative_fallback"] is False
    assert result["delta"] == pytest.approx(0.10)
