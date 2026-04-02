#!/usr/bin/env python3
"""Composite Score Berechnung und TSV-Logging für Skill Forge.

Berechnet einen gewichteten Score aus:
- Assertion Pass Rate (50%)
- LLM Judge Score (30%)
- Efficiency Score (20%)

Unterstützt zwei Modi:
- Skill-Modus: Composite Score aus Assertions + Judge + Effizienz
- Generic-Modus: Direkte Metrik-Extraktion aus Shell-Command-Output

Schreibt Ergebnisse sowohl als JSON als auch als TSV-Zeile.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path


# ─── Skill-Modus Scoring ──────────────────────────────────────────────────


def calc_assertion_pass_rate(grading_results: list[dict]) -> float:
    """Berechne die Gesamt-Pass-Rate über alle Grading-Ergebnisse."""
    total_passed = 0
    total_assertions = 0
    for grading in grading_results:
        summary = grading.get("summary", {})
        total_passed += summary.get("passed", 0)
        total_assertions += summary.get("total", 0)
    if total_assertions == 0:
        return 0.0
    return total_passed / total_assertions


def calc_efficiency_score(
    tokens_used: int,
    duration_seconds: float,
    max_tokens: int = 100000,
    max_duration: float = 300.0,
) -> float:
    """Berechne den Effizienz-Score (0-1, höher = effizienter).

    Normalisiert Token-Verbrauch und Laufzeit auf [0,1] und mittelt.
    """
    token_score = max(0.0, 1.0 - (tokens_used / max_tokens))
    time_score = max(0.0, 1.0 - (duration_seconds / max_duration))
    return (token_score + time_score) / 2.0


def calc_composite_score(
    assertion_pass_rate: float,
    llm_judge_score: float | None = None,
    efficiency_score: float = 0.5,
    use_comparator: bool = False,
) -> float:
    """Berechne den gewichteten Composite Score.

    Gewichtung:
    - Mit Comparator:  assertions=0.50, judge=0.30, efficiency=0.20
    - Ohne Comparator: assertions=0.80, efficiency=0.20
    """
    if use_comparator and llm_judge_score is not None:
        return (
            assertion_pass_rate * 0.50
            + llm_judge_score * 0.30
            + efficiency_score * 0.20
        )
    else:
        return assertion_pass_rate * 0.80 + efficiency_score * 0.20


# ─── Generic-Modus Scoring ────────────────────────────────────────────────


def extract_metric_value(output: str) -> float | None:
    """Extrahiere einen einzelnen Zahlenwert aus Command-Output.

    Sucht nach der letzten Zahl im Output (Float oder Int).
    """
    import re

    numbers = re.findall(r"[-+]?\d*\.?\d+", output)
    if not numbers:
        return None
    return float(numbers[-1])


def calc_generic_delta(
    current_value: float,
    baseline_value: float,
    direction: str = "higher_is_better",
) -> dict:
    """Berechne Delta und Bewertung für Generic-Modus.

    Args:
        current_value: Aktueller Metrik-Wert
        baseline_value: Baseline-Wert
        direction: 'higher_is_better' oder 'lower_is_better'

    Returns:
        Dict mit delta, improved, normalized_delta
    """
    raw_delta = current_value - baseline_value

    if direction == "lower_is_better":
        improved = raw_delta < 0
        # Normalisiere: positive normalized_delta = Verbesserung
        normalized_delta = -raw_delta / max(abs(baseline_value), 1e-10)
    else:
        improved = raw_delta > 0
        normalized_delta = raw_delta / max(abs(baseline_value), 1e-10)

    return {
        "current_value": current_value,
        "baseline_value": baseline_value,
        "raw_delta": raw_delta,
        "normalized_delta": round(normalized_delta, 6),
        "improved": improved,
        "direction": direction,
    }


# ─── TSV-Logging ──────────────────────────────────────────────────────────


TSV_HEADER = [
    "timestamp",
    "experiment",
    "hypothesis_summary",
    "metric_before",
    "metric_after",
    "delta",
    "decision",
    "category",
    "duration_s",
]


def init_tsv_log(tsv_path: str) -> None:
    """Initialisiere eine neue TSV-Log-Datei mit Header."""
    path = Path(tsv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(TSV_HEADER)


def append_tsv_log(
    tsv_path: str,
    experiment_id: str,
    hypothesis_summary: str,
    metric_before: float,
    metric_after: float,
    delta: float,
    decision: str,
    category: str,
    duration_seconds: float,
) -> None:
    """Hänge eine Zeile an das TSV-Log an."""
    path = Path(tsv_path)
    if not path.exists():
        init_tsv_log(tsv_path)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = [
        timestamp,
        experiment_id,
        hypothesis_summary[:80],  # Kürzen für Lesbarkeit
        f"{metric_before:.4f}",
        f"{metric_after:.4f}",
        f"{delta:+.4f}",
        decision,
        category,
        f"{duration_seconds:.0f}",
    ]

    with open(path, "a", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(row)


def read_tsv_log(tsv_path: str) -> list[dict]:
    """Lies das TSV-Log und gib es als Liste von Dicts zurück."""
    path = Path(tsv_path)
    if not path.exists():
        return []

    with open(path, "r") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader)


# ─── Coverage-Matrix ──────────────────────────────────────────────────────


DEFAULT_SKILL_CATEGORIES = [
    "formatting",
    "content_quality",
    "examples",
    "workflow",
    "edge_cases",
    "efficiency",
    "scripts",
    "structure",
]


def init_coverage_matrix(
    matrix_path: str, categories: list[str] | None = None
) -> dict:
    """Initialisiere eine neue Coverage-Matrix."""
    if categories is None:
        categories = DEFAULT_SKILL_CATEGORIES

    matrix = {
        "categories": {},
        "coverage_summary": {
            "total_categories": len(categories),
            "touched_categories": 0,
            "saturated_categories": 0,
            "untouched_categories": list(categories),
            "coverage_percent": 0.0,
        },
    }

    for cat in categories:
        matrix["categories"][cat] = {
            "experiments_total": 0,
            "experiments_kept": 0,
            "experiments_reverted": 0,
            "last_experiment": None,
            "best_delta": None,
            "saturated": False,
        }

    path = Path(matrix_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(matrix, f, indent=2)

    return matrix


def update_coverage_matrix(
    matrix_path: str,
    category: str,
    experiment_id: str,
    decision: str,
    delta: float,
    saturation_threshold: int = 3,
    saturation_min_delta: float = 0.01,
) -> dict:
    """Aktualisiere die Coverage-Matrix nach einem Experiment.

    Args:
        matrix_path: Pfad zur coverage-matrix.json
        category: Kategorie des Experiments
        experiment_id: ID des Experiments
        decision: KEEP, REVERT oder NEUTRAL
        delta: Score-Delta des Experiments
        saturation_threshold: Min. Experimente für Sättigung
        saturation_min_delta: Min. Verbesserung um nicht saturiert zu sein
    """
    path = Path(matrix_path)
    with open(path, "r") as f:
        matrix = json.load(f)

    # Kategorie anlegen falls neu (Generic-Modus)
    if category not in matrix["categories"]:
        matrix["categories"][category] = {
            "experiments_total": 0,
            "experiments_kept": 0,
            "experiments_reverted": 0,
            "last_experiment": None,
            "best_delta": None,
            "saturated": False,
        }
        matrix["coverage_summary"]["total_categories"] += 1

    cat = matrix["categories"][category]
    cat["experiments_total"] += 1
    cat["last_experiment"] = experiment_id

    if decision == "KEEP":
        cat["experiments_kept"] += 1
    elif decision == "REVERT":
        cat["experiments_reverted"] += 1

    # Best Delta aktualisieren
    if cat["best_delta"] is None or delta > float(cat["best_delta"]):
        cat["best_delta"] = f"{delta:+.4f}"

    # Sättigungsprüfung
    if (
        cat["experiments_total"] >= saturation_threshold
        and (cat["best_delta"] is None or float(cat["best_delta"]) < saturation_min_delta)
    ):
        cat["saturated"] = True

    # Summary aktualisieren
    categories = matrix["categories"]
    touched = sum(1 for c in categories.values() if c["experiments_total"] > 0)
    saturated = sum(1 for c in categories.values() if c["saturated"])
    total = len(categories)
    untouched = [k for k, v in categories.items() if v["experiments_total"] == 0]

    matrix["coverage_summary"] = {
        "total_categories": total,
        "touched_categories": touched,
        "saturated_categories": saturated,
        "untouched_categories": untouched,
        "coverage_percent": round(touched / max(total, 1) * 100, 1),
    }

    with open(path, "w") as f:
        json.dump(matrix, f, indent=2)

    return matrix


# ─── Experiment-Verzeichnis Scoring ───────────────────────────────────────


def score_from_experiment_dir(experiment_dir: str, use_comparator: bool = False) -> dict:
    """Berechne den Composite Score aus einem Experiment-Verzeichnis (Skill-Modus).

    Erwartet folgende Dateien im Verzeichnis:
    - grading_results.json: Liste von Grading-Ergebnissen
    - timing.json: Timing-Daten (optional)
    - comparison.json: LLM-Judge-Ergebnis (optional, nur mit use_comparator)
    """
    exp_path = Path(experiment_dir)

    # Grading-Ergebnisse laden
    grading_file = exp_path / "grading_results.json"
    if grading_file.exists():
        grading_results = json.loads(grading_file.read_text())
    else:
        # Suche nach einzelnen grading.json Dateien in Unterordnern
        grading_results = []
        for gf in exp_path.rglob("grading.json"):
            grading_results.append(json.loads(gf.read_text()))

    assertion_pass_rate = calc_assertion_pass_rate(grading_results)

    # Timing-Daten laden
    total_tokens = 0
    total_duration = 0.0
    for tf in exp_path.rglob("timing.json"):
        timing = json.loads(tf.read_text())
        total_tokens += timing.get("total_tokens", 0)
        total_duration += timing.get("total_duration_seconds", 0)

    efficiency = calc_efficiency_score(total_tokens, total_duration)

    # Optional: LLM Judge Score
    llm_judge_score = None
    if use_comparator:
        comparison_file = exp_path / "comparison.json"
        if comparison_file.exists():
            comparison = json.loads(comparison_file.read_text())
            rubric = comparison.get("rubric", {})
            # Normalisiere den Score auf [0,1] (original ist 1-10)
            scores = []
            for side in rubric.values():
                if isinstance(side, dict) and "overall_score" in side:
                    scores.append(side["overall_score"] / 10.0)
            if scores:
                llm_judge_score = max(scores)  # Score des Kandidaten

    composite = calc_composite_score(
        assertion_pass_rate=assertion_pass_rate,
        llm_judge_score=llm_judge_score,
        efficiency_score=efficiency,
        use_comparator=use_comparator,
    )

    return {
        "composite_score": round(composite, 4),
        "assertion_pass_rate": round(assertion_pass_rate, 4),
        "llm_judge_score": round(llm_judge_score, 4) if llm_judge_score is not None else None,
        "efficiency_score": round(efficiency, 4),
        "details": {
            "total_tokens": total_tokens,
            "total_duration_seconds": round(total_duration, 1),
            "grading_files_found": len(grading_results),
        },
    }


# ─── Tiered History ──────────────────────────────────────────────────────


def compact_history(history_path: str, detailed_keep: int = 5) -> dict:
    """Komprimiere alte History-Einträge zu Kurzform.

    Behält die letzten `detailed_keep` Experimente vollständig,
    ältere werden auf Kernfelder reduziert. Verhindert Context-Overflow
    bei langen Experiment-Runs (>10 Experimente).
    """
    path = Path(history_path)
    if not path.exists():
        return {}

    with open(path, "r") as f:
        history = json.load(f)

    experiments = history.get("experiments", [])
    if len(experiments) <= detailed_keep:
        return history

    # Ältere Einträge komprimieren
    compacted = []
    for exp in experiments[:-detailed_keep]:
        compacted.append({
            "id": exp["id"],
            "version": exp.get("version"),
            "category": exp.get("category"),
            "composite_score": exp.get("composite_score"),
            "delta": exp.get("delta"),
            "decision": exp.get("decision"),
            "timestamp": exp.get("timestamp"),
            "_compacted": True,
        })

    # Letzte N Einträge behalten
    detailed = experiments[-detailed_keep:]

    history["experiments"] = compacted + detailed
    history["_compaction_info"] = {
        "compacted_count": len(compacted),
        "detailed_count": len(detailed),
        "last_compaction": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    with open(path, "w") as f:
        json.dump(history, f, indent=2)

    return history


def get_history_for_agent(history_path: str, detailed_keep: int = 5) -> dict:
    """Liefere eine agent-optimierte Sicht auf die History.

    Vollständige Details nur für die letzten N Experimente,
    ältere als kompakte Zusammenfassung. Ideal als Input
    für den Hypothesis Agent.
    """
    path = Path(history_path)
    if not path.exists():
        return {"experiments_detailed": [], "experiments_summary": [], "stats": {}}

    with open(path, "r") as f:
        history = json.load(f)

    experiments = history.get("experiments", [])

    summary = []
    detailed = []

    for exp in experiments:
        if exp.get("_compacted"):
            summary.append(exp)
        else:
            if len(experiments) - experiments.index(exp) <= detailed_keep:
                detailed.append(exp)
            else:
                summary.append({
                    "id": exp["id"],
                    "category": exp.get("category"),
                    "delta": exp.get("delta"),
                    "decision": exp.get("decision"),
                })

    # Statistiken für schnellen Überblick
    all_exps = experiments
    keeps = sum(1 for e in all_exps if e.get("decision") == "KEEP")
    reverts = sum(1 for e in all_exps if e.get("decision") == "REVERT")
    best_delta = max((e.get("delta", 0) for e in all_exps), default=0)

    return {
        "experiments_detailed": detailed,
        "experiments_summary": summary,
        "stats": {
            "total": len(all_exps),
            "keeps": keeps,
            "reverts": reverts,
            "best_delta": best_delta,
            "current_best": history.get("current_best"),
            "best_score": history.get("best_score"),
        },
    }


# ─── Checkpoint/Resume ────────────────────────────────────────────────────


def save_checkpoint(workspace_path: str, experiment_id: str,
                    baseline_score: float, coverage_state: dict,
                    next_category: str | None = None) -> dict:
    """Speichere einen Resume-Point nach jedem Experiment.

    Ermöglicht Unterbrechung und Fortsetzung über Sessions hinweg.

    Args:
        workspace_path: Pfad zum Skill-Forge Workspace
        experiment_id: ID des zuletzt abgeschlossenen Experiments
        baseline_score: Aktueller Baseline-Score
        coverage_state: Aktueller Coverage-Matrix-Zustand
        next_category: Geplante nächste Kategorie (optional)
    """
    checkpoint = {
        "last_completed_experiment": experiment_id,
        "current_baseline_score": baseline_score,
        "coverage_snapshot": coverage_state.get("coverage_summary", {}),
        "next_planned_category": next_category,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "resumable": True,
    }

    checkpoint_path = Path(workspace_path) / "checkpoint.json"
    with open(checkpoint_path, "w") as f:
        json.dump(checkpoint, f, indent=2)

    return checkpoint


def load_checkpoint(workspace_path: str) -> dict | None:
    """Lade den letzten Checkpoint für Resume.

    Returns:
        Checkpoint-Dict oder None wenn kein Checkpoint existiert.
    """
    checkpoint_path = Path(workspace_path) / "checkpoint.json"
    if not checkpoint_path.exists():
        return None

    with open(checkpoint_path, "r") as f:
        return json.load(f)


def get_resume_info(workspace_path: str) -> str:
    """Erzeuge eine menschenlesbare Resume-Info."""
    checkpoint = load_checkpoint(workspace_path)
    if checkpoint is None:
        return "Kein Checkpoint vorhanden — frischer Start."

    return (
        f"Resume von Checkpoint:\n"
        f"  Letztes Experiment: {checkpoint['last_completed_experiment']}\n"
        f"  Baseline-Score: {checkpoint['current_baseline_score']:.4f}\n"
        f"  Coverage: {checkpoint['coverage_snapshot'].get('coverage_percent', 0):.0f}%\n"
        f"  Gespeichert: {checkpoint['timestamp']}\n"
        f"  Nächste Kategorie: {checkpoint.get('next_planned_category', 'auto')}"
    )


# ─── Context-Grouping ────────────────────────────────────────────────────


def group_history_by_category(history_path: str) -> dict:
    """Gruppiere Experiment-History nach Kategorien statt chronologisch.

    Ideal als Input für den Hypothesis Agent: Pro Kategorie sieht er
    die beste Mutation, häufigste Failure-Patterns und Saturation-Status.
    """
    path = Path(history_path)
    if not path.exists():
        return {}

    with open(path, "r") as f:
        history = json.load(f)

    grouped = {}
    for exp in history.get("experiments", []):
        cat = exp.get("category", "unknown")
        if cat not in grouped:
            grouped[cat] = {
                "experiments": [],
                "total": 0,
                "keeps": 0,
                "reverts": 0,
                "best_delta": None,
                "best_experiment": None,
            }

        g = grouped[cat]
        g["experiments"].append({
            "id": exp["id"],
            "delta": exp.get("delta", 0),
            "decision": exp.get("decision"),
            "hypothesis": exp.get("hypothesis", "")[:80],
        })
        g["total"] += 1

        if exp.get("decision") == "KEEP":
            g["keeps"] += 1
        elif exp.get("decision") == "REVERT":
            g["reverts"] += 1

        delta = exp.get("delta", 0)
        if g["best_delta"] is None or delta > g["best_delta"]:
            g["best_delta"] = delta
            g["best_experiment"] = exp["id"]

    return grouped


# ─── CLI ──────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Skill Forge — Scoring & Logging")
    subparsers = parser.add_subparsers(dest="command", help="Verfügbare Befehle")

    # Score-Berechnung (Skill-Modus)
    score_parser = subparsers.add_parser("score", help="Composite Score berechnen")
    score_parser.add_argument("experiment_dir", help="Pfad zum Experiment-Verzeichnis")
    score_parser.add_argument(
        "--use-comparator",
        action="store_true",
        help="LLM-as-Judge Score einbeziehen",
    )
    score_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")

    # Metrik extrahieren (Generic-Modus)
    metric_parser = subparsers.add_parser("metric", help="Metrik aus Output extrahieren")
    metric_parser.add_argument("output", help="Command-Output oder '-' für stdin")
    metric_parser.add_argument(
        "--baseline", type=float, required=True, help="Baseline-Wert"
    )
    metric_parser.add_argument(
        "--direction",
        choices=["higher_is_better", "lower_is_better"],
        default="higher_is_better",
    )

    # TSV initialisieren
    tsv_init_parser = subparsers.add_parser("tsv-init", help="TSV-Log initialisieren")
    tsv_init_parser.add_argument("tsv_path", help="Pfad zur TSV-Datei")

    # TSV anhängen
    tsv_append_parser = subparsers.add_parser("tsv-append", help="Zeile ans TSV-Log anhängen")
    tsv_append_parser.add_argument("tsv_path", help="Pfad zur TSV-Datei")
    tsv_append_parser.add_argument("--experiment", required=True)
    tsv_append_parser.add_argument("--hypothesis", required=True)
    tsv_append_parser.add_argument("--before", type=float, required=True)
    tsv_append_parser.add_argument("--after", type=float, required=True)
    tsv_append_parser.add_argument("--decision", required=True)
    tsv_append_parser.add_argument("--category", required=True)
    tsv_append_parser.add_argument("--duration", type=float, default=0)

    # Coverage-Matrix initialisieren
    cov_init_parser = subparsers.add_parser("coverage-init", help="Coverage-Matrix initialisieren")
    cov_init_parser.add_argument("matrix_path", help="Pfad zur JSON-Datei")
    cov_init_parser.add_argument(
        "--categories", nargs="+", help="Kategorien (Standard: Skill-Kategorien)"
    )

    # Coverage-Matrix aktualisieren
    cov_update_parser = subparsers.add_parser("coverage-update", help="Coverage-Matrix aktualisieren")
    cov_update_parser.add_argument("matrix_path", help="Pfad zur JSON-Datei")
    cov_update_parser.add_argument("--category", required=True)
    cov_update_parser.add_argument("--experiment", required=True)
    cov_update_parser.add_argument("--decision", required=True)
    cov_update_parser.add_argument("--delta", type=float, required=True)

    # v3 Features: Tiered History, Checkpoint, Grouping
    _register_new_subcommands(subparsers)

    args = parser.parse_args()

    if args.command == "score":
        result = score_from_experiment_dir(args.experiment_dir, args.use_comparator)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Composite Score: {result['composite_score']:.2%}")
            print(f"  Assertion Pass Rate: {result['assertion_pass_rate']:.2%}")
            if result["llm_judge_score"] is not None:
                print(f"  LLM Judge Score:     {result['llm_judge_score']:.2%}")
            print(f"  Efficiency Score:    {result['efficiency_score']:.2%}")
            print(f"  Tokens: {result['details']['total_tokens']}")
            print(f"  Duration: {result['details']['total_duration_seconds']}s")

    elif args.command == "metric":
        output = sys.stdin.read() if args.output == "-" else args.output
        value = extract_metric_value(output)
        if value is None:
            print("Fehler: Keine Zahl im Output gefunden", file=sys.stderr)
            sys.exit(1)
        result = calc_generic_delta(value, args.baseline, args.direction)
        print(json.dumps(result, indent=2))

    elif args.command == "tsv-init":
        init_tsv_log(args.tsv_path)
        print(f"TSV-Log initialisiert: {args.tsv_path}")

    elif args.command == "tsv-append":
        delta = args.after - args.before
        append_tsv_log(
            args.tsv_path,
            args.experiment,
            args.hypothesis,
            args.before,
            args.after,
            delta,
            args.decision,
            args.category,
            args.duration,
        )
        print(f"Zeile angehängt: {args.experiment} ({args.decision})")

    elif args.command == "coverage-init":
        matrix = init_coverage_matrix(args.matrix_path, args.categories)
        print(f"Coverage-Matrix initialisiert mit {len(matrix['categories'])} Kategorien")

    elif args.command == "coverage-update":
        matrix = update_coverage_matrix(
            args.matrix_path, args.category, args.experiment, args.decision, args.delta
        )
        summary = matrix["coverage_summary"]
        print(
            f"Coverage: {summary['coverage_percent']:.0f}% "
            f"({summary['touched_categories']}/{summary['total_categories']})"
        )

    # History komprimieren
    elif args.command == "compact":
        result = compact_history(args.history_path, args.keep)
        info = result.get("_compaction_info", {})
        print(
            f"History komprimiert: {info.get('compacted_count', 0)} komprimiert, "
            f"{info.get('detailed_count', 0)} vollständig"
        )

    # Agent-optimierte History
    elif args.command == "agent-history":
        result = get_history_for_agent(args.history_path, args.keep)
        print(json.dumps(result, indent=2))

    # Checkpoint speichern
    elif args.command == "checkpoint-save":
        coverage = {}
        if args.coverage_path:
            cov_path = Path(args.coverage_path)
            if cov_path.exists():
                coverage = json.loads(cov_path.read_text())
        checkpoint = save_checkpoint(
            args.workspace, args.experiment, args.baseline, coverage, args.next_category
        )
        print(f"Checkpoint gespeichert: {checkpoint['last_completed_experiment']}")

    # Checkpoint laden / Resume-Info
    elif args.command == "checkpoint-info":
        print(get_resume_info(args.workspace))

    # History nach Kategorien gruppieren
    elif args.command == "group-history":
        result = group_history_by_category(args.history_path)
        print(json.dumps(result, indent=2))

    else:
        parser.print_help()


def _register_new_subcommands(subparsers):
    """Registriere die neuen CLI-Subcommands (v3 Features)."""

    # History komprimieren
    compact_parser = subparsers.add_parser(
        "compact", help="History komprimieren (Tiered Compression)"
    )
    compact_parser.add_argument("history_path", help="Pfad zur history.json")
    compact_parser.add_argument(
        "--keep", type=int, default=5, help="Anzahl vollständiger Einträge (Standard: 5)"
    )

    # Agent-optimierte History
    agent_hist_parser = subparsers.add_parser(
        "agent-history", help="Agent-optimierte History-Sicht"
    )
    agent_hist_parser.add_argument("history_path", help="Pfad zur history.json")
    agent_hist_parser.add_argument("--keep", type=int, default=5)

    # Checkpoint speichern
    cp_save_parser = subparsers.add_parser(
        "checkpoint-save", help="Resume-Point speichern"
    )
    cp_save_parser.add_argument("workspace", help="Workspace-Pfad")
    cp_save_parser.add_argument("--experiment", required=True)
    cp_save_parser.add_argument("--baseline", type=float, required=True)
    cp_save_parser.add_argument("--coverage-path", dest="coverage_path")
    cp_save_parser.add_argument("--next-category", dest="next_category")

    # Checkpoint Info
    cp_info_parser = subparsers.add_parser(
        "checkpoint-info", help="Resume-Info anzeigen"
    )
    cp_info_parser.add_argument("workspace", help="Workspace-Pfad")

    # History gruppieren
    group_parser = subparsers.add_parser(
        "group-history", help="History nach Kategorien gruppieren"
    )
    group_parser.add_argument("history_path", help="Pfad zur history.json")


if __name__ == "__main__":
    main()
