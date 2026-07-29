"""History-Kompaktierung und Checkpoints.

`compact_history` löschte in v2 das Feld `hypothesis` in-place und ohne
Backup, also genau das Feld, das der Duplikat-Check in agents/hypothesis.md
braucht. Ab Experiment 6 sah der Agent, dass eine Kategorie viermal reverted
worden war, aber nicht mehr, was versucht worden war.

`get_resume_info` indizierte vier Felder direkt und warf bei einem Checkpoint
aus einer früheren Version einen KeyError, also genau in dem Moment, in dem
ein Resume gebraucht wird.
"""

import json

import pytest

from scripts.composite_score import (
    compact_history,
    get_history_for_agent,
    get_resume_info,
    group_history_by_category,
    load_checkpoint,
    save_checkpoint,
)


def _history(tmp_path, count=8):
    experiments = []
    for i in range(1, count + 1):
        experiments.append({
            "id": "exp-%03d" % i,
            "version": "v%d" % i,
            "category": "workflow" if i % 2 else "examples",
            "mutation_type": "instruction_edit",
            "hypothesis": "Hypothese Nummer %d im Wortlaut" % i,
            "composite_score": 0.60 + i * 0.01,
            "delta": "+0.0%d" % i,
            "decision": "KEEP" if i % 3 == 0 else "NEUTRAL",
            "timestamp": "2026-07-2%dT10:00:00Z" % (i % 10),
        })
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"experiments": experiments, "current_best": "v6"}))
    return path


def test_compaction_archives_the_full_records(tmp_path):
    path = _history(tmp_path, 8)
    compact_history(str(path), detailed_keep=5)
    archive = tmp_path / "history.archive.jsonl"
    assert archive.exists()
    archived = [json.loads(line) for line in archive.read_text().splitlines()]
    assert [a["id"] for a in archived] == ["exp-001", "exp-002", "exp-003"]
    assert archived[0]["hypothesis"] == "Hypothese Nummer 1 im Wortlaut"


def test_compaction_is_idempotent(tmp_path):
    """SKILL.md lässt die Kompaktierung ab Experiment 6 in jeder Runde laufen."""
    path = _history(tmp_path, 8)
    for _ in range(4):
        compact_history(str(path), detailed_keep=5)
    archive = tmp_path / "history.archive.jsonl"
    lines = [line for line in archive.read_text().splitlines() if line.strip()]
    assert len(lines) == 3


def test_compaction_keeps_mutation_type(tmp_path):
    """Das Meta-Memory braucht mutation_type, die alte Fassung warf ihn weg."""
    path = _history(tmp_path, 8)
    result = compact_history(str(path), detailed_keep=5)
    compacted = [e for e in result["experiments"] if e.get("_compacted")]
    assert compacted
    assert all("mutation_type" in e for e in compacted)


def test_compaction_below_the_threshold_changes_nothing(tmp_path):
    path = _history(tmp_path, 3)
    before = path.read_text()
    compact_history(str(path), detailed_keep=5)
    assert path.read_text() == before
    assert not (tmp_path / "history.archive.jsonl").exists()


def test_compaction_survives_a_record_without_id(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"experiments": [
        {"category": "workflow", "delta": "+0.01", "decision": "NEUTRAL"},
        {"id": "exp-002", "delta": "+0.02", "decision": "KEEP"},
    ]}))
    compact_history(str(path), detailed_keep=1)   # darf keinen KeyError werfen


def test_agent_history_handles_string_deltas(tmp_path):
    """max() über gemischte str/float wirft TypeError."""
    path = _history(tmp_path, 8)
    view = get_history_for_agent(str(path), detailed_keep=5)
    assert isinstance(view["stats"]["best_delta"], float)
    assert len(view["experiments_detailed"]) == 5


def test_agent_history_survives_duplicate_records(tmp_path):
    """Die alte Fassung nutzte experiments.index(exp), das den ERSTEN Treffer
    liefert. Zwei gleiche Dicts landeten damit beide im falschen Eimer."""
    entry = {"id": "exp-001", "delta": "+0.01", "decision": "NEUTRAL"}
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"experiments": [dict(entry) for _ in range(6)]}))
    view = get_history_for_agent(str(path), detailed_keep=2)
    assert len(view["experiments_detailed"]) == 2
    assert len(view["experiments_summary"]) == 4


def test_group_history_compares_deltas_numerically(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"experiments": [
        {"id": "exp-001", "category": "workflow", "delta": "+0.09",
         "decision": "KEEP", "hypothesis": "a"},
        {"id": "exp-002", "category": "workflow", "delta": "+0.10",
         "decision": "KEEP", "hypothesis": "b"},
    ]}))
    grouped = group_history_by_category(str(path))
    assert grouped["workflow"]["best_experiment"] == "exp-002"
    assert grouped["workflow"]["best_delta"] == pytest.approx(0.10)


def test_checkpoint_roundtrip_carries_the_new_fields(tmp_path):
    save_checkpoint(
        str(tmp_path), "exp-003", 0.78, {"coverage_summary": {"coverage_percent": 62.5}},
        next_category="edge_cases", on_disk_version="pre-exp-004",
        applied_but_undecided=True, best_version="pre-exp-003",
        best_score=0.81, experiment_index=3,
    )
    loaded = load_checkpoint(str(tmp_path))
    assert loaded["applied_but_undecided"] is True
    assert loaded["on_disk_version"] == "pre-exp-004"
    assert loaded["best_score"] == 0.81
    assert loaded["experiment_index"] == 3


def test_resume_info_warns_about_an_undecided_mutation(tmp_path):
    save_checkpoint(
        str(tmp_path), "exp-003", 0.78, {},
        on_disk_version="pre-exp-004", applied_but_undecided=True,
    )
    info = get_resume_info(str(tmp_path))
    assert "pre-exp-004" in info
    assert "ACHTUNG" in info


def test_resume_info_survives_a_v2_checkpoint(tmp_path):
    """Nur die fünf Felder aus v2, keine der neuen."""
    (tmp_path / "checkpoint.json").write_text(json.dumps({
        "last_completed_experiment": "exp-002",
        "current_baseline_score": 0.71,
        "coverage_snapshot": {},
        "next_planned_category": None,
        "timestamp": "2026-07-01T22:00:00Z",
    }))
    info = get_resume_info(str(tmp_path))
    assert "exp-002" in info
    assert "0.7100" in info


def test_resume_info_survives_a_broken_checkpoint(tmp_path):
    (tmp_path / "checkpoint.json").write_text(json.dumps({"resumable": True}))
    info = get_resume_info(str(tmp_path))
    assert "unbekannt" in info


def test_resume_info_without_checkpoint(tmp_path):
    assert "frischer Start" in get_resume_info(str(tmp_path))


def test_group_history_respects_direction(tmp_path):
    """Bei lower_is_better war die schlimmste Regression der Bestwert, und der
    Hypothesis-Agent bekam in der Spätphase die falsche Kategorie empfohlen."""
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"experiments": [
        {"id": "exp-001", "category": "bundle", "delta": -20.0, "decision": "KEEP"},
        {"id": "exp-002", "category": "bundle", "delta": 35.0, "decision": "REVERT"},
    ]}))
    grouped = group_history_by_category(str(path), direction="lower_is_better")
    assert grouped["bundle"]["best_experiment"] == "exp-001"
    assert grouped["bundle"]["best_delta"] == pytest.approx(20.0)


def test_agent_history_best_delta_respects_direction(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"experiments": [
        {"id": "exp-001", "delta": -20.0, "decision": "KEEP"},
        {"id": "exp-002", "delta": 35.0, "decision": "REVERT"},
    ]}))
    view = get_history_for_agent(str(path), direction="lower_is_better")
    assert view["stats"]["best_delta"] == pytest.approx(20.0)
