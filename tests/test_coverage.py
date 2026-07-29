"""Coverage-Matrix. Pinnt zwei Fehler aus v2.

1. Sättigung rastete ein: `cat["saturated"] = True` hatte keinen Gegenzweig.
   Eine Kategorie, die einmal als abgegrast galt, erholte sich nie mehr, auch
   nicht nach einem späteren Treffer. Die Matrix steuert die Exploration, der
   Fehler lenkte den Hypothesis-Agent also dauerhaft in die falsche Richtung.
2. `best_delta` war richtungsblind. Bei `lower_is_better` gewann die
   schlimmste Regression als Bestwert.
"""

import json

import pytest

from scripts.composite_score import (
    as_float,
    init_coverage_matrix,
    update_coverage_matrix,
)


@pytest.fixture
def matrix_path(tmp_path):
    path = tmp_path / "coverage-matrix.json"
    init_coverage_matrix(str(path), ["workflow", "examples"])
    return str(path)


def _cat(matrix_path, name):
    return json.loads(open(matrix_path).read())["categories"][name]


def test_saturation_sets_after_three_flat_experiments(matrix_path):
    for i in range(3):
        update_coverage_matrix(
            matrix_path, "workflow", "exp-00%d" % (i + 1), "NEUTRAL", 0.001
        )
    assert _cat(matrix_path, "workflow")["saturated"] is True


def test_saturation_resolves_after_a_hit(matrix_path):
    """Der eigentliche Bug: saturated wurde nie zurückgenommen."""
    for i in range(3):
        update_coverage_matrix(
            matrix_path, "workflow", "exp-00%d" % (i + 1), "NEUTRAL", 0.001
        )
    assert _cat(matrix_path, "workflow")["saturated"] is True
    update_coverage_matrix(matrix_path, "workflow", "exp-004", "KEEP", 0.09)
    assert _cat(matrix_path, "workflow")["saturated"] is False


def test_best_delta_respects_lower_is_better(matrix_path):
    """Bei lower_is_better ist -20 besser als +5."""
    update_coverage_matrix(
        matrix_path, "workflow", "exp-001", "KEEP", -20.0,
        direction="lower_is_better",
    )
    update_coverage_matrix(
        matrix_path, "workflow", "exp-002", "REVERT", 5.0,
        direction="lower_is_better",
    )
    assert as_float(_cat(matrix_path, "workflow")["best_delta"]) == pytest.approx(20.0)


def test_best_delta_default_direction(matrix_path):
    update_coverage_matrix(matrix_path, "examples", "exp-001", "KEEP", 0.09)
    update_coverage_matrix(matrix_path, "examples", "exp-002", "REVERT", -0.12)
    assert as_float(_cat(matrix_path, "examples")["best_delta"]) == pytest.approx(0.09)


def test_neutral_lands_in_its_own_bucket(matrix_path):
    update_coverage_matrix(matrix_path, "workflow", "exp-001", "NEUTRAL", 0.0)
    cat = _cat(matrix_path, "workflow")
    assert cat["experiments_neutral"] == 1
    assert cat["experiments_kept"] == 0
    assert cat["experiments_reverted"] == 0


def test_invalid_does_not_count_towards_saturation(matrix_path):
    """Eine Kategorie, die nie gemessen wurde, gilt nicht als abgegrast."""
    for i in range(4):
        update_coverage_matrix(
            matrix_path, "workflow", "exp-00%d" % (i + 1), "INVALID", 0.0
        )
    cat = _cat(matrix_path, "workflow")
    assert cat["experiments_invalid"] == 4
    assert cat["saturated"] is False


def test_invalid_does_not_pollute_best_delta(matrix_path):
    update_coverage_matrix(matrix_path, "workflow", "exp-001", "INVALID", 0.99)
    assert _cat(matrix_path, "workflow")["best_delta"] is None


def test_unknown_category_is_created_for_generic_mode(matrix_path):
    update_coverage_matrix(matrix_path, "src/api", "exp-001", "KEEP", 0.04)
    matrix = json.loads(open(matrix_path).read())
    assert "src/api" in matrix["categories"]
    assert matrix["coverage_summary"]["total_categories"] == 3


def test_old_matrix_without_new_fields_is_migrated(tmp_path):
    """Ein Workspace aus v2 darf nicht mit KeyError abbrechen."""
    path = tmp_path / "alt.json"
    path.write_text(json.dumps({
        "categories": {"workflow": {
            "experiments_total": 2, "experiments_kept": 1,
            "experiments_reverted": 1, "last_experiment": "exp-002",
            "best_delta": "+0.0300", "saturated": False,
        }},
        "coverage_summary": {"total_categories": 1},
    }))
    update_coverage_matrix(str(path), "workflow", "exp-003", "NEUTRAL", 0.0)
    cat = json.loads(path.read_text())["categories"]["workflow"]
    assert cat["experiments_neutral"] == 1
    assert cat["experiments_invalid"] == 0


def test_as_float_handles_signed_strings():
    """best_delta in der Coverage-Matrix und alte history.json-Dateien fuehren
    delta als formatierten String wie '+0.06'."""
    assert as_float("+0.06") == pytest.approx(0.06)
    assert as_float("-0.12") == pytest.approx(-0.12)
    assert as_float(0.5) == pytest.approx(0.5)
    assert as_float(None) == 0.0
    assert as_float("keine Zahl") == 0.0


def test_string_deltas_compare_numerically_not_lexicographically():
    """Lexikografisch wäre '+0.09' > '+0.10'."""
    assert as_float("+0.09") < as_float("+0.10")


def test_fresh_matrix_already_has_the_new_count_fields(matrix_path):
    """init_coverage_matrix benutzte ein eigenes Inline-Dict und schrieb
    experiments_neutral und experiments_invalid nicht. Wer die Matrix direkt
    nach der Initialisierung auslas, fand die Schluessel nicht."""
    cat = _cat(matrix_path, "workflow")
    assert cat["experiments_neutral"] == 0
    assert cat["experiments_invalid"] == 0
