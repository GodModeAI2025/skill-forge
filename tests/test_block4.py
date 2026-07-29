"""Block 4: Token-Budget mit Konsequenz und Invarianten im Generic-Modus.

Der gemeinsame Nenner: der Loop soll die Zahl nicht dadurch verbessern können,
dass er das Gemessene kleiner macht. Die optimale Mutation für
`flake8 src/ | wc -l` ist, `src/` zu löschen. Ein Skill wächst, weil Wachstum
nichts kostet.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.composite_score import (
    artifact_stats,
    check_invariants,
    count_tokens,
    hash_paths,
    snapshot_scope,
    suggest_token_budget,
)

SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "composite_score.py")


def run(*args):
    # stdin explizit abklemmen. Seit `metric` stdin zuerst liest, blockiert ein
    # geerbtes Pipe-stdin den Subprozess, und der Testlauf haengt ohne Fehler.
    return subprocess.run(
        [sys.executable, SCRIPT] + list(args), capture_output=True, text=True,
        stdin=subprocess.DEVNULL,
    )


# ─── Token-Budget ─────────────────────────────────────────────────────────


def test_the_divisor_is_three_for_german():
    """Mit 4 wäre das Budget für deutsche Texte rund 30 Prozent zu grosszügig."""
    assert count_tokens("x" * 300) == 100
    assert count_tokens("x" * 300, chars_per_token=4) == 75


def test_stats_sum_over_all_paths(tmp_path):
    (tmp_path / "SKILL.md").write_text("a" * 300)
    (tmp_path / "referenz.md").write_text("b" * 150)
    result = artifact_stats([str(tmp_path / "SKILL.md"), str(tmp_path / "referenz.md")])
    assert result["file_count"] == 2
    assert result["chars"] == 450
    assert result["tokens"] == 150


def test_the_budget_cannot_be_dodged_via_a_reference_file(tmp_path):
    """reference_add legt eine separate Datei an und schreibt nur den Verweis
    in die SKILL.md. Ein Budget, das nur die Hauptdatei zählt, ist damit in
    einer Runde umgangen, und zwar durch genau den Mutationstyp, den der Loop
    unter Budgetdruck naheliegenderweise wählt."""
    (tmp_path / "SKILL.md").write_text("a" * 300)
    (tmp_path / "references").mkdir()
    (tmp_path / "references" / "gross.md").write_text("b" * 3000)

    nur_skill = artifact_stats([str(tmp_path / "SKILL.md")], budget=200)
    assert nur_skill["budget_ok"] is True

    voller_scope = artifact_stats(
        [str(tmp_path / "SKILL.md"), str(tmp_path / "references" / "*.md")],
        budget=200,
    )
    assert voller_scope["budget_ok"] is False
    assert voller_scope["over_by"] > 0


def test_exceeding_the_budget_forces_a_prune(tmp_path):
    """Der Richtwert ohne Konsequenz hat nie ein KEEP verhindert."""
    (tmp_path / "SKILL.md").write_text("a" * 3000)
    result = artifact_stats([str(tmp_path / "SKILL.md")], budget=100)
    assert result["forced_category"] == "efficiency"
    assert result["forced_mutation_type"] == "prune"


def test_within_the_budget_forces_nothing(tmp_path):
    (tmp_path / "SKILL.md").write_text("a" * 90)
    result = artifact_stats([str(tmp_path / "SKILL.md")], budget=100)
    assert result["budget_ok"] is True
    assert "forced_category" not in result


def test_protected_regions_are_reported_separately(tmp_path):
    (tmp_path / "SKILL.md").write_text(
        "Body\n<!-- FORGE_APPENDIX_START -->\n" + "n" * 300
        + "\n<!-- FORGE_APPENDIX_END -->\n"
    )
    result = artifact_stats([str(tmp_path / "SKILL.md")])
    assert result["protected_tokens"] > 0
    assert result["protected_tokens"] < result["tokens"]


def test_the_suggested_budget_has_a_floor():
    assert suggest_token_budget(100) == 2000
    assert suggest_token_budget(4000) == 5000


def test_a_missing_file_is_skipped_not_fatal(tmp_path):
    (tmp_path / "SKILL.md").write_text("a" * 30)
    result = artifact_stats([str(tmp_path / "SKILL.md"), str(tmp_path / "weg.md")])
    assert result["file_count"] == 1


def test_artifact_stats_cli_exits_one_over_budget(tmp_path):
    (tmp_path / "SKILL.md").write_text("a" * 3000)
    proc = run("artifact-stats", str(tmp_path / "SKILL.md"), "--budget", "100")
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["budget_ok"] is False


def test_artifact_stats_cli_can_suggest(tmp_path):
    (tmp_path / "SKILL.md").write_text("a" * 30000)
    payload = json.loads(
        run("artifact-stats", str(tmp_path / "SKILL.md"), "--suggest-budget").stdout
    )
    assert payload["suggested_budget"] == 12500


# ─── Invarianten ──────────────────────────────────────────────────────────


def _projekt(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(10):
        (src / ("modul_%d.py" % i)).write_text("x = %d\n" % i)
    (tmp_path / ".flake8").write_text("[flake8]\nmax-line-length = 100\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n")
    return src


def _before(tmp_path):
    _projekt(tmp_path)
    return snapshot_scope(
        str(tmp_path / "src"),
        [str(tmp_path / ".flake8"), str(tmp_path / "tests" / "*.py")],
    )


def test_hashes_cover_globs(tmp_path):
    _projekt(tmp_path)
    hashes = hash_paths([str(tmp_path / "tests" / "*.py")])
    assert len(hashes) == 1
    assert all(len(h) == 64 for h in hashes.values())


def test_an_untouched_scope_passes(tmp_path):
    before = _before(tmp_path)
    (tmp_path / "src" / "modul_0.py").write_text("x = 0  # kommentiert\n")
    result = check_invariants(before)
    assert result["ok"] is True
    assert result["decision"] is None


def test_changing_the_metric_config_is_a_violation(tmp_path):
    """Die Lint-Schwelle zu senken verbessert die Zahl, nicht die Software."""
    before = _before(tmp_path)
    (tmp_path / ".flake8").write_text("[flake8]\nmax-line-length = 500\nignore = E501\n")
    result = check_invariants(before)
    assert result["ok"] is False
    assert result["decision"] == "INVALID"
    assert any(".flake8" in p for p in result["violated_paths"])


def test_deleting_a_test_file_is_a_violation(tmp_path):
    before = _before(tmp_path)
    (tmp_path / "tests" / "test_a.py").unlink()
    result = check_invariants(before)
    assert result["ok"] is False
    assert any("test_a.py" in p for p in result["vanished_paths"])


def test_deleting_the_measured_source_is_caught_by_the_scope_ratio(tmp_path):
    """Die optimale Mutation für `flake8 src/ | wc -l` ist, src/ zu löschen."""
    before = _before(tmp_path)
    for i in range(8):
        (tmp_path / "src" / ("modul_%d.py" % i)).unlink()
    result = check_invariants(before)
    assert result["ok"] is False
    assert result["scope_after"] == 2
    assert any("geschrumpft" in r for r in result["reasons"])


def test_a_small_shrink_stays_within_the_ratio(tmp_path):
    before = _before(tmp_path)
    (tmp_path / "src" / "modul_0.py").unlink()
    result = check_invariants(before, min_scope_ratio=0.9)
    assert result["ok"] is True


def test_the_invariant_command_must_stay_green(tmp_path):
    before = _before(tmp_path)
    ok = check_invariants(before, invariant_command="exit 0")
    assert ok["ok"] is True and ok["invariant_exit_code"] == 0
    broken = check_invariants(before, invariant_command="exit 1")
    assert broken["ok"] is False
    assert broken["decision"] == "INVALID"
    assert any("Exit 1" in r for r in broken["reasons"])


def test_the_command_never_runs_after_a_protected_file_changed(tmp_path):
    """SkillOpt: never execute a test file after detecting that the evaluated
    agent changed it."""
    before = _before(tmp_path)
    (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    pass\n")
    result = check_invariants(before, invariant_command="exit 0")
    assert result["invariant_command_ran"] is False
    assert result["ok"] is False


def test_metric_without_invariants_still_works():
    proc = run("metric", "Coverage: 82.5", "--baseline", "80")
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["current_value"] == pytest.approx(82.5)


def test_metric_refuses_a_value_when_invariants_broke(tmp_path):
    """Ohne bestandene Prüfung gibt es keine Zahl. Sonst könnte der Prompt den
    Check überspringen und trotzdem einen Wert bekommen."""
    before = _before(tmp_path)
    state = tmp_path / "before.json"
    state.write_text(json.dumps(before))
    (tmp_path / ".flake8").write_text("ignore = alles\n")
    proc = run("metric", "Fehler: 0", "--baseline", "12",
               "--direction", "lower_is_better",
               "--invariants-before", str(state))
    assert proc.returncode == 3
    payload = json.loads(proc.stdout)
    assert payload["decision"] == "INVALID"
    assert "current_value" not in payload


def test_metric_passes_through_when_invariants_hold(tmp_path):
    before = _before(tmp_path)
    state = tmp_path / "before.json"
    state.write_text(json.dumps(before))
    proc = run("metric", "Fehler: 3", "--baseline", "12",
               "--direction", "lower_is_better",
               "--invariants-before", str(state), "--invariant-command", "exit 0")
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["improved_raw"] is True


def test_invariants_cli_roundtrip(tmp_path):
    _projekt(tmp_path)
    state = tmp_path / "inv.json"
    proc = run("invariants-snapshot", "--scope", str(tmp_path / "src"),
               "--protected", str(tmp_path / ".flake8"), "--out", str(state))
    assert proc.returncode == 0
    assert state.exists()
    assert run("invariants-check", "--before", str(state)).returncode == 0
    (tmp_path / ".flake8").write_text("kaputt\n")
    proc = run("invariants-check", "--before", str(state))
    assert proc.returncode == 3
    assert "Traceback" not in proc.stderr
