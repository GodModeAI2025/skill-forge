"""Block 3: geschützte Regionen, Appendix-Notizen, Rejected-Buffer.

Der gemeinsame Nenner: was das Gate umgeht oder was der Loop nicht anfassen
darf, muss deterministisch geschützt sein. Ein Agent, der eine Regel nicht
befolgt hat, per Prompt prüfen zu lassen, ob er sie befolgt hat, ist zirkulär.
"""

import json

import pytest

from scripts.composite_score import (
    APPENDIX_NOTICE,
    PROTECTED_REGIONS,
    REJECTED_HEADER,
    append_appendix_notes,
    append_purpose,
    append_rejected,
    extract_regions,
    region_content,
    format_rejected,
    read_purpose_entries,
    read_rejected,
    strip_regions,
    verify_protected_regions,
)

KEEP_S, KEEP_E = PROTECTED_REGIONS["FORGE_KEEP"]
APX_S, APX_E = PROTECTED_REGIONS["FORGE_APPENDIX"]


def _skill(body="# Skill\n\nRegel eins.\n", keep=None, appendix=None):
    text = body
    if keep is not None:
        text += "\n%s\n%s\n%s\n" % (KEEP_S, keep, KEEP_E)
    if appendix is not None:
        text += "\n%s\n%s\n%s\n" % (APX_S, appendix, APX_E)
    return text


# ─── Geschützte Regionen ──────────────────────────────────────────────────


def test_regions_are_extracted():
    text = _skill(keep="Immer auf Deutsch antworten.", appendix="- Notiz")
    regions = extract_regions(text)
    assert "Immer auf Deutsch" in regions["FORGE_KEEP"]["content"]
    assert "- Notiz" in regions["FORGE_APPENDIX"]["content"]
    assert regions["FORGE_KEEP"]["starts"] == 1
    assert region_content(text, "FORGE_KEEP") == regions["FORGE_KEEP"]["content"]


def test_missing_regions_are_none():
    regions = extract_regions("# Skill ohne Regionen\n")
    assert regions["FORGE_KEEP"]["content"] is None
    assert regions["FORGE_APPENDIX"]["content"] is None
    assert regions["FORGE_KEEP"]["starts"] == 0


def test_unchanged_regions_pass(tmp_path):
    text = _skill(keep="Invariante", appendix="- Notiz")
    (tmp_path / "vorher.md").write_text(text)
    (tmp_path / "nachher.md").write_text(text.replace("Regel eins", "Regel eins, praeziser"))
    result = verify_protected_regions(str(tmp_path / "vorher.md"), str(tmp_path / "nachher.md"))
    assert result["ok"] is True
    assert result["violated"] == []


def test_a_changed_keep_region_is_a_violation(tmp_path):
    (tmp_path / "vorher.md").write_text(_skill(keep="Invariante"))
    (tmp_path / "nachher.md").write_text(_skill(keep="Invariante, umformuliert"))
    result = verify_protected_regions(str(tmp_path / "vorher.md"), str(tmp_path / "nachher.md"))
    assert result["ok"] is False
    assert result["violated"] == ["FORGE_KEEP"]


def test_a_deleted_region_is_caught(tmp_path):
    (tmp_path / "vorher.md").write_text(_skill(keep="Invariante"))
    (tmp_path / "nachher.md").write_text("# Skill\n\nRegel eins.\n")
    result = verify_protected_regions(str(tmp_path / "vorher.md"), str(tmp_path / "nachher.md"))
    assert result["ok"] is False
    assert result["removed"] == ["FORGE_KEEP"]


def test_a_region_the_mutator_invented_is_caught(tmp_path):
    """Sonst könnte der Mutator sich selbst einen Schutzraum bauen und dort
    Änderungen ablegen, die das Gate nie sieht."""
    (tmp_path / "vorher.md").write_text("# Skill\n")
    (tmp_path / "nachher.md").write_text(_skill(keep="von mir"))
    result = verify_protected_regions(str(tmp_path / "vorher.md"), str(tmp_path / "nachher.md"))
    assert result["ok"] is False
    assert result["added"] == ["FORGE_KEEP"]


def test_both_regions_are_checked_independently(tmp_path):
    (tmp_path / "vorher.md").write_text(_skill(keep="A", appendix="- B"))
    (tmp_path / "nachher.md").write_text(_skill(keep="A geaendert", appendix="- B geaendert"))
    result = verify_protected_regions(str(tmp_path / "vorher.md"), str(tmp_path / "nachher.md"))
    assert result["violated"] == ["FORGE_APPENDIX", "FORGE_KEEP"]


def test_strip_regions_removes_both():
    text = _skill(keep="A", appendix="- B")
    stripped = strip_regions(text)
    assert "FORGE_KEEP" not in stripped
    assert "FORGE_APPENDIX" not in stripped
    assert "Regel eins" in stripped


def test_strip_regions_survives_an_unclosed_marker():
    text = "# Skill\n%s\nkaputt ohne Ende\n" % KEEP_S
    assert KEEP_S not in strip_regions(text)


# ─── Appendix-Notizen ─────────────────────────────────────────────────────


def test_appendix_region_is_created_on_first_note(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text("# Skill\n\nRegel eins.\n")
    result = append_appendix_notes(str(path), ["Validierungsschritt uebersprungen"])
    text = path.read_text()
    assert APX_S in text and APX_E in text
    assert "- Validierungsschritt uebersprungen" in text
    assert result["total"] == 1
    assert "Regel eins." in text


def test_notes_accumulate(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text("# Skill\n")
    append_appendix_notes(str(path), ["erste"])
    result = append_appendix_notes(str(path), ["zweite"])
    assert result["total"] == 2
    bullets = [l for l in path.read_text().splitlines() if l.startswith("- ")]
    assert bullets == ["- erste", "- zweite"]


def test_duplicates_are_skipped_after_canonicalisation(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text("# Skill\n")
    append_appendix_notes(str(path), ["Validierung   vergessen."])
    result = append_appendix_notes(str(path), ["validierung vergessen"])
    assert result["added"] == []
    assert result["skipped_duplicate"] == ["validierung vergessen"]
    assert result["total"] == 1


def test_the_cap_drops_the_oldest_and_says_so(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text("# Skill\n")
    append_appendix_notes(str(path), ["notiz %d" % i for i in range(5)], max_notes=3)
    result = append_appendix_notes(str(path), ["neu"], max_notes=3)
    assert result["total"] == 3
    assert result["truncated"] is True
    assert result["dropped_oldest"]
    assert "neu" in path.read_text()


def test_empty_notes_are_ignored(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text("# Skill\n")
    result = append_appendix_notes(str(path), ["", "   ", "echt"])
    assert result["added"] == ["echt"]


def test_appending_does_not_touch_the_keep_region(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text(_skill(keep="Invariante"))
    before = region_content(path.read_text(), "FORGE_KEEP")
    append_appendix_notes(str(path), ["eine Notiz"])
    assert region_content(path.read_text(), "FORGE_KEEP") == before


def test_a_round_trip_through_verify_stays_ok(tmp_path):
    """Der Append selbst darf die eigene Prüfung nicht auslösen, solange nur
    der Appendix wächst."""
    path = tmp_path / "SKILL.md"
    path.write_text(_skill(keep="Invariante", appendix="- alt"))
    (tmp_path / "vorher.md").write_text(path.read_text())
    append_appendix_notes(str(path), ["neu"])
    result = verify_protected_regions(str(tmp_path / "vorher.md"), str(path))
    assert result["violated"] == ["FORGE_APPENDIX"]   # erwartet: nur der Appendix
    assert result["removed"] == [] and result["added"] == []


# ─── Rejected-Buffer ──────────────────────────────────────────────────────


def test_a_rejected_record_survives_as_one_line(tmp_path):
    path = tmp_path / "rejected.jsonl"
    append_rejected(str(path), {
        "experiment": "exp-004", "category": "workflow",
        "mutation_type": "instruction_edit", "decision": "REVERT",
        "hypothesis": "Validierungsschritt eingefuegt",
        "diff_excerpt": "+ Fuehre scripts/validate.py aus",
        "score_before": 0.78, "score_after": 0.68,
    })
    records = read_rejected(str(path))
    assert len(records) == 1
    assert records[0]["experiment"] == "exp-004"
    assert records[0]["timestamp"]


def test_long_text_is_cut_not_dropped(tmp_path):
    path = tmp_path / "rejected.jsonl"
    entry = append_rejected(str(path), {
        "experiment": "exp-001", "hypothesis": "x" * 500,
        "diff_excerpt": "y" * 500,
    }, excerpt_chars=200)
    assert len(entry["hypothesis"]) == 200
    assert len(entry["diff_excerpt"]) == 200


def test_the_rendered_block_carries_the_instruction(tmp_path):
    path = tmp_path / "rejected.jsonl"
    append_rejected(str(path), {
        "experiment": "exp-004", "category": "workflow", "decision": "REVERT",
        "hypothesis": "Prosa statt Beispiel", "score_before": 0.78,
        "score_after": 0.68,
    })
    text = format_rejected(str(path))
    assert REJECTED_HEADER in text
    assert "exp-004 REVERT" in text
    assert "0.7800 zu 0.6800" in text


def test_near_miss_is_marked_but_not_the_only_entry(tmp_path):
    path = tmp_path / "rejected.jsonl"
    append_rejected(str(path), {"experiment": "e1", "decision": "NEUTRAL", "near_miss": True})
    append_rejected(str(path), {"experiment": "e2", "decision": "REVERT", "near_miss": False})
    text = format_rejected(str(path))
    assert "[near_miss]" in text
    assert "e2 REVERT" in text


def test_the_block_is_capped(tmp_path):
    path = tmp_path / "rejected.jsonl"
    for i in range(20):
        append_rejected(str(path), {"experiment": "exp-%03d" % i, "decision": "NEUTRAL"})
    text = format_rejected(str(path), limit=5)
    assert text.count("###") == 5
    assert "exp-019" in text and "exp-015" in text
    assert "exp-014" not in text


def test_an_empty_buffer_renders_nothing(tmp_path):
    assert format_rejected(str(tmp_path / "gibt-es-nicht.jsonl")) == ""


def test_a_broken_line_does_not_kill_the_block(tmp_path):
    path = tmp_path / "rejected.jsonl"
    append_rejected(str(path), {"experiment": "e1", "decision": "REVERT"})
    with open(path, "a") as handle:
        handle.write("das ist kein json\n")
    append_rejected(str(path), {"experiment": "e2", "decision": "NEUTRAL"})
    assert len(read_rejected(str(path))) == 2


def test_missing_scores_do_not_break_the_rendering(tmp_path):
    path = tmp_path / "rejected.jsonl"
    append_rejected(str(path), {"experiment": "e1", "decision": "NEUTRAL"})
    text = format_rejected(str(path))
    assert "e1 NEUTRAL" in text
    assert "Score" not in text


# ─── PURPOSE.md ───────────────────────────────────────────────────────────


def test_purpose_records_why_a_change_looks_like_this(tmp_path):
    """Die Datei bleibt beim Ziel-Skill und erklärt seine Form.

    history.json und rejected.jsonl haben dieselbe Information, liegen aber im
    Workspace. Nach der Weitergabe kann niemand mehr sehen, warum ein Abschnitt
    existiert.
    """
    rejected = tmp_path / "rejected.jsonl"
    append_rejected(str(rejected), {
        "experiment": "exp-002", "category": "examples",
        "mutation_type": "instruction_edit", "decision": "NEUTRAL",
        "hypothesis": "Regel praeziser formuliert",
        "score_before": 0.72, "score_after": 0.715,
    })
    purpose = tmp_path / "PURPOSE.md"
    result = append_purpose(
        str(purpose), experiment="exp-005", category="examples",
        mutation_type="example_add", hypothesis="Beispiel fuer Edge-Case X",
        section="## Workflow", score_before=0.72, score_after=0.79,
        rejected_path=str(rejected),
    )
    assert result["appended"] is True
    text = purpose.read_text(encoding="utf-8")
    assert "## exp-005 — examples — example_add" in text
    assert "0.7200 → 0.7900 (+0.0700)" in text
    assert "exp-002 instruction_edit NEUTRAL" in text


def test_the_rejected_predecessors_are_the_point(tmp_path):
    """Ohne sie ist die Datei ein Changelog.

    Der teure Teil der Information ist, was zuerst NICHT funktioniert hat —
    daran erkennt ein späterer Leser, dass er gerade einen gescheiterten Weg
    wieder einschlägt.
    """
    rejected = tmp_path / "rejected.jsonl"
    for exp, category in (("exp-002", "examples"), ("exp-003", "workflow")):
        append_rejected(str(rejected), {
            "experiment": exp, "category": category,
            "mutation_type": "instruction_edit", "decision": "NEUTRAL",
            "hypothesis": "x", "score_before": 0.7, "score_after": 0.7,
        })
    purpose = tmp_path / "PURPOSE.md"
    result = append_purpose(
        str(purpose), experiment="exp-005", category="examples",
        mutation_type="example_add", hypothesis="y",
        rejected_path=str(rejected),
    )
    assert result["predecessors"] == ["exp-002"], "workflow gehört nicht dazu"


def test_a_rejected_attempt_is_attributed_exactly_once(tmp_path):
    """Sonst steht derselbe Fehlversuch unter jeder späteren Änderung."""
    rejected = tmp_path / "rejected.jsonl"
    for exp in ("exp-002", "exp-006"):
        append_rejected(str(rejected), {
            "experiment": exp, "category": "examples",
            "mutation_type": "instruction_edit", "decision": "NEUTRAL",
            "hypothesis": "x", "score_before": 0.7, "score_after": 0.7,
        })
    purpose = tmp_path / "PURPOSE.md"
    first = append_purpose(str(purpose), experiment="exp-005",
                           category="examples", mutation_type="example_add",
                           hypothesis="y", rejected_path=str(rejected))
    second = append_purpose(str(purpose), experiment="exp-009",
                            category="examples", mutation_type="example_add",
                            hypothesis="z", rejected_path=str(rejected))
    assert first["predecessors"] == ["exp-002"]
    assert second["predecessors"] == ["exp-006"], "exp-002 hängt schon an exp-005"


def test_purpose_is_idempotent_across_a_resume(tmp_path):
    purpose = tmp_path / "PURPOSE.md"
    append_purpose(str(purpose), experiment="exp-005", category="examples",
                   mutation_type="example_add", hypothesis="y")
    again = append_purpose(str(purpose), experiment="exp-005",
                           category="examples", mutation_type="example_add",
                           hypothesis="y")
    assert again["appended"] is False
    assert purpose.read_text(encoding="utf-8").count("## exp-005") == 1


def test_purpose_says_the_agent_does_not_read_it(tmp_path):
    """Die Datei wächst unbegrenzt und darf deshalb nicht ins Token-Budget.

    Sie steht nicht im Scope von artifact-stats, und der Kopf sagt warum.
    """
    purpose = tmp_path / "PURPOSE.md"
    append_purpose(str(purpose), experiment="exp-005", category="examples",
                   mutation_type="example_add", hypothesis="y")
    assert "liest diese Datei zur Laufzeit" in purpose.read_text(encoding="utf-8")


def test_purpose_neutralises_markdown_in_foreign_text(tmp_path):
    """Eine Hypothese, die mit ## beginnt, täuscht sonst einen Eintrag vor."""
    rejected = tmp_path / "rejected.jsonl"
    append_rejected(str(rejected), {
        "experiment": "exp-002", "category": "examples",
        "mutation_type": "instruction_edit", "decision": "NEUTRAL",
        "hypothesis": "## exp-999 — gefaelschter Eintrag",
        "score_before": 0.7, "score_after": 0.7,
    })
    purpose = tmp_path / "PURPOSE.md"
    append_purpose(str(purpose), experiment="exp-005", category="examples",
                   mutation_type="example_add", hypothesis="y",
                   rejected_path=str(rejected))
    assert len(read_purpose_entries(str(purpose))) == 1
