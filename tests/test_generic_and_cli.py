"""Generic-Modus und die CLI-Schicht.

Beides war komplett ungetestet, obwohl `calc_generic_delta` in v3 geändert
wurde (`improved` heisst jetzt `improved_raw`) und die Richtungslogik von
`tsv-append` ausschliesslich in `main()` steht, nicht in `append_tsv_log`.
"""

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.composite_score import calc_generic_delta, extract_metric_value

SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "composite_score.py")


def run(*args, cwd=None):
    # stdin explizit abklemmen. Seit `metric` stdin zuerst liest, blockiert ein
    # geerbtes Pipe-stdin den Subprozess, und der Testlauf haengt ohne Fehler.
    return subprocess.run(
        [sys.executable, SCRIPT] + list(args),
        capture_output=True, text=True, cwd=cwd, stdin=subprocess.DEVNULL,
    )


# ─── Metrik-Extraktion ────────────────────────────────────────────────────


@pytest.mark.parametrize("output,expected", [
    ("82.5", 82.5),
    ("All files | 82.5 | 70 | 65 | 82.5", 82.5),
    ("Coverage: 91", 91.0),
    ("First Load JS  128.4 kB", 128.4),      # Einheit ohne Ziffern stoert nicht
    ("Build 3 fertig, Score: 91.2", 91.2),   # dokumentierte Falle: LETZTE Zahl gewinnt
    ("-3", -3.0),
    ("0.0", 0.0),
])
def test_extract_metric_takes_the_last_number(output, expected):
    assert extract_metric_value(output) == pytest.approx(expected)


def test_extract_metric_without_a_number():
    assert extract_metric_value("keine Zahl weit und breit") is None
    assert extract_metric_value("") is None


# ─── Generic-Delta ────────────────────────────────────────────────────────


def test_generic_delta_higher_is_better():
    result = calc_generic_delta(82.5, 80.0)
    assert result["improved_raw"] is True
    assert result["raw_delta"] == pytest.approx(2.5)
    assert result["normalized_delta"] == pytest.approx(0.03125)


def test_generic_delta_lower_is_better():
    result = calc_generic_delta(100.0, 120.0, direction="lower_is_better")
    assert result["improved_raw"] is True
    assert result["raw_delta"] == pytest.approx(-20.0)
    assert result["normalized_delta"] == pytest.approx(20 / 120, abs=1e-6)


def test_improved_raw_is_only_a_sign_not_a_decision():
    """Der Name wurde bewusst geändert. improved_raw kennt keine Schwelle:
    schon +0.0001 ist true, obwohl decide dafür NEUTRAL liefert."""
    result = calc_generic_delta(80.0001, 80.0)
    assert result["improved_raw"] is True
    assert "keine Entscheidung" in result["note"]
    assert "improved" not in result


# ─── CLI ──────────────────────────────────────────────────────────────────


def test_version():
    proc = run("--version")
    assert proc.returncode == 0
    assert "3.0.0" in proc.stdout


def test_no_subcommand_prints_help():
    proc = run()
    assert proc.returncode == 0
    assert "decide" in proc.stdout


def test_decide_cli_matches_the_function():
    proc = run("decide", "--candidate", "0.84", "--baseline", "0.78")
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["decision"] == "KEEP"
    assert payload["relative_fallback"] is False


def test_decide_cli_overrides_beat_the_config(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"improvement_threshold": 0.02}))
    proc = run("decide", "--candidate", "0.84", "--baseline", "0.78",
               "--config", str(cfg), "--improvement", "0.10")
    payload = json.loads(proc.stdout)
    assert payload["decision"] == "NEUTRAL"
    assert payload["improvement_threshold"] == pytest.approx(0.10)


def test_tsv_append_orients_the_delta(tmp_path):
    """Die Richtungslogik sitzt in main(), nicht in append_tsv_log."""
    log = tmp_path / "log.tsv"
    assert run("tsv-init", str(log)).returncode == 0
    proc = run("tsv-append", str(log), "--experiment", "exp-001",
               "--hypothesis", "Bundle verkleinert",
               "--before", "120", "--after", "100",
               "--decision", "KEEP", "--category", "bundle",
               "--direction", "lower_is_better")
    assert proc.returncode == 0
    rows = list(csv.DictReader(log.open(), delimiter="\t"))
    assert rows[0]["delta"] == "+20.0000"
    assert rows[0]["decision"] == "KEEP"


def test_tsv_append_default_direction(tmp_path):
    log = tmp_path / "log.tsv"
    run("tsv-init", str(log))
    run("tsv-append", str(log), "--experiment", "exp-001", "--hypothesis", "h",
        "--before", "0.72", "--after", "0.78", "--decision", "KEEP",
        "--category", "workflow")
    rows = list(csv.DictReader(log.open(), delimiter="\t"))
    assert rows[0]["delta"] == "+0.0600"


def test_tsv_header_has_nine_columns(tmp_path):
    log = tmp_path / "log.tsv"
    run("tsv-init", str(log))
    header = log.read_text().splitlines()[0].split("\t")
    assert len(header) == 9
    assert header[0] == "timestamp" and header[-1] == "duration_s"


def test_invalid_decision_value_is_rejected(tmp_path):
    log = tmp_path / "log.tsv"
    run("tsv-init", str(log))
    proc = run("tsv-append", str(log), "--experiment", "e", "--hypothesis", "h",
               "--before", "0", "--after", "1", "--decision", "KEEEP",
               "--category", "workflow")
    assert proc.returncode == 2
    assert "invalid choice" in proc.stderr


def test_metric_cli(tmp_path):
    proc = run("metric", "Coverage: 82.5", "--baseline", "80")
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["improved_raw"] is True
    assert payload["current_value"] == pytest.approx(82.5)


def test_metric_without_a_number_exits_one():
    proc = run("metric", "kein Wert", "--baseline", "80")
    assert proc.returncode == 1
    assert "Keine Zahl" in proc.stderr


def test_plateau_cli(tmp_path):
    hist = tmp_path / "history.json"
    hist.write_text(json.dumps({"experiments": [
        {"id": "e1", "decision": "KEEP"},
        {"id": "e2", "decision": "NEUTRAL"},
        {"id": "e3", "decision": "REVERT"},
        {"id": "e4", "decision": "NEUTRAL"},
    ]}))
    payload = json.loads(run("plateau", str(hist), "--window", "3").stdout)
    assert payload["plateau"] is True
    assert payload["last_decisions"] == ["NEUTRAL", "REVERT", "NEUTRAL"]


# ─── CLI-Fehlerpfade: Exit 2 statt Traceback ──────────────────────────────


def test_score_without_gradings_exits_two(tmp_path):
    (tmp_path / "leer").mkdir()
    proc = run("score", str(tmp_path / "leer"), "--side", "with_mutation")
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr


def test_revert_without_manifest_exits_two(tmp_path):
    proc = run("revert", "--snapshot-dir", str(tmp_path), "--version", "pre-exp-009")
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr


def test_snapshot_on_a_missing_target_exits_two(tmp_path):
    proc = run("snapshot", "--target", str(tmp_path / "weg.md"),
               "--snapshot-dir", str(tmp_path / "snap"), "--version", "pre-exp-001")
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr


def test_snapshot_conflict_exits_two(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("# v0\n")
    run("snapshot", "--target", str(target),
        "--snapshot-dir", str(tmp_path / "snap"), "--version", "pre-exp-001")
    target.write_text("# mutiert\n")
    proc = run("snapshot", "--target", str(target),
               "--snapshot-dir", str(tmp_path / "snap"), "--version", "pre-exp-001")
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr


def test_score_with_bad_gate_weights_exits_two(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"gate_weights": {"assertions": 0.8, "judge": 0.3}}))
    exp = tmp_path / "exp"
    run_dir = exp / "runs" / "eval-0" / "with_mutation"
    run_dir.mkdir(parents=True)
    (run_dir / "grading.json").write_text(json.dumps({"summary": {"passed": 1, "total": 1}}))
    proc = run("score", str(exp), "--side", "with_mutation", "--config", str(cfg))
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr


# ─── Doku-Aufrufe wörtlich ausführen ──────────────────────────────────────


def test_the_documented_snapshot_revert_cycle(tmp_path):
    """Der Ablauf aus SKILL.md Schritt 2 und Schritt 5, wörtlich."""
    target = tmp_path / "SKILL.md"
    target.write_text("# Baseline\n")
    snap = tmp_path / "snapshots"
    assert run("snapshot", "--target", str(target),
               "--snapshot-dir", str(snap), "--version", "pre-exp-001").returncode == 0
    target.write_text("# Mutiert\n")
    decision = json.loads(run("decide", "--candidate", "0.70", "--baseline", "0.80").stdout)
    assert decision["decision"] == "REVERT"
    assert run("revert", "--snapshot-dir", str(snap),
               "--version", "pre-exp-001").returncode == 0
    assert target.read_text() == "# Baseline\n"
