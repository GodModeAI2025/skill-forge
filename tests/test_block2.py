"""Block 2: Auflösungsgrenze, Dreiwege-Split, Diff mit NO_OP, Längsvergleich.

Der gemeinsame Nenner: die Zahl, über die entschieden wird, soll bedeuten, was
sie behauptet. Eine feste Schwelle von 0.02 auf einem Score, der in Schritten
von 1/N springt, bedeutet nichts. Ein Split, der nur in der Config existiert,
schützt nicht vor Overfitting. Ein Aggregat, das fünf Treffer gegen drei
Regressionen aufrechnet, versteckt den Schaden.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.composite_score import (
    MIN_EVALS_FOR_TEST,
    SPLIT_NAMES,
    assign_split,
    assign_splits,
    compare_runs,
    decide,
    format_comparison,
    load_evals,
    make_diff,
    min_detectable_delta,
    score_from_experiment_dir,
    snapshot,
)

SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "composite_score.py")


def run(*args):
    # stdin explizit abklemmen. Seit `metric` stdin zuerst liest, blockiert ein
    # geerbtes Pipe-stdin den Subprozess, und der Testlauf haengt ohne Fehler.
    return subprocess.run(
        [sys.executable, SCRIPT] + list(args), capture_output=True, text=True,
        stdin=subprocess.DEVNULL,
    )


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


# ─── B1: Auflösungsgrenze ─────────────────────────────────────────────────


def test_resolution_is_two_flips_over_the_assertion_count():
    assert min_detectable_delta(9) == pytest.approx(2 / 9)
    assert min_detectable_delta(31) == pytest.approx(2 / 31)
    assert min_detectable_delta(100) == pytest.approx(0.02)


def test_resolution_with_no_assertions_is_zero():
    assert min_detectable_delta(0) == 0.0
    assert min_detectable_delta(-5) == 0.0


def test_a_single_flip_no_longer_triggers_keep():
    """Der Kern des Befunds: bei 9 Assertions bewegt ein Flip 0.111, die feste
    Schwelle von 0.02 lag darunter und konnte nie greifen."""
    resolution = min_detectable_delta(9)
    one_flip = 1 / 9
    assert decide(0.5 + one_flip, 0.5)["decision"] == "KEEP"      # ohne Auflösung
    assert decide(0.5 + one_flip, 0.5, resolution=resolution)["decision"] == "NEUTRAL"


def test_two_flips_survive_the_resolution():
    resolution = min_detectable_delta(9)
    two_flips = 2 / 9 + 1e-9
    assert decide(0.5 + two_flips, 0.5, resolution=resolution)["decision"] == "KEEP"


def test_the_formula_names_the_binding_threshold():
    result = decide(0.55, 0.50, resolution=0.22)
    assert result["binding_threshold"] == "resolution"
    assert "resolution" in result["formula"]
    plain = decide(0.55, 0.50)
    assert plain["binding_threshold"] == "improvement_threshold"


def test_noise_floor_and_resolution_take_the_maximum():
    result = decide(0.60, 0.50, noise_floor=0.08, resolution=0.15)
    assert result["threshold"] == pytest.approx(0.15)
    assert result["decision"] == "NEUTRAL"


def test_score_reports_the_resolution(tmp_path):
    exp = tmp_path / "exp"
    _write(exp / "runs" / "eval-0" / "with_mutation" / "grading.json",
           {"summary": {"passed": 7, "total": 9}})
    result = score_from_experiment_dir(str(exp), side="with_mutation")
    assert result["total_assertions"] == 9
    assert result["resolution"] == pytest.approx(2 / 9, abs=1e-6)


def test_resolution_cli():
    payload = json.loads(run("resolution", "--assertions", "31").stdout)
    assert payload["resolution"] == pytest.approx(2 / 31, abs=1e-6)
    assert "nicht messbar" in payload["note"]


# ─── B4: Dreiwege-Split ───────────────────────────────────────────────────


def test_split_assignment_is_stable_for_the_same_id():
    first = assign_split("ki-marker-entfernung")
    for _ in range(20):
        assert assign_split("ki-marker-entfernung") == first


def test_split_assignment_changes_with_the_seed():
    ids = ["eval-%02d" % i for i in range(40)]
    a = [assign_split(i, seed=42) for i in ids]
    b = [assign_split(i, seed=7) for i in ids]
    assert a != b


def test_deleting_an_eval_does_not_move_the_others():
    """Genau das würde eine Liste oder eine Positionsnummer kaputt machen."""
    evals = [{"id": "eval-%02d" % i} for i in range(20)]
    assign_splits(evals)
    before = {e["id"]: e["split"] for e in evals}
    remaining = [e for e in evals if e["id"] != "eval-05"]
    assign_splits(remaining)
    for entry in remaining:
        assert entry["split"] == before[entry["id"]]


def test_all_three_splits_are_used_with_enough_evals():
    evals = [{"id": "eval-%02d" % i} for i in range(40)]
    summary = assign_splits(evals)
    assert summary["with_test"] is True
    assert all(summary["counts"][name] > 0 for name in SPLIT_NAMES)
    assert sum(summary["counts"].values()) == 40


def test_no_test_split_below_the_threshold():
    """Ein Zwei-Item-Holdout als unabhängigen Test auszuweisen ist
    irreführender als gar keiner."""
    evals = [{"id": "eval-%02d" % i} for i in range(MIN_EVALS_FOR_TEST - 1)]
    summary = assign_splits(evals)
    assert summary["with_test"] is False
    assert summary["counts"]["test"] == 0
    assert any("kein test-Split" in w for w in summary["warnings"])


def test_empty_val_is_filled_deterministically():
    """Ohne Fallback gated der Loop gegen eine leere Menge und meldet 1.0."""
    evals = [{"id": "eval-%02d" % i} for i in range(14)]
    summary = assign_splits(evals, val_fraction=0.0, test_fraction=0.25)
    assert summary["counts"]["val"] >= 1
    assert summary["forced_to_val"]
    forced = summary["forced_to_val"][0]
    again = [{"id": "eval-%02d" % i} for i in range(14)]
    assert assign_splits(again, val_fraction=0.0,
                         test_fraction=0.25)["forced_to_val"] == [forced]


def test_the_val_fallback_never_takes_from_test():
    evals = [{"id": "eval-%02d" % i} for i in range(14)]
    summary = assign_splits(evals, val_fraction=0.0, test_fraction=0.25)
    forced = summary["forced_to_val"][0]
    # Das gezwungene Eval kam aus train, nicht aus test.
    assert assign_split(forced, 42, 0.0, 0.25) == "train"


def test_too_few_evals_produce_a_warning():
    evals = [{"id": "eval-%d" % i} for i in range(3)]
    summary = assign_splits(evals)
    assert any("nur 3 Evals" in w for w in summary["warnings"])


def test_missing_ids_are_rejected():
    with pytest.raises(ValueError):
        assign_splits([{"prompt": "ohne id"}])


def test_duplicate_ids_are_rejected():
    with pytest.raises(ValueError):
        assign_splits([{"id": "a"}, {"id": "a"}])


def test_load_evals_filters_by_split(tmp_path):
    path = tmp_path / "evals.json"
    path.write_text(json.dumps({"version": 1, "evals": [
        {"id": "a", "split": "train"},
        {"id": "b", "split": "val"},
        {"id": "c", "split": "train"},
    ]}))
    assert [e["id"] for e in load_evals(str(path), "train")] == ["a", "c"]
    assert [e["id"] for e in load_evals(str(path), "val")] == ["b"]
    assert len(load_evals(str(path))) == 3


def test_load_evals_rejects_an_unknown_split(tmp_path):
    path = tmp_path / "evals.json"
    path.write_text(json.dumps({"evals": []}))
    with pytest.raises(ValueError):
        load_evals(str(path), "holdout")


def test_split_assign_cli_writes_the_field(tmp_path):
    path = tmp_path / "evals.json"
    path.write_text(json.dumps({"version": 1, "evals": [
        {"id": "eval-%02d" % i, "prompt": "p"} for i in range(20)
    ]}))
    proc = run("split-assign", str(path))
    assert proc.returncode == 0
    data = json.loads(path.read_text())
    assert data["split_seed"] == 42
    assert all(e["split"] in SPLIT_NAMES for e in data["evals"])


def test_split_assign_dry_run_does_not_write(tmp_path):
    path = tmp_path / "evals.json"
    original = json.dumps({"evals": [{"id": "a"}, {"id": "b"}]})
    path.write_text(original)
    proc = run("split-assign", str(path), "--dry-run")
    assert proc.returncode == 0
    assert path.read_text() == original
    assert json.loads(proc.stdout)["written"] is False


def test_split_assign_cli_rejects_missing_ids(tmp_path):
    path = tmp_path / "evals.json"
    path.write_text(json.dumps({"evals": [{"prompt": "ohne id"}]}))
    proc = run("split-assign", str(path))
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr


# ─── B7: Diff und NO_OP ───────────────────────────────────────────────────


def test_diff_detects_an_edit(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("Zeile eins\nZeile zwei\n")
    snapshot(str(target), str(tmp_path / "snap"), "pre-exp-001")
    target.write_text("Zeile eins\nZeile zwei geaendert\n")
    result = make_diff(str(tmp_path / "snap"), "pre-exp-001",
                       str(tmp_path / "mutation.diff"))
    assert result["changed"] is True
    assert result["files_changed"] == ["SKILL.md"]
    assert result["lines_added"] == 1 and result["lines_removed"] == 1
    assert "Zeile zwei geaendert" in (tmp_path / "mutation.diff").read_text()


def test_a_mutation_that_changed_nothing_is_a_no_op(tmp_path):
    """Ein Experiment ohne Byte-Änderung liefert per Konstruktion Delta null
    und darf nicht als Neutralergebnis in die Statistik gehen."""
    target = tmp_path / "SKILL.md"
    target.write_text("unveraendert\n")
    snapshot(str(target), str(tmp_path / "snap"), "pre-exp-001")
    result = make_diff(str(tmp_path / "snap"), "pre-exp-001")
    assert result["changed"] is False
    assert result["files_changed"] == []


def test_diff_sees_a_newly_added_file(tmp_path):
    """script_add und reference_add legen Dateien an, die im Snapshot fehlen.
    Ein naiver Datei-gegen-Datei-Vergleich stempelte das als NO_OP ab."""
    scope = tmp_path / "scope"
    scope.mkdir()
    (scope / "a.py").write_text("a\n")
    snapshot(str(scope), str(tmp_path / "snap"), "pre-exp-001")
    (scope / "helper.py").write_text("neu\n")
    result = make_diff(str(tmp_path / "snap"), "pre-exp-001")
    assert result["changed"] is True
    assert result["files_added"] == ["helper.py"]


def test_diff_sees_a_deleted_file(tmp_path):
    scope = tmp_path / "scope"
    scope.mkdir()
    (scope / "a.py").write_text("a\n")
    (scope / "b.py").write_text("b\n")
    snapshot(str(scope), str(tmp_path / "snap"), "pre-exp-001")
    (scope / "b.py").unlink()
    result = make_diff(str(tmp_path / "snap"), "pre-exp-001")
    assert result["files_deleted"] == ["b.py"]
    assert result["changed"] is True


def test_diff_handles_binary_files(tmp_path):
    scope = tmp_path / "scope"
    scope.mkdir()
    (scope / "bild.bin").write_bytes(b"\xff\xfe\x00PNG")
    snapshot(str(scope), str(tmp_path / "snap"), "pre-exp-001")
    (scope / "bild.bin").write_bytes(b"\xff\xfe\x01PNG")
    result = make_diff(str(tmp_path / "snap"), "pre-exp-001")
    assert result["binary_files"] == ["bild.bin"]
    assert result["changed"] is True


def test_diff_cli(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("alt\n")
    run("snapshot", "--target", str(target),
        "--snapshot-dir", str(tmp_path / "snap"), "--version", "pre-exp-001")
    target.write_text("neu\n")
    proc = run("diff", "--snapshot-dir", str(tmp_path / "snap"),
               "--version", "pre-exp-001", "--out", str(tmp_path / "m.diff"))
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["changed"] is True
    assert (tmp_path / "m.diff").exists()


def test_diff_cli_without_manifest_exits_two(tmp_path):
    proc = run("diff", "--snapshot-dir", str(tmp_path), "--version", "pre-exp-009")
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr


# ─── B8: Längsvergleich ───────────────────────────────────────────────────


def _pair(exp, eval_id, baseline_ok, mutation_ok, total=3):
    for side, ok in (("baseline", baseline_ok), ("with_mutation", mutation_ok)):
        _write(exp / "runs" / eval_id / side / "grading.json",
               {"summary": {"passed": total if ok else 1, "total": total}})


def test_comparison_categorises_every_pair(tmp_path):
    exp = tmp_path / "exp"
    _pair(exp, "eval-0", False, True)    # improved
    _pair(exp, "eval-1", True, False)    # regressed
    _pair(exp, "eval-2", False, False)   # persistent_fail
    _pair(exp, "eval-3", True, True)     # stable_success
    result = compare_runs(str(exp))
    assert result["counts"] == {
        "improved": 1, "regressed": 1,
        "persistent_fail": 1, "stable_success": 1,
    }
    assert result["categories"]["regressed"] == ["eval-1"]
    assert result["total_pairs"] == 4
    assert result["net"] == 0


def test_a_positive_net_can_still_hide_regressions(tmp_path):
    """Genau der Fall, den ein Aggregatscore verschluckt: fünf neue Treffer,
    drei neue Fehler, netto plus zwei, sieht wie Fortschritt aus."""
    exp = tmp_path / "exp"
    for i in range(5):
        _pair(exp, "eval-imp-%d" % i, False, True)
    for i in range(3):
        _pair(exp, "eval-reg-%d" % i, True, False)
    result = compare_runs(str(exp))
    assert result["net"] == 2
    assert result["counts"]["regressed"] == 3


def test_regressions_come_first_in_the_rendering(tmp_path):
    exp = tmp_path / "exp"
    _pair(exp, "eval-0", False, True)
    _pair(exp, "eval-1", True, False)
    text = format_comparison(compare_runs(str(exp)))
    assert text.index("Regressionen") < text.index("Neu gelöst")
    assert "HÖCHSTE PRIORITÄT" in text


def test_unpaired_evals_are_reported_not_guessed(tmp_path):
    exp = tmp_path / "exp"
    _pair(exp, "eval-0", True, True)
    _write(exp / "runs" / "eval-1" / "with_mutation" / "grading.json",
           {"summary": {"passed": 3, "total": 3}})
    result = compare_runs(str(exp))
    assert result["unpaired"] == ["eval-1"]
    assert result["total_pairs"] == 1


def test_an_eval_counts_as_passed_only_when_all_assertions_pass(tmp_path):
    exp = tmp_path / "exp"
    _write(exp / "runs" / "eval-0" / "baseline" / "grading.json",
           {"summary": {"passed": 2, "total": 3}})
    _write(exp / "runs" / "eval-0" / "with_mutation" / "grading.json",
           {"summary": {"passed": 3, "total": 3}})
    result = compare_runs(str(exp))
    assert result["categories"]["improved"] == ["eval-0"]


def test_compare_cli(tmp_path):
    exp = tmp_path / "exp"
    _pair(exp, "eval-0", True, False)
    proc = run("compare", str(exp))
    assert proc.returncode == 0
    assert "Regressionen" in proc.stdout
    payload = json.loads(run("compare", str(exp), "--json").stdout)
    assert payload["counts"]["regressed"] == 1
