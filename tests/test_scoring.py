"""Scoring. Pinnt zwei gemessene Fehler aus v2.

1. Ein leeres Experiment-Verzeichnis lieferte
   {"composite_score": 0.2, "assertion_pass_rate": 0.0, "efficiency_score": 1.0},
   weil calc_efficiency_score(0, 0.0) genau 1.0 ergibt. Ein Lauf, der nichts
   protokolliert hatte, bekam perfekte Effizienz.
2. score_from_experiment_dir sammelte per rglob alle grading.json unterhalb des
   Experiment-Verzeichnisses ein, also with_mutation UND baseline. Der
   berechnete Score war der Mittelwert über beide Seiten.
"""

import json

import pytest

from scripts.composite_score import (
    GATE_WEIGHTS_COMPARATOR,
    GATE_WEIGHTS_PLAIN,
    NoGradingDataError,
    NoJudgeDataError,
    calc_composite_score,
    calc_efficiency_score,
    load_gate_weights,
    load_use_comparator,
    score_from_experiment_dir,
)


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _experiment(tmp_path, mutation=(5, 5), baseline=(1, 5), timings=True):
    exp = tmp_path / "exp-001"
    for eval_id in range(2):
        for side, (passed, total) in (
            ("with_mutation", mutation), ("baseline", baseline)
        ):
            run = exp / "runs" / ("eval-%d" % eval_id) / side
            _write(run / "grading.json", {"summary": {"passed": passed, "total": total}})
            if timings:
                _write(run / "timing.json", {
                    "total_tokens": 20000, "total_duration_seconds": 60,
                })
    return exp


def test_empty_directory_raises_instead_of_scoring_020(tmp_path):
    empty = tmp_path / "exp-leer"
    empty.mkdir()
    with pytest.raises(NoGradingDataError):
        score_from_experiment_dir(str(empty))


def test_side_filter_separates_candidate_from_baseline(tmp_path):
    exp = _experiment(tmp_path, mutation=(5, 5), baseline=(1, 5))
    mutated = score_from_experiment_dir(str(exp), side="with_mutation")
    base = score_from_experiment_dir(str(exp), side="baseline")
    assert mutated["assertion_pass_rate"] == pytest.approx(1.0)
    assert base["assertion_pass_rate"] == pytest.approx(0.2)
    assert mutated["details"]["grading_files_found"] == 2
    assert base["details"]["grading_files_found"] == 2


def test_without_side_both_sides_are_mixed(tmp_path):
    """Dokumentiert das alte Verhalten als Grund für den Pflicht-Parameter."""
    exp = _experiment(tmp_path, mutation=(5, 5), baseline=(1, 5))
    mixed = score_from_experiment_dir(str(exp))
    assert mixed["assertion_pass_rate"] == pytest.approx(0.6)
    assert mixed["side"] is None


def test_unknown_side_raises(tmp_path):
    exp = _experiment(tmp_path)
    with pytest.raises(ValueError):
        score_from_experiment_dir(str(exp), side="mutation")


def test_side_without_matching_runs_raises(tmp_path):
    """Ein Tippfehler im Verzeichnisnamen darf nicht still 0.0 liefern."""
    exp = tmp_path / "exp-002"
    _write(
        exp / "runs" / "eval-0" / "baseline" / "grading.json",
        {"summary": {"passed": 3, "total": 3}},
    )
    with pytest.raises(NoGradingDataError):
        score_from_experiment_dir(str(exp), side="with_mutation")


def test_missing_timing_is_no_data_not_perfect_efficiency():
    assert calc_efficiency_score(0, 0.0, samples=0) is None
    assert calc_efficiency_score(0, 0.0, samples=1) == pytest.approx(1.0)


def test_efficiency_is_reported_but_not_gated(tmp_path):
    exp = _experiment(tmp_path, mutation=(4, 5), baseline=(4, 5), timings=False)
    result = score_from_experiment_dir(str(exp), side="with_mutation")
    assert result["details"]["efficiency_score"] is None
    assert result["details"]["timing_files_found"] == 0
    # Der Gate-Score ist trotz fehlender Timings exakt die Pass-Rate.
    assert result["composite_score"] == pytest.approx(0.8)


def test_gate_score_equals_pass_rate_without_comparator():
    assert calc_composite_score(0.75) == pytest.approx(0.75)
    assert GATE_WEIGHTS_PLAIN["assertions"] == 1.0
    assert GATE_WEIGHTS_PLAIN["judge"] == 0.0


def test_comparator_weights_are_renormalised():
    """0.50/0.30 ohne Efficiency ergibt 0.65/0.35, nicht 0.50/0.30."""
    assert sum(GATE_WEIGHTS_COMPARATOR.values()) == pytest.approx(1.0)
    score = calc_composite_score(1.0, llm_judge_score=0.0, use_comparator=True)
    assert score == pytest.approx(0.65)


def test_efficiency_cannot_move_the_gate_score(tmp_path):
    """Zwei Läufe, identische Assertions, sehr unterschiedliche Effizienz."""
    fast = tmp_path / "fast"
    slow = tmp_path / "slow"
    for exp, tokens, seconds in ((fast, 20000, 60), (slow, 45000, 120)):
        run = exp / "runs" / "eval-0" / "with_mutation"
        _write(run / "grading.json", {"summary": {"passed": 4, "total": 5}})
        _write(run / "timing.json", {
            "total_tokens": tokens, "total_duration_seconds": seconds,
        })
    a = score_from_experiment_dir(str(fast), side="with_mutation")
    b = score_from_experiment_dir(str(slow), side="with_mutation")
    assert a["composite_score"] == b["composite_score"]
    # In v2 lagen diese beiden Läufe 0.045 auseinander, bei einer
    # Keep-Schwelle von 0.02.
    assert a["details"]["efficiency_score"] != b["details"]["efficiency_score"]


def test_gate_weights_from_config_are_applied(tmp_path):
    """Was in der Konfigurationstabelle steht, muss auch wirken."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"gate_weights": {"assertions": 0.5, "judge": 0.5}}))
    weights = load_gate_weights(str(cfg))
    exp = _experiment(tmp_path, mutation=(4, 5), baseline=(0, 5))
    _write(exp / "comparison.json", {"rubric": {
        "with_mutation": {"overall_score": 6.0},
        "baseline": {"overall_score": 3.0},
    }})
    result = score_from_experiment_dir(
        str(exp), use_comparator=True, side="with_mutation", weights=weights
    )
    assert result["gate_weights"] == {"assertions": 0.5, "judge": 0.5}
    assert result["composite_score"] == pytest.approx(0.5 * 0.8 + 0.5 * 0.6)


def test_judge_weight_without_judge_data_is_rejected(tmp_path):
    """Sonst wird der fehlende Judge-Anteil als 0.0 eingerechnet statt als
    'keine Daten', und der Score sackt still um das Judge-Gewicht ab."""
    exp = _experiment(tmp_path, mutation=(4, 5), baseline=(4, 5))
    with pytest.raises(NoJudgeDataError):
        score_from_experiment_dir(
            str(exp), side="with_mutation",
            weights={"assertions": 0.65, "judge": 0.35},
        )


def test_use_comparator_without_comparison_file_is_rejected(tmp_path):
    exp = _experiment(tmp_path, mutation=(4, 5), baseline=(4, 5))
    with pytest.raises(NoJudgeDataError):
        score_from_experiment_dir(str(exp), use_comparator=True, side="with_mutation")


def test_out_of_range_judge_score_is_rejected(tmp_path):
    """85 statt 8.5 ergaebe llm_judge_score 8.5 und composite 3.6."""
    exp = _experiment(tmp_path, mutation=(4, 5), baseline=(4, 5))
    _write(exp / "comparison.json", {"rubric": {
        "with_mutation": {"overall_score": 85},
        "baseline": {"overall_score": 4.0},
    }})
    with pytest.raises(NoJudgeDataError):
        score_from_experiment_dir(str(exp), use_comparator=True, side="with_mutation")


def test_passed_greater_than_total_is_rejected(tmp_path):
    """passed 7 von total 5 ergaebe eine Pass-Rate von 1.4."""
    exp = tmp_path / "exp-kaputt"
    _write(exp / "runs" / "eval-0" / "with_mutation" / "grading.json",
           {"summary": {"passed": 7, "total": 5}})
    with pytest.raises(NoGradingDataError):
        score_from_experiment_dir(str(exp), side="with_mutation")


def test_gate_weights_must_sum_to_one(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"gate_weights": {"assertions": 0.8, "judge": 0.3}}))
    with pytest.raises(ValueError):
        load_gate_weights(str(cfg))


def test_efficiency_cannot_be_smuggled_back_in_as_a_weight(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "gate_weights": {"assertions": 0.8, "judge": 0.0, "efficiency": 0.2}
    }))
    with pytest.raises(ValueError):
        load_gate_weights(str(cfg))


def test_no_config_means_defaults(tmp_path):
    assert load_gate_weights(None) is None
    assert load_gate_weights(str(tmp_path / "fehlt.json")) is None
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"max_experiments": 10}))
    assert load_gate_weights(str(cfg)) is None


def test_efficiency_normalises_per_run_not_over_the_sum(tmp_path):
    """Sonst skaliert der Score mit der Anzahl der Evals."""
    exp = tmp_path / "exp"
    for eval_id in range(4):
        run = exp / "runs" / ("eval-%d" % eval_id) / "with_mutation"
        _write(run / "grading.json", {"summary": {"passed": 1, "total": 1}})
        _write(run / "timing.json", {
            "total_tokens": 10000, "total_duration_seconds": 30,
        })
    result = score_from_experiment_dir(str(exp), side="with_mutation")
    assert result["details"]["efficiency_score"] == pytest.approx(0.9)


# ─── SICHERHEIT: gefundene Fehler der ersten v3-Fassung ───────────────────


def test_judge_score_respects_the_side(tmp_path):
    """max() ueber alle rubric-Eintraege gab beiden Seiten denselben
    Judge-Wert. Der Judge-Anteil hob sich im Delta immer weg, der Comparator
    war fuer die Entscheidung wirkungslos, obwohl er 0.35 Gewicht traegt."""
    exp = _experiment(tmp_path, mutation=(4, 5), baseline=(4, 5))
    _write(exp / "comparison.json", {"rubric": {
        "with_mutation": {"overall_score": 7.0},
        "baseline": {"overall_score": 5.7},
    }})
    mutated = score_from_experiment_dir(
        str(exp), use_comparator=True, side="with_mutation")
    base = score_from_experiment_dir(
        str(exp), use_comparator=True, side="baseline")
    assert mutated["llm_judge_score"] == pytest.approx(0.70)
    assert base["llm_judge_score"] == pytest.approx(0.57)
    assert mutated["composite_score"] > base["composite_score"]


def test_one_sided_rubric_is_rejected(tmp_path):
    """Eine einseitige Rubrik gewichtete die eine Seite mit 0.65/0.35 und die
    andere mit 1.00/0.00. decide bekam damit zwei Zahlen aus zwei Formeln, und
    ein guter Judge-Wert erzeugte ein KEEP, ohne dass eine Assertion kippte."""
    exp = _experiment(tmp_path, mutation=(4, 5), baseline=(4, 5))
    _write(exp / "comparison.json", {"rubric": {
        "with_mutation": {"overall_score": 9.0},
    }})
    for side in ("with_mutation", "baseline"):
        with pytest.raises(NoJudgeDataError):
            score_from_experiment_dir(str(exp), use_comparator=True, side=side)


def test_both_sides_get_the_same_gate_weights(tmp_path):
    exp = _experiment(tmp_path, mutation=(4, 5), baseline=(4, 5))
    _write(exp / "comparison.json", {"rubric": {
        "with_mutation": {"overall_score": 9.0},
        "baseline": {"overall_score": 4.0},
    }})
    a = score_from_experiment_dir(str(exp), use_comparator=True, side="with_mutation")
    b = score_from_experiment_dir(str(exp), use_comparator=True, side="baseline")
    assert a["gate_weights"] == b["gate_weights"] == GATE_WEIGHTS_COMPARATOR


def test_use_comparator_is_read_from_the_config(tmp_path):
    """Der dokumentierte Aufrufweg gibt nur --config mit. Ohne diese Brücke
    liefert er bei use_comparator: true still den reinen Assertion-Score."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"use_comparator": True}))
    assert load_use_comparator(str(cfg), False) is True
    assert load_use_comparator(None, True) is True
    assert load_use_comparator(None, False) is False
    cfg2 = tmp_path / "aus.json"
    cfg2.write_text(json.dumps({"use_comparator": False}))
    assert load_use_comparator(str(cfg2), False) is False
    assert load_use_comparator(str(cfg2), True) is True


def test_an_eval_directory_named_baseline_does_not_break_the_side_filter(tmp_path):
    """Der Filter suchte den Seitennamen irgendwo im Pfad. Ein Eval-Ordner
    namens baseline liess runs/baseline/with_mutation/ fuer beide Seiten
    matchen."""
    exp = tmp_path / "exp-007"
    _write(exp / "runs" / "baseline" / "with_mutation" / "grading.json",
           {"summary": {"passed": 5, "total": 5}})
    _write(exp / "runs" / "baseline" / "baseline" / "grading.json",
           {"summary": {"passed": 1, "total": 5}})
    mutated = score_from_experiment_dir(str(exp), side="with_mutation")
    base = score_from_experiment_dir(str(exp), side="baseline")
    assert mutated["assertion_pass_rate"] == pytest.approx(1.0)
    assert base["assertion_pass_rate"] == pytest.approx(0.2)
    assert mutated["details"]["grading_files_found"] == 1
    assert base["details"]["grading_files_found"] == 1


def test_side_marker_is_the_deepest_one(tmp_path):
    """outputs/-Unterordner unterhalb der Seite duerfen nicht stoeren."""
    exp = tmp_path / "exp-008"
    _write(exp / "runs" / "eval-0" / "with_mutation" / "outputs" / "grading.json",
           {"summary": {"passed": 3, "total": 3}})
    result = score_from_experiment_dir(str(exp), side="with_mutation")
    assert result["assertion_pass_rate"] == pytest.approx(1.0)
