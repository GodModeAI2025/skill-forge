"""Der Musterbestand des Optimierers.

Vorher war das Gedächtnis acht Bullets, alle fünf Experimente neu geschrieben —
bewusst vergesslich, damit der Kontext klein bleibt. WikiSkills Ablation
(arXiv:2608.27454) misst für persistentes, verdichtetes Optimierer-Wissen
+15,0 Punkte im Schnitt. Was hier festgenagelt wird, ist der Mechanismus, der
das bezahlbar macht (Index im Kontext, Seiten auf Abruf) und die Disziplin, die
verhindert, dass ein unbegrenzter Bestand zu Rauschen wird.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.patterns import (
    MIN_SUPPORT,
    add_evidence,
    add_pattern,
    build_index,
    find_pattern,
    format_index,
    next_pattern_id,
    parse_pattern,
    pattern_stats,
    read_patterns,
    show_pattern,
    update_pattern,
)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "patterns.py"

MUSTER = {
    "title": "Beispiele nehmen, Prosa-Umformulierungen nicht",
    "observation": "Drei instruction_edit blieben NEUTRAL, zwei example_add wurden behalten.",
    "consequence": "Zuerst das Beispiel versuchen, die Regelformulierung danach.",
    "category": "examples",
}


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True)


@pytest.fixture
def ws(tmp_path):
    add_pattern(str(tmp_path), **MUSTER)
    return str(tmp_path)


# ─── Persistenz statt Deckel ──────────────────────────────────────────────


def test_the_store_is_not_capped(tmp_path):
    """Der Kern der Änderung.

    Die alte editing-notes.md hielt acht Bullets und wurde alle fünf
    Experimente neu geschrieben: jede Erkenntnis fiel nach spätestens zwei
    Runden heraus, sobald eine neuere wichtiger schien.
    """
    for i in range(12):
        add_pattern(str(tmp_path), title="Muster %d" % i,
                    observation="Beobachtung %d" % i, consequence="Folge %d" % i)
    assert len(read_patterns(str(tmp_path))) == 12


def test_evidence_accumulates_across_experiments(ws):
    """Verdichten statt anhängen: eine Seite, viele Belege."""
    add_evidence(ws, "P-0001", experiment="exp-002", decision="NEUTRAL",
                 delta=-0.005, mutation_type="instruction_edit")
    add_evidence(ws, "P-0001", experiment="exp-005", decision="KEEP",
                 delta=0.070, mutation_type="example_add")
    add_evidence(ws, "P-0001", experiment="exp-009", decision="NEUTRAL",
                 delta=0.010, mutation_type="instruction_edit")

    pattern = find_pattern(ws, "P-0001")
    assert [e["experiment"] for e in pattern["evidence"]] == [
        "exp-002", "exp-005", "exp-009"
    ]
    assert pattern["support"] == 3
    assert pattern["best_delta"] == pytest.approx(0.070)


def test_refining_a_pattern_keeps_its_evidence(ws):
    """Patch statt Neuschreiben. Sonst beginnt die Stützzahl bei null."""
    add_evidence(ws, "P-0001", experiment="exp-002", decision="KEEP", delta=0.05)
    update_pattern(ws, "P-0001", consequence="Neue Konsequenz, gleiches Muster.")
    pattern = find_pattern(ws, "P-0001")
    assert pattern["support"] == 1
    assert "Neue Konsequenz" in Path(pattern["path"]).read_text(encoding="utf-8")
    assert "exp-002" in Path(pattern["path"]).read_text(encoding="utf-8")


# ─── Belegdisziplin ───────────────────────────────────────────────────────


def test_a_single_experiment_is_provisional(ws):
    """Dieselbe Regel wie min_support_count bei den Hypothesen."""
    add_evidence(ws, "P-0001", experiment="exp-002", decision="KEEP", delta=0.05)
    assert find_pattern(ws, "P-0001")["provisional"] is True
    add_evidence(ws, "P-0001", experiment="exp-005", decision="KEEP", delta=0.03)
    assert find_pattern(ws, "P-0001")["provisional"] is False
    assert MIN_SUPPORT == 2


def test_unmeasured_decisions_do_not_count_as_support(ws):
    """DEFERRED, SKIP, INVALID und NO_OP haben nichts gemessen.

    Zählten sie mit, wäre ein Muster nach drei abgebrochenen Runden belegt.
    """
    for i, decision in enumerate(("DEFERRED", "SKIP", "INVALID", "NO_OP"), 1):
        add_evidence(ws, "P-0001", experiment="exp-00%d" % i,
                     decision=decision, delta=0.0)
    pattern = find_pattern(ws, "P-0001")
    assert pattern["support"] == 0
    assert pattern["provisional"] is True
    assert len(pattern["evidence"]) == 4, "protokolliert sind sie trotzdem"


def test_replaying_an_experiment_does_not_double_the_support(ws):
    """Sonst wüchse die Stützzahl durch Wiederholung statt durch Bestätigung."""
    add_evidence(ws, "P-0001", experiment="exp-002", decision="KEEP", delta=0.05)
    result = add_evidence(ws, "P-0001", experiment="exp-002", decision="KEEP",
                          delta=0.05)
    assert result["replaced"] is True
    assert result["support"] == 1


def test_derived_numbers_are_recomputed_not_stored(ws):
    """Die Lektion aus der Coverage-Matrix.

    Dort rastete `saturated` ein: einmal gesetzt, erholte sich eine Kategorie
    nach einem späteren Treffer nie mehr. Ein abgeleiteter Wert auf der Platte
    ist ein Wert, der veraltet.
    """
    add_evidence(ws, "P-0001", experiment="exp-002", decision="KEEP", delta=0.05)
    text = Path(find_pattern(ws, "P-0001")["path"]).read_text(encoding="utf-8")
    assert "support" not in text
    assert "provisional" not in text
    assert "best_delta" not in text


def test_no_single_hit_rate_is_reported(ws):
    """Bewusst keine Quote.

    Ein Muster kann positiv behaupten ("Beispiele nehmen hier") oder negativ
    ("Prosa nicht") — im zweiten Fall belegen NEUTRAL-Zeilen das Muster und
    KEEP-Zeilen widersprächen ihm. Eine Quote hiesse für beide Gegenteiliges.
    """
    add_evidence(ws, "P-0001", experiment="exp-002", decision="KEEP", delta=0.05)
    pattern = find_pattern(ws, "P-0001")
    assert "hit_rate" not in pattern
    assert pattern["counts"]["KEEP"] == 1


# ─── Irrtümer bleiben stehen ──────────────────────────────────────────────


def test_refuting_a_pattern_needs_the_contradicting_experiment(ws):
    with pytest.raises(ValueError, match="refuted_by"):
        update_pattern(ws, "P-0001", status="widerlegt")

    result = update_pattern(ws, "P-0001", status="widerlegt",
                            refuted_by="exp-011")
    assert result["status"] == "widerlegt"


def test_a_refuted_pattern_stays_readable(ws):
    """Damit derselbe Irrtum nicht in drei Runden neu entdeckt wird."""
    update_pattern(ws, "P-0001", status="widerlegt", refuted_by="exp-011")
    assert len(read_patterns(ws)) == 1
    assert "exp-011" in show_pattern(ws, "P-0001")
    assert "widerlegt" in format_index(ws)


def test_a_second_page_on_the_same_title_is_refused(ws):
    """Sonst zerfällt die Evidenz auf zwei Seiten und beide bleiben vorläufig."""
    with pytest.raises(ValueError, match="existiert schon"):
        add_pattern(ws, **MUSTER)


@pytest.mark.parametrize("field", ["title", "observation", "consequence"])
def test_every_field_is_required(tmp_path, field):
    with pytest.raises(ValueError, match=field):
        add_pattern(str(tmp_path), **dict(MUSTER, **{field: "  "}))


def test_unknown_pattern_and_status_are_refused(ws):
    with pytest.raises(KeyError):
        add_evidence(ws, "P-0099", experiment="exp-001", decision="KEEP",
                     delta=0.0)
    with pytest.raises(ValueError):
        add_evidence(ws, "P-0001", experiment="exp-001", decision="AKZEPTIERT",
                     delta=0.0)
    with pytest.raises(ValueError):
        update_pattern(ws, "P-0001", status="egal")


# ─── Index im Kontext, Seiten auf Abruf ───────────────────────────────────


def test_only_the_index_goes_into_the_prompt(ws):
    """Der Mechanismus, der einen unbegrenzten Bestand bezahlbar macht.

    Ohne diese Trennung wäre er genau das Kontextproblem, gegen das der
    Achter-Deckel einmal gebaut wurde.
    """
    block = format_index(ws)
    assert MUSTER["title"] in block
    assert MUSTER["observation"] not in block
    assert MUSTER["consequence"] not in block
    assert "patterns.py show" in block


def test_the_index_carries_the_precedence_rule(ws):
    block = format_index(ws)
    assert "mehrdeutig" in block
    assert "klar widersprechen" in block
    assert "nichts hier gehört in die Ziel-SKILL.md" in block.replace("\n", " ")


def test_the_index_grows_slowly(tmp_path):
    """Zwanzig Muster müssen noch in einen Prompt passen."""
    for i in range(20):
        add_pattern(str(tmp_path), title="Muster %d" % i,
                    observation="Beobachtung", consequence="Folge")
    assert pattern_stats(str(tmp_path))["index_tokens"] < 1200


def test_the_index_is_deterministic(ws):
    add_evidence(ws, "P-0001", experiment="exp-002", decision="KEEP", delta=0.05)
    assert build_index(ws) == build_index(ws)


def test_an_empty_store_formats_to_nothing(tmp_path):
    assert format_index(str(tmp_path)) == ""
    build_index(str(tmp_path))
    assert format_index(str(tmp_path)) == ""


def test_ids_continue_after_a_refutation(ws):
    update_pattern(ws, "P-0001", status="widerlegt", refuted_by="exp-011")
    assert next_pattern_id(ws) == "P-0002"


# ─── CLI ──────────────────────────────────────────────────────────────────


def test_cli_add_evidence_and_format(tmp_path):
    workspace = str(tmp_path)
    added = run("add", workspace, "--title", MUSTER["title"],
                "--observation", MUSTER["observation"],
                "--consequence", MUSTER["consequence"],
                "--category", "examples")
    assert added.returncode == 0
    assert json.loads(added.stdout)["created"][0]["pattern_id"] == "P-0001"

    ev = run("evidence", workspace, "P-0001", "--experiment", "exp-002",
             "--decision", "KEEP", "--delta", "0.07")
    assert ev.returncode == 0
    assert json.loads(ev.stdout)["support"] == 1

    assert MUSTER["title"] in run("format", workspace).stdout
    assert MUSTER["observation"] in run("show", workspace, "P-0001").stdout


def test_cli_add_reads_the_meta_agent_output(tmp_path):
    payload = tmp_path / "meta.json"
    payload.write_text(json.dumps({"patterns": [
        dict(MUSTER),
        {"title": "Zweites Muster", "observation": "B", "consequence": "C"},
    ]}), encoding="utf-8")
    result = run("add", str(tmp_path), "--title", "x", "--observation", "y",
                 "--consequence", "z", "--from-json", str(payload))
    assert result.returncode == 0
    assert len(json.loads(result.stdout)["created"]) == 2


def test_cli_add_exits_two_when_nothing_was_created(tmp_path):
    payload = tmp_path / "meta.json"
    payload.write_text(json.dumps({"patterns": [
        {"title": "Ohne Beobachtung", "observation": "", "consequence": "C"},
    ]}), encoding="utf-8")
    result = run("add", str(tmp_path), "--title", "x", "--observation", "y",
                 "--consequence", "z", "--from-json", str(payload))
    assert result.returncode == 2
    assert json.loads(result.stdout)["skipped"][0]["title"] == "Ohne Beobachtung"


def test_cli_unknown_pattern_reports_on_stderr(tmp_path):
    result = run("show", str(tmp_path), "P-0099")
    assert result.returncode == 1
    assert "Unbekanntes Muster" in result.stderr
