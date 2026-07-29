#!/usr/bin/env python3
"""Scoring, Entscheidung, Snapshots und Logging für Skill Forge.

Der Gate-Score misst ausschliesslich Aufgabenqualität:
- ohne Comparator: assertion_pass_rate * 1.00
- mit Comparator:  assertion_pass_rate * 0.65 + llm_judge_score * 0.35

Der Efficiency-Score wird weiterhin berechnet, fliesst aber NICHT mehr in den
Gate-Score ein. Zwei konstruierte Läufe mit identischen Assertions (20k Tokens
gegen 45k, 60s gegen 120s) liegen unter der alten Gewichtung 0.045 auseinander,
also stärker als die Keep-Schwelle von 0.02. Die Zahl ist aus der v2-Formel
gerechnet, nicht empirisch gemessen; wie stark der Score zwischen zwei
identischen Läufen tatsächlich streut, ist offen und hängt an der
Wiederholungsmessung. Er erscheint jetzt nur noch unter `details` und
im Morning Report.

Unterstützt zwei Modi:
- Skill-Modus: Gate-Score aus Assertions (+ optional Judge)
- Generic-Modus: Direkte Metrik-Extraktion aus Shell-Command-Output

Die Keep/Revert-Entscheidung fällt ausschliesslich in `decide()`. Das ist die
einzige Stelle im Projekt, an der eine Score-Differenz in eine Entscheidung
übersetzt wird.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import glob as globlib
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

__version__ = "3.0.0"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Skill-Modus Scoring ──────────────────────────────────────────────────


def calc_assertion_pass_rate(grading_results: list[dict]) -> float:
    """Berechne die Gesamt-Pass-Rate über alle Grading-Ergebnisse.

    grading.json wird von einem LLM geschrieben. Ohne Bereichsprüfung ergibt
    ein ``{"passed": 7, "total": 5}`` eine Pass-Rate von 1.4 und damit ein
    garantiertes KEEP, während `decide` nebenan NaN und Inf hart ablehnt.
    """
    total_passed = 0
    total_assertions = 0
    for grading in grading_results:
        summary = grading.get("summary", {})
        passed = summary.get("passed", 0)
        total = summary.get("total", 0)
        if passed < 0 or total < 0 or passed > total:
            raise NoGradingDataError(
                "unplausibles Grading: passed=%r, total=%r. Erwartet wird "
                "0 <= passed <= total." % (passed, total)
            )
        total_passed += passed
        total_assertions += total
    if total_assertions == 0:
        return 0.0
    return total_passed / total_assertions


def calc_efficiency_score(
    tokens_used: int,
    duration_seconds: float,
    max_tokens: int = 100000,
    max_duration: float = 300.0,
    samples: int = 1,
) -> float | None:
    """Berechne den Effizienz-Score (0-1, höher = effizienter).

    Gibt ``None`` zurück, wenn keine Messdaten vorliegen (``samples == 0``).
    "Nichts gemessen" ist nicht dasselbe wie "perfekt effizient"; die alte
    Fassung lieferte für ein leeres Experiment-Verzeichnis 1.0 und belohnte
    damit genau die Läufe, die nichts protokolliert haben.

    Normalisiert wird pro Lauf, nicht über die Summe aller Läufe: ``samples``
    ist die Anzahl der gefundenen timing.json-Dateien.
    """
    if samples <= 0:
        return None
    per_run_tokens = tokens_used / samples
    per_run_duration = duration_seconds / samples
    token_score = max(0.0, 1.0 - (per_run_tokens / max_tokens))
    time_score = max(0.0, 1.0 - (per_run_duration / max_duration))
    return (token_score + time_score) / 2.0


# Gate-Gewichtungen. Efficiency ist bewusst nicht enthalten.
GATE_WEIGHTS_PLAIN = {"assertions": 1.0, "judge": 0.0}
GATE_WEIGHTS_COMPARATOR = {"assertions": 0.65, "judge": 0.35}


def calc_composite_score(
    assertion_pass_rate: float,
    llm_judge_score: float | None = None,
    use_comparator: bool = False,
    weights: dict | None = None,
) -> float:
    """Berechne den Gate-Score.

    Gewichtung:
    - Ohne Comparator: assertions=1.00
    - Mit Comparator:  assertions=0.65, judge=0.35

    Die Comparator-Gewichte sind aus den alten 0.50/0.30 renormalisiert,
    nachdem der Efficiency-Anteil entfallen ist. Efficiency wird weiterhin
    berechnet und berichtet, entscheidet aber nichts.
    """
    if weights is None:
        weights = (
            GATE_WEIGHTS_COMPARATOR
            if (use_comparator and llm_judge_score is not None)
            else GATE_WEIGHTS_PLAIN
        )
    judge = llm_judge_score if llm_judge_score is not None else 0.0
    return assertion_pass_rate * weights["assertions"] + judge * weights["judge"]


# ─── Generic-Modus Scoring ────────────────────────────────────────────────


def extract_metric_value(output: str) -> float | None:
    """Extrahiere einen einzelnen Zahlenwert aus Command-Output.

    Sucht nach der letzten Zahl im Output (Float oder Int).
    """
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
        "improved_raw": improved,
        "direction": direction,
        "note": (
            "improved_raw ist nur das Vorzeichen, keine Entscheidung. "
            "Keep/Revert faellt in decide(), im Generic-Modus mit --relative."
        ),
    }


# ─── Eval-Splits ──────────────────────────────────────────────────────────


SPLIT_NAMES = ("train", "val", "test")
MIN_EVALS_FOR_TEST = 12
MIN_EVALS = 6


def assign_split(eval_id: str, seed: int = 42,
                 val_fraction: float = 0.25,
                 test_fraction: float = 0.25) -> str:
    """Ordne ein Eval über einen stabilen Hash einem Split zu.

    Nach SkillOpt-Vorbild (``skillopt_sleep/mine.py``): der Bucket ergibt sich
    aus ``sha256(seed:id) % 100`` gegen kumulative Grenzen. Eine Liste wäre
    fragil, weil das Löschen eines Evals alle nachfolgenden verschieben würde.

    Die ID muss ein sprechender, unveränderlicher Slug sein. Ein Hash über
    eine Positionsnummer ist wertlos: beim Löschen eines Evals wechseln alle
    späteren ihren Split, und jedes Delta danach vergleicht Äpfel mit Birnen.
    Ein Slug umzubenennen ist deshalb ein Re-Baseline-Ereignis.
    """
    bucket = int(
        hashlib.sha256(("%s:%s" % (seed, eval_id)).encode()).hexdigest(), 16
    ) % 100
    val_cut = int(round(val_fraction * 100))
    test_cut = val_cut + int(round(test_fraction * 100))
    if bucket < val_cut:
        return "val"
    if bucket < test_cut:
        return "test"
    return "train"


def assign_splits(evals: list, seed: int = 42,
                  val_fraction: float = 0.25,
                  test_fraction: float = 0.25,
                  with_test: bool | None = None) -> dict:
    """Weise allen Evals ihren Split zu und sichere die Mindestbelegung.

    ``with_test=None`` entscheidet anhand der Anzahl: unter
    ``MIN_EVALS_FOR_TEST`` gibt es keinen test-Split. Ein Zwei-Item-Holdout als
    unabhängigen Test auszuweisen ist irreführender als gar keiner.

    Bleibt val leer, wird deterministisch ein Eval dorthin gezwungen. Ohne
    diesen Fallback gated der Loop irgendwann gegen eine leere Menge und meldet
    triumphal 1.0. Der Fallback zieht nie aus test.
    """
    ids = [e.get("id") for e in evals]
    missing = [i for i, v in enumerate(ids) if not v]
    if missing:
        raise ValueError(
            "Evals ohne id an Position %s. Der Split hängt an einem stabilen "
            "Slug, nicht an der Reihenfolge." % missing
        )
    if len(set(ids)) != len(ids):
        raise ValueError("doppelte Eval-IDs: der Split wäre nicht eindeutig")

    if with_test is None:
        with_test = len(evals) >= MIN_EVALS_FOR_TEST

    effective_test = test_fraction if with_test else 0.0
    for entry in evals:
        entry["split"] = assign_split(
            entry["id"], seed, val_fraction, effective_test
        )

    counts = {name: sum(1 for e in evals if e["split"] == name)
              for name in SPLIT_NAMES}
    forced = []
    if counts["val"] == 0 and evals:
        # Deterministisch und ausschliesslich aus train. Aus test zu ziehen
        # würde das unabhängige Holdout verkleinern, also genau die Grösse
        # beschädigen, die am Ende die einzige nicht mitoptimierte Zahl liefert.
        candidates = [e for e in evals if e["split"] == "train"]
        if not candidates:
            raise ValueError(
                "val ist leer und train ebenfalls. Mit dieser Aufteilung lässt "
                "sich weder eine Hypothese bilden noch entscheiden."
            )
        chosen = min(candidates, key=lambda e: e["id"])
        chosen["split"] = "val"
        forced.append(chosen["id"])
        counts = {name: sum(1 for e in evals if e["split"] == name)
                  for name in SPLIT_NAMES}

    warnings = []
    if with_test and counts["test"] == 0:
        # Die Vorprüfung schaut nur auf die Gesamtzahl. Bei genau 12 Evals
        # liefert der Hash je nach Seed einen leeren test-Split, und der wäre
        # als unabhängiges Holdout ausgewiesen worden, ohne dass irgendwo etwas
        # steht. Für val gibt es einen Fallback, für test bewusst nicht: ein
        # erzwungenes Holdout aus train wäre keines.
        with_test = False
        warnings.append(
            "test-Split blieb leer und wurde abgeschaltet. Der Report muss "
            "ausweisen, dass es kein unabhängiges Holdout gibt."
        )
    if with_test and counts["test"] < 3:
        warnings.append(
            "test-Split hat nur %d Evals. Eine Endzahl auf dieser Basis trägt "
            "wenig." % counts["test"]
        )
    if counts["val"] < 3:
        warnings.append(
            "val-Split hat nur %d Evals. Die Auflösungsgrenze wird entsprechend "
            "grob." % counts["val"]
        )
    if len(evals) < MIN_EVALS:
        warnings.append(
            "nur %d Evals. Unter %d ist keine belastbare Messung möglich."
            % (len(evals), MIN_EVALS)
        )
    if not with_test:
        warnings.append(
            "kein test-Split: unter %d Evals gibt es kein unabhängiges "
            "Holdout. Der Report muss das ausweisen." % MIN_EVALS_FOR_TEST
        )
    if counts["train"] == 0:
        warnings.append("train ist leer, es gibt kein Signal für Hypothesen")

    return {
        "counts": counts,
        "seed": seed,
        "with_test": with_test,
        "forced_to_val": forced,
        "warnings": warnings,
        "total": len(evals),
    }


def load_evals(path: str, split: str | None = None) -> list:
    """Lies evals.json und filtere optional auf einen Split.

    Schema:
    ``{"version": 1, "evals": [{"id": str, "prompt": str,
    "assertions": [{"id": str, "check": str, "weight": float}],
    "split": "train|val|test"}]}``
    """
    data = json.loads(Path(path).read_text())
    evals = data["evals"] if isinstance(data, dict) else data
    if split is None:
        return evals
    if split not in SPLIT_NAMES:
        raise ValueError("unbekannter Split %r; erwartet eine aus %r"
                         % (split, SPLIT_NAMES))
    return [e for e in evals if e.get("split") == split]


# ─── Auflösungsgrenze ─────────────────────────────────────────────────────


def min_detectable_delta(total_assertions: int, flips: int = 2) -> float:
    """Die kleinste Score-Differenz, die überhaupt etwas bedeuten kann.

    Nachdem Efficiency aus dem Gate geflogen ist, ist der Score exakt die
    Assertion-Pass-Rate. Sie ist damit grob quantisiert: ein einzelner
    Assertion-Flip bewegt ``1 / N``. Bei 9 Assertions sind das 0.111, bei 31
    noch 0.032. Eine feste Keep-Schwelle von 0.02 liegt darunter und kann
    deshalb nie greifen, jeder einzelne Flip löst KEEP aus.

    ``flips`` ist die Anzahl der Assertions, die kippen müssen, damit die
    Änderung als gemessen gilt. Zwei ist die vernünftige Untergrenze: ein
    einzelner Flip kann ein Ausrutscher des Subagenten sein.

    SkillOpt braucht das nicht, weil dort der Selection-Split gross genug ist,
    dass ein Item-Flip im Promillebereich bleibt. Der Blogpost zieht dieselbe
    Konsequenz redaktionell: "treat differences below 1.5 percentage points as
    noise".
    """
    if total_assertions <= 0:
        return 0.0
    return flips / total_assertions


# ─── Entscheidung ─────────────────────────────────────────────────────────


DECISIONS = ("KEEP", "REVERT", "NEUTRAL", "SKIP", "NO_OP", "INVALID")

IMPROVEMENT_THRESHOLD = 0.02
REGRESSION_THRESHOLD = 0.05
NEAR_MISS_BAND = 0.02


def decide(
    candidate: float,
    baseline: float,
    *,
    improvement: float = IMPROVEMENT_THRESHOLD,
    regression: float = REGRESSION_THRESHOLD,
    near_miss_band: float = NEAR_MISS_BAND,
    noise_floor: float = 0.0,
    resolution: float = 0.0,
    direction: str = "higher_is_better",
    relative: bool = False,
) -> dict:
    """Die einzige Stelle, an der aus zwei Zahlen eine Entscheidung wird.

    Drei Ausgänge, kein vierter:

    - ``KEEP``    delta >= max(improvement, noise_floor, resolution)
    - ``REVERT``  delta <= -regression
    - ``NEUTRAL`` alles dazwischen

    Die Grenzen sind inklusiv und mit einem Epsilon von 1e-9 gegen
    Float-Rundung abgesichert. Ein Score, der in Schritten von 1/N springt,
    trifft die Schwelle regelmässig exakt; ob daraus KEEP oder NEUTRAL wird,
    darf nicht von der letzten Binärstelle abhängen.

    ``near_miss`` ist ein Flag auf NEUTRAL, kein eigener Ausgang. Es markiert
    das Band knapp unterhalb der Keep-Schwelle, also die Hypothesen, für die
    eine Variation sich lohnt.

    Gleichstand ist bewusst NEUTRAL und damit Revert. Ein Loop, der bei
    Null-Runden die neue Version behält, driftet über zehn Experimente ohne
    jede Messung vom Ausgangspunkt weg.

    ``relative=True`` normalisiert das Delta auf die Baseline. Das ist der
    sinnvolle Modus im Generic-Modus, wo die Metrik in KB, Sekunden oder
    Fehlerzahlen misst und absolute Schwellen von 0.02 nichts bedeuten.
    """
    for name, value in (("candidate", candidate), ("baseline", baseline)):
        if math.isnan(value) or math.isinf(value):
            raise ValueError(
                "%s ist %r. Ein kaputtes Scoring darf nicht als 'kein "
                "Unterschied gemessen' durchgehen: mit NaN sind alle "
                "Vergleiche False, die Kaskade fiele still auf NEUTRAL."
                % (name, value)
            )

    delta = candidate - baseline
    if direction == "lower_is_better":
        delta = -delta
    elif direction != "higher_is_better":
        raise ValueError(
            "unbekannte direction %r; erwartet 'higher_is_better' "
            "oder 'lower_is_better'" % (direction,)
        )

    relative_fallback = False
    if relative:
        if abs(baseline) < 1e-9:
            # Baseline null, etwa "0 Lint-Fehler". Ein relatives Delta ist
            # hier nicht definiert; die alte Division durch 1e-10 erzeugte
            # Deltas in der Grössenordnung 1e10 und damit garantiert KEEP.
            relative_fallback = True
        else:
            delta = delta / abs(baseline)

    threshold = max(improvement, noise_floor, resolution)
    # Der Grenzfall gehört definiert, nicht dem Float überlassen. resolution ist
    # 2/N und liegt damit exakt auf dem Quantisierungsraster des Scores: genau
    # zwei gekippte Assertions ergeben delta == threshold, und ob daraus KEEP
    # oder NEUTRAL wird, entschied vorher die letzte Binärstelle. Über N = 5 bis
    # 60 kippte das in 33 von 56 Fällen auf NEUTRAL, obwohl der Docstring zwei
    # Flips ausdrücklich als gemessene Änderung führt.
    eps = 1e-9
    binding = "improvement_threshold"
    if noise_floor >= threshold and noise_floor > improvement:
        binding = "noise_floor"
    if resolution >= threshold and resolution > improvement and resolution >= noise_floor:
        binding = "resolution"

    if delta >= threshold - eps:
        decision = "KEEP"
    elif delta <= -regression + eps:
        decision = "REVERT"
    else:
        decision = "NEUTRAL"

    near_miss = (
        decision == "NEUTRAL" and delta > threshold - near_miss_band - eps
    )

    formula = (
        "delta = %.4f - %.4f = %+.4f; threshold = max(improvement %.4f, "
        "noise_floor %.4f, resolution %.4f) = %.4f (%s); "
        "revert_if delta < %+.4f -> %s%s"
        % (
            candidate,
            baseline,
            delta,
            improvement,
            noise_floor,
            resolution,
            threshold,
            binding,
            -regression,
            decision,
            " (near_miss)" if near_miss else "",
        )
    )
    if relative_fallback:
        formula += "; relative Rechnung übersprungen, Baseline ist 0"

    return {
        "decision": decision,
        "near_miss": near_miss,
        "delta": round(delta, 6),
        "threshold": round(threshold, 6),
        "improvement_threshold": improvement,
        "regression_threshold": regression,
        "noise_floor": noise_floor,
        "resolution": resolution,
        "binding_threshold": binding,
        "direction": direction,
        "relative": relative,
        "relative_fallback": relative_fallback,
        "formula": formula,
    }


def load_thresholds(config_path: str | None) -> dict:
    """Lies die Schwellenwerte aus einer config.json.

    Argparse-Defaults sind nur Fallback. Steht eine config.json zur Verfügung,
    gewinnt sie, sonst driften Script-Default und konfigurierter Wert
    auseinander.
    """
    defaults = {
        "improvement": IMPROVEMENT_THRESHOLD,
        "regression": REGRESSION_THRESHOLD,
        "near_miss_band": NEAR_MISS_BAND,
        "noise_floor": 0.0,
        "resolution": 0.0,
    }
    if not config_path:
        return defaults
    path = Path(config_path)
    if not path.exists():
        return defaults
    cfg = json.loads(path.read_text())
    mapping = {
        "improvement": "improvement_threshold",
        "regression": "regression_threshold",
        "near_miss_band": "near_miss_band",
        "noise_floor": "noise_floor",
        "resolution": "resolution",
    }
    for key, cfg_key in mapping.items():
        if cfg.get(cfg_key) is not None:
            defaults[key] = float(cfg[cfg_key])
    return defaults


def is_plateau(decisions: list, window: int = 3) -> bool:
    """Plateau = ``window`` aufeinanderfolgende Nicht-KEEP-Entscheidungen.

    Die alte Formulierung ("3 aufeinanderfolgende NEUTRAL/REVERT") liess
    NEAR_MISS ausser Acht, und NEAR_MISS war durch die kaputte Kaskade der
    häufigste Ausgang. Ein Lauf im mittleren Band brach deshalb nie ab.
    """
    if len(decisions) < window:
        return False
    return all(d != "KEEP" for d in decisions[-window:])


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

    timestamp = _utc_now()
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
        matrix["categories"][cat] = _new_category()

    path = Path(matrix_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(matrix, f, indent=2)

    return matrix


def _new_category() -> dict:
    return {
        "experiments_total": 0,
        "experiments_kept": 0,
        "experiments_reverted": 0,
        "experiments_neutral": 0,
        "experiments_invalid": 0,
        "last_experiment": None,
        "best_delta": None,
        "saturated": False,
    }


def as_float(value, default: float = 0.0) -> float:
    """Robuste Zahl aus einem Feld, das auch ein String wie '+0.06' sein kann.

Seit v3 ist `delta` in history.json eine Zahl. Ältere Workspaces und die
    Coverage-Matrix (`best_delta`) führen es als formatierten String wie
    `"+0.06"`. Ohne diesen Helfer vergleicht Python Strings lexikografisch,
    und `"+0.09" > "+0.10"` ist wahr.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace("+", ""))
    except (TypeError, ValueError):
        return default


def update_coverage_matrix(
    matrix_path: str,
    category: str,
    experiment_id: str,
    decision: str,
    delta: float,
    saturation_threshold: int = 3,
    saturation_min_delta: float = 0.01,
    direction: str = "higher_is_better",
) -> dict:
    """Aktualisiere die Coverage-Matrix nach einem Experiment.

    Args:
        matrix_path: Pfad zur coverage-matrix.json
        category: Kategorie des Experiments
        experiment_id: ID des Experiments
        decision: KEEP, REVERT, NEUTRAL, SKIP, NO_OP oder INVALID
        delta: Score-Delta des Experiments (roh, in Metrik-Einheiten)
        saturation_threshold: Min. Experimente für Sättigung
        saturation_min_delta: Min. Verbesserung um nicht saturiert zu sein
        direction: bestimmt, welches Vorzeichen eine Verbesserung ist

    Zwei reparierte Fehler gegenüber v2:

    1. Sättigung rastete ein. ``saturated`` wurde nur auf True gesetzt und nie
       zurückgenommen; eine Kategorie erholte sich nach einem späteren Treffer
       nie mehr. Jetzt wird der Wert bei jedem Update neu berechnet.
    2. ``best_delta`` war richtungsblind. Bei ``lower_is_better`` gewann die
       schlimmste Regression als Bestwert und lenkte den Hypothesis-Agent
       systematisch in die falsche Kategorie.

    INVALID, SKIP und NO_OP zählen nicht in die Sättigung. Sonst gilt eine
    Kategorie als abgegrast, obwohl sie nie wirklich gemessen wurde.
    """
    path = Path(matrix_path)
    with open(path, "r") as f:
        matrix = json.load(f)

    # Kategorie anlegen falls neu (Generic-Modus)
    if category not in matrix["categories"]:
        matrix["categories"][category] = _new_category()
        matrix["coverage_summary"]["total_categories"] += 1

    cat = matrix["categories"][category]
    for field, default in _new_category().items():
        cat.setdefault(field, default)

    cat["experiments_total"] += 1
    cat["last_experiment"] = experiment_id

    if decision == "KEEP":
        cat["experiments_kept"] += 1
    elif decision == "REVERT":
        cat["experiments_reverted"] += 1
    elif decision == "NEUTRAL":
        cat["experiments_neutral"] += 1
    elif decision in ("INVALID", "SKIP", "NO_OP"):
        cat["experiments_invalid"] += 1

    counted = decision in ("KEEP", "REVERT", "NEUTRAL")

    # Best Delta aktualisieren, richtungsbewusst und nur für gemessene Läufe
    oriented = delta if direction == "higher_is_better" else -delta
    if counted:
        current_best = cat["best_delta"]
        if current_best is None or oriented > as_float(current_best):
            cat["best_delta"] = "%+.4f" % oriented

    # Sättigungsprüfung, bei jedem Update neu berechnet
    measured = (
        cat["experiments_total"]
        - cat["experiments_invalid"]
    )
    cat["saturated"] = (
        measured >= saturation_threshold
        and cat["best_delta"] is not None
        and as_float(cat["best_delta"]) < saturation_min_delta
    )

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


SIDES = ("with_mutation", "baseline")


class NoGradingDataError(RuntimeError):
    """Kein einziges Grading gefunden. Ein Score von 0.0 wäre hier eine Lüge."""


class NoJudgeDataError(RuntimeError):
    """comparison.json fehlt oder deckt nicht beide Seiten ab."""


def _side_of(path: Path, exp_path: Path) -> str | None:
    """Die Seite, zu der eine Datei gehört: das TIEFSTE Seitenverzeichnis.

    Eine frühere Fassung prüfte nur, ob der Seitenname irgendwo im Pfad
    vorkommt. Ein Eval-Verzeichnis namens ``baseline`` liess damit
    ``runs/baseline/with_mutation/grading.json`` für beide Seiten matchen und
    mischte genau das wieder, was der Filter trennen soll.
    """
    marker = None
    for part in path.relative_to(exp_path).parts:
        if part in SIDES:
            marker = part
    return marker


def _side_matches(path: Path, exp_path: Path, side: str | None) -> bool:
    if side is None:
        return True
    return _side_of(path, exp_path) == side


def load_use_comparator(config_path: str | None, cli_flag: bool) -> bool:
    """``use_comparator`` aus der config.json, CLI-Flag gewinnt.

    Ohne das hier liest der dokumentierte Aufrufweg
    ``score ... --config config.json`` bei ``use_comparator: true`` still den
    reinen Assertion-Score, obwohl comparison.json danebenliegt.
    """
    if cli_flag:
        return True
    if not config_path:
        return False
    path = Path(config_path)
    if not path.exists():
        return False
    return bool(json.loads(path.read_text()).get("use_comparator", False))


def load_gate_weights(config_path: str | None) -> dict | None:
    """Lies ``gate_weights`` aus einer config.json, falls vorhanden.

    Gibt ``None`` zurück, wenn nichts konfiguriert ist; dann gelten die
    Defaults aus GATE_WEIGHTS_PLAIN beziehungsweise GATE_WEIGHTS_COMPARATOR.
    Die Gewichte müssen sich zu 1.0 summieren, sonst ist der Score nicht mehr
    mit früheren Läufen vergleichbar.
    """
    if not config_path:
        return None
    path = Path(config_path)
    if not path.exists():
        return None
    raw = json.loads(path.read_text()).get("gate_weights")
    if not raw:
        return None
    weights = {
        "assertions": float(raw.get("assertions", 0.0)),
        "judge": float(raw.get("judge", 0.0)),
    }
    total = weights["assertions"] + weights["judge"]
    if abs(total - 1.0) > 1e-6:
        raise ValueError(
            "gate_weights müssen sich zu 1.0 summieren, gefunden %.4f" % total
        )
    if "efficiency" in raw and float(raw["efficiency"]) != 0.0:
        raise ValueError(
            "efficiency ist kein Gate-Gewicht mehr. Sie schwankte zwischen "
            "zwei Läufen mit identischen Assertions um 0.045, bei einer "
            "Keep-Schwelle von 0.02. Der Wert steht im Report unter "
            "details.efficiency_score."
        )
    return weights


def score_from_experiment_dir(
    experiment_dir: str,
    use_comparator: bool = False,
    side: str | None = None,
    weights: dict | None = None,
) -> dict:
    """Berechne den Gate-Score aus einem Experiment-Verzeichnis (Skill-Modus).

    Erwartet folgende Dateien im Verzeichnis:
    - grading_results.json: Liste von Grading-Ergebnissen, oder
    - runs/eval-N/<side>/grading.json je Lauf
    - runs/eval-N/<side>/timing.json (optional)
    - comparison.json: LLM-Judge-Ergebnis (optional, nur mit use_comparator)

    ``side`` muss ``"with_mutation"`` oder ``"baseline"`` sein. Ohne diesen
    Filter sammelte die alte Fassung per rglob beide Seiten ein und mittelte
    Kandidat und Baseline in einen einzigen Wert. Die gemessene Grösse war
    damit nicht die, über die entschieden wurde.

    Wirft ``NoGradingDataError``, wenn nichts gefunden wurde. Die alte Fassung
    lieferte für ein leeres Verzeichnis stillschweigend
    ``composite_score: 0.2``.
    """
    if side is not None and side not in SIDES:
        raise ValueError("unbekannte side %r; erwartet eine aus %r" % (side, SIDES))

    exp_path = Path(experiment_dir)

    # Grading-Ergebnisse laden
    grading_file = exp_path / "grading_results.json"
    if grading_file.exists() and side is None:
        grading_results = json.loads(grading_file.read_text())
    else:
        # Suche nach einzelnen grading.json Dateien in Unterordnern
        grading_results = []
        for gf in sorted(exp_path.rglob("grading.json")):
            if _side_matches(gf, exp_path, side):
                grading_results.append(json.loads(gf.read_text()))

    if not grading_results:
        raise NoGradingDataError(
            "keine Grading-Daten unter %s%s"
            % (experiment_dir, "" if side is None else " für side=%s" % side)
        )

    assertion_pass_rate = calc_assertion_pass_rate(grading_results)
    total_assertions = sum(
        g.get("summary", {}).get("total", 0) for g in grading_results
    )

    # Timing-Daten laden
    total_tokens = 0
    total_duration = 0.0
    timing_files = 0
    for tf in sorted(exp_path.rglob("timing.json")):
        if not _side_matches(tf, exp_path, side):
            continue
        timing = json.loads(tf.read_text())
        total_tokens += timing.get("total_tokens", 0)
        total_duration += timing.get("total_duration_seconds", 0)
        timing_files += 1

    efficiency = calc_efficiency_score(total_tokens, total_duration, samples=timing_files)

    # Optional: LLM Judge Score, seitengetrennt wie die Assertions
    llm_judge_score = None
    if use_comparator:
        comparison_file = exp_path / "comparison.json"
        if not comparison_file.exists():
            raise NoJudgeDataError(
                "use_comparator ist aktiv, aber %s fehlt. Ohne die Datei "
                "würde dieser Lauf gegen eine andere Formel gemessen als der "
                "Vorlauf, ohne dass es auffällt." % comparison_file
            )
        if True:
            comparison = json.loads(comparison_file.read_text())
            rubric = comparison.get("rubric", {})
            if side is not None:
                # Genau der Eintrag dieser Seite. Die alte Fassung nahm
                # max() über alle Einträge und gab damit beiden Seiten
                # denselben Judge-Wert. Der Judge-Anteil hob sich im Delta
                # weg, der Comparator war für die Entscheidung wirkungslos,
                # obwohl er 35 Prozent Gewicht trägt.
                missing = [
                    s for s in SIDES
                    if not (
                        isinstance(rubric.get(s), dict)
                        and "overall_score" in rubric[s]
                    )
                ]
                if missing:
                    # Eine einseitige Rubrik würde die eine Seite mit
                    # 0.65/0.35 und die andere mit 1.00/0.00 gewichten.
                    # decide bekäme dann zwei Zahlen aus zwei Formeln.
                    raise NoJudgeDataError(
                        "comparison.json enthält keinen rubric-Eintrag für %s. "
                        "Mit use_comparator müssen beide Seiten bewertet sein, "
                        "sonst werden Kandidat und Baseline unterschiedlich "
                        "gewichtet und sind nicht mehr vergleichbar."
                        % ", ".join(missing)
                    )
                raw_score = rubric[side]["overall_score"]
                if not 0 <= raw_score <= 10:
                    raise NoJudgeDataError(
                        "overall_score %r liegt ausserhalb der Skala 1 bis 10. "
                        "Ein um den Faktor 10 verrutschter Wert erzeugt ein "
                        "garantiertes KEEP." % raw_score
                    )
                llm_judge_score = raw_score / 10.0
            else:
                scores = [
                    e["overall_score"] / 10.0
                    for e in rubric.values()
                    if isinstance(e, dict) and "overall_score" in e
                ]
                if scores:
                    llm_judge_score = max(scores)

    effective_weights = weights or (
        GATE_WEIGHTS_COMPARATOR
        if (use_comparator and llm_judge_score is not None)
        else GATE_WEIGHTS_PLAIN
    )
    if effective_weights["judge"] > 0 and llm_judge_score is None:
        # Sonst wird der fehlende Judge-Anteil als 0.0 eingerechnet statt als
        # "keine Daten", und der Score sackt still um das Judge-Gewicht ab.
        raise NoJudgeDataError(
            "gate_weights geben dem Judge %.2f Gewicht, aber es liegt kein "
            "Judge-Wert vor. Entweder use_comparator einschalten und "
            "comparison.json schreiben, oder gate_weights weglassen."
            % effective_weights["judge"]
        )
    composite = calc_composite_score(
        assertion_pass_rate=assertion_pass_rate,
        llm_judge_score=llm_judge_score,
        use_comparator=use_comparator,
        weights=effective_weights,
    )

    return {
        "composite_score": round(composite, 4),
        "assertion_pass_rate": round(assertion_pass_rate, 4),
        "llm_judge_score": round(llm_judge_score, 4) if llm_judge_score is not None else None,
        "gate_weights": effective_weights,
        "side": side,
        "total_assertions": total_assertions,
        # Ungerundet. Gerundet auf 6 Stellen lag der Wert je nach N mal knapp
        # über und mal knapp unter dem echten 2/N, und dieselbe Messung fiel
        # unterschiedlich aus, je nachdem ob der exakte oder der ausgegebene
        # Wert eingesetzt wurde.
        "resolution": min_detectable_delta(total_assertions),
        "details": {
            # Efficiency ist Report-Information, kein Bestandteil des Gates.
            "efficiency_score": round(efficiency, 4) if efficiency is not None else None,
            "total_tokens": total_tokens,
            "total_duration_seconds": round(total_duration, 1),
            "timing_files_found": timing_files,
            "grading_files_found": len(grading_results),
        },
    }


# ─── Snapshot / Revert ────────────────────────────────────────────────────


_GLOB_MAGIC = set("*?[")


class ScopeMismatchError(RuntimeError):
    """Das Basisverzeichnis des Snapshots passt nicht mehr zum Ziel.

    Ein Revert, der auf einer anderen Basis arbeitet als der Snapshot, löscht
    fremde Dateien und lässt die Mutation stehen. Er bricht deshalb ab, statt
    zu raten.
    """


class SnapshotConflictError(RuntimeError):
    """Dieselbe Snapshot-Version soll mit anderem Inhalt überschrieben werden."""


def is_glob(target: str) -> bool:
    """Ist das ein Glob-Pattern oder ein wörtlicher Pfad?

    Ein existierender Pfad gewinnt immer, auch wenn sein Name Glob-Zeichen
    enthält. Sonst behandelt der Snapshot Next.js-, Remix- und
    SvelteKit-Routen wie ``app/[slug]`` als Muster, findet nichts, schreibt
    einen leeren Snapshot mit Exit 0, und der spätere Revert rollt nichts
    zurück, ohne das zu melden.
    """
    if not (_GLOB_MAGIC & set(target)):
        return False
    return not Path(target).exists()


def absolute_target(target: str) -> str:
    """Absoluter Zielpfad, auch für Glob-Patterns.

    Ein relativer Zielstring im Manifest wird beim Resume gegen ein anderes
    Arbeitsverzeichnis aufgelöst. Der Löschdurchgang findet dann nichts, fällt
    still aus, und die von der Mutation angelegten Dateien bleiben liegen.

    Die letzte Pfadkomponente wird NICHT über ``resolve()`` aufgelöst. Sonst
    zeigt ``target`` bei einem symlinkten SKILL.md auf das Linkziel, während
    ``resolve_scope`` die Basis am Linkort bildet, und jeder Revert bricht mit
    ScopeMismatchError ab.
    """
    if is_glob(target):
        base = _glob_base(target)
        if str(base) == ".":
            return str(Path.cwd() / target)
        tail = Path(target).relative_to(base)
        return str(base.resolve() / tail)
    path = Path(target)
    if path.is_dir():
        return str(path.resolve())
    return str(path.parent.resolve() / path.name)


def _scope_hash(base: Path, files) -> str:
    """Fingerabdruck über Pfade und Inhalte des Scopes."""
    digest = hashlib.sha256()
    for rel in files:
        digest.update(str(rel).encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256((base / rel).read_bytes()).digest())
    return digest.hexdigest()


def _glob_base(pattern: str) -> Path:
    """Längstes magic-freies Präfix eines Glob-Patterns als Basisverzeichnis.

    Bewusst OHNE Existenzprüfung. Eine frühere Fassung fiel auf
    ``base.parent`` zurück, wenn das Präfix-Verzeichnis noch nicht existierte.
    Damit wurde die Basis eine Ebene zu breit, Snapshot und Revert rechneten
    mit unterschiedlichen Basen, und ``revert`` löschte Dateien ausserhalb des
    Scopes: bei ``src/api/**/*.ts`` mit noch fehlendem ``src/api`` traf das
    Löschen ``src/helper.ts``, während die eigentliche Mutation stehen blieb.
    """
    base_parts = []
    for part in Path(pattern).parts:
        if _GLOB_MAGIC & set(part):
            break
        base_parts.append(part)
    if not base_parts:
        return Path(".")
    return Path(*base_parts)


def resolve_scope(target: str):
    """Löse ein Ziel zu (absolute Basis, sortierte relative Dateipfade) auf.

    Akzeptiert eine einzelne Datei, ein Verzeichnis oder ein Glob-Pattern.
    Die Auflösung passiert in Python, nicht in einer Shell-Schleife: die alte
    Fassung in agents/mutator.md übergab ein Glob als find-Pfad und splittete
    ungequotet auf Leerzeichen.

    Die Basis wird absolut aufgelöst. Ein relativer Pfad im Manifest würde
    beim Resume gegen ein anderes Arbeitsverzeichnis geschrieben, und der
    Revert legte dann einen Schattenbaum an, statt zurückzurollen. Ein
    Scheduled Task startet grundsätzlich mit unbekanntem cwd.

    Symlinks werden übersprungen und getrennt zurückgemeldet. ``shutil.copy2``
    folgt ihnen sonst und schreibt beim Revert an Dateien ausserhalb des
    Scopes; ausserdem folgt ``glob`` symlinkten Verzeichnissen, ``rglob`` aber
    nicht, die beiden Zweige verhielten sich also unterschiedlich.
    """
    path = Path(target)
    if is_glob(target):
        base = _glob_base(target).resolve()
        candidates = [Path(p) for p in globlib.glob(target, recursive=True)]
    elif path.is_dir():
        base = path.resolve()
        candidates = sorted(path.rglob("*"))
    elif path.is_file():
        base = path.parent.resolve()
        candidates = [path]
    else:
        raise FileNotFoundError("Ziel nicht gefunden: %s" % target)

    files, symlinks = [], []
    for candidate in candidates:
        resolved_parent = candidate.parent.resolve()
        rel_parent = _relative_or_none(resolved_parent, base)
        if rel_parent is None:
            # Über einen symlinkten Ordner ausserhalb der Basis gelandet.
            symlinks.append(str(candidate))
            continue
        rel = rel_parent / candidate.name
        if candidate.is_symlink():
            symlinks.append(str(rel))
            continue
        if candidate.is_file():
            files.append(rel)
    return base, sorted(set(files)), sorted(set(symlinks))


def _relative_or_none(path: Path, base: Path):
    """``path`` relativ zu ``base``, oder None wenn es ausserhalb liegt."""
    try:
        return path.relative_to(base)
    except ValueError:
        return None


def snapshot(target: str, snapshot_dir: str, version: str) -> dict:
    """Sichere den aktuellen Zustand des Ziels unter <snapshot_dir>/<version>/.

    Ersetzt ``cp -r <datei> <dir>/v1/``, das mit Exit 1 abbricht, wenn v1 noch
    nicht existiert, und ohne Trailing-Slash eine Datei namens v1 anlegt.

    Schreibt ein manifest.json mit der Dateiliste. Ohne dieses Manifest kann
    ``revert`` im Generic-Modus nicht wissen, welche Dateien die Mutation neu
    angelegt hat, und der Zustand nach einem Revert wäre weder v(N) noch
    v(N+1).
    """
    base, files, symlinks = resolve_scope(target)
    dest = Path(snapshot_dir) / version
    manifest_path = dest / "manifest.json"

    manifest = {
        "version": version,
        # Immer absolut, auch bei Globs. Nur so findet ein Revert aus einem
        # anderen Arbeitsverzeichnis denselben Scope wieder.
        "target": absolute_target(target),
        "target_raw": str(target),
        "base": str(base),
        "is_glob": is_glob(target),
        "files": [str(f) for f in files],
        "file_count": len(files),
        "skipped_symlinks": symlinks,
        "content_hash": _scope_hash(base, files),
        "created_at": _utc_now(),
    }

    # Konflikt VOR dem Kopieren prüfen, sonst ist die alte Baseline schon
    # überschrieben, wenn der Fehler auffällt.
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        old_hash = previous.get("content_hash")
        if old_hash is not None and old_hash != manifest["content_hash"]:
            raise SnapshotConflictError(
                "Snapshot %s existiert bereits mit anderem Inhalt. Ein zweiter "
                "Snapshot auf dieselbe Version würde die saubere Baseline mit "
                "dem mutierten Stand überschreiben, und danach gäbe es keinen "
                "Weg zurück. Erst zurückrollen oder eine neue Version wählen."
                % version
            )

    files_root = dest / "files"
    files_root.mkdir(parents=True, exist_ok=True)
    for rel in files:
        dst = files_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base / rel, dst, follow_symlinks=False)

    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest


def revert(snapshot_dir: str, version: str) -> dict:
    """Stelle den Zustand aus <snapshot_dir>/<version>/ wieder her.

    Dateien, die im Scope liegen aber nicht im Manifest stehen, werden
    gelöscht. Das sind genau die Dateien, die die Mutation neu angelegt hat.

    Das Ziel kommt ausschliesslich aus dem Manifest. Eine frühere Fassung
    erlaubte ein ``--target``-Override, das den Scope verbreitern konnte: ein
    Snapshot auf eine einzelne Datei plus Revert auf das Elternverzeichnis
    löschte alles daneben, im Test unter anderem LICENSE.
    """
    src_root = Path(snapshot_dir) / version
    manifest_path = src_root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("kein Manifest unter %s" % manifest_path)
    manifest = json.loads(manifest_path.read_text())

    # Absolutes Ziel. Der rohe Zielstring ist meist relativ und würde aus einem
    # anderen cwd gegen das falsche Verzeichnis aufgelöst: der Löschdurchgang
    # fiele dann still aus, und die von der Mutation angelegten Dateien blieben
    # liegen. Ein Resume und ein Scheduled Task starten immer mit unbekanntem cwd.
    target = manifest["target"]
    base = Path(manifest["base"])
    snapshot_files = {Path(f) for f in manifest["files"]}

    if not base.is_dir() and not snapshot_files:
        # Leerer Snapshot und Basis nie angelegt. Es gibt nichts zurückzurollen,
        # das ist kein Fehler.
        return {
            "version": version, "target": str(target), "base": str(base),
            "restored": [], "removed": [], "cleanup_skipped": True,
            "note": "Basis existiert nicht und der Snapshot war leer",
        }

    restored = []
    for rel in sorted(snapshot_files):
        dst = _safe_join(base, rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_root / "files" / rel, dst, follow_symlinks=False)
        restored.append(str(rel))

    removed = []
    cleanup_skipped = False
    try:
        current_base, current, _ = resolve_scope(target)
    except FileNotFoundError:
        current_base, current, cleanup_skipped = base, [], True
    if current_base != base:
        raise ScopeMismatchError(
            "Snapshot wurde unter %s angelegt, das Ziel löst jetzt auf %s auf. "
            "Kein Revert, sonst würden fremde Dateien gelöscht."
            % (base, current_base)
        )
    for rel in current:
        if rel not in snapshot_files:
            _safe_join(base, rel).unlink(missing_ok=True)
            removed.append(str(rel))

    # Von der Mutation angelegte, jetzt leere Verzeichnisse mitnehmen. Ein
    # leerer Ordner kann im Generic-Modus die Metrik beeinflussen, etwa als
    # Paketverzeichnis oder über Lint- und Build-Discovery.
    snapshot_dirs = {p for f in snapshot_files for p in Path(f).parents}
    for rel in sorted(
        {Path(r).parent for r in removed} - {Path(".")} - snapshot_dirs,
        key=lambda p: len(p.parts), reverse=True,
    ):
        candidate = base / rel
        while candidate != base and candidate.is_dir() and not any(candidate.iterdir()):
            candidate.rmdir()
            candidate = candidate.parent

    return {
        "version": version,
        "target": str(target),
        "base": str(base),
        "restored": restored,
        "removed": removed,
        "cleanup_skipped": cleanup_skipped,
    }


def _safe_join(base: Path, rel: Path) -> Path:
    """``base / rel``, aber nur wenn das Ergebnis unterhalb von base bleibt.

    Letzte Sicherung gegen ``..``-Anteile in einem manipulierten oder alten
    Manifest. Ein Revert darf unter keinen Umständen ausserhalb seiner eigenen
    Basis schreiben oder löschen.
    """
    target = (base / rel)
    resolved_parent = target.parent.resolve()
    if _relative_or_none(resolved_parent, base.resolve()) is None:
        raise ScopeMismatchError(
            "Pfad %s liegt ausserhalb der Snapshot-Basis %s" % (target, base)
        )
    return target


# ─── Diff ─────────────────────────────────────────────────────────────────


def _diff_lines(path: Path) -> list:
    """Zeilen mit garantiertem Terminator.

    Ohne die Normalisierung verschmelzen die letzte Minus- und die erste
    Plus-Zeile, sobald eine Datei ohne Schluss-Newline endet, und `git apply`
    lehnt den Patch als korrupt ab. Explizites Encoding, weil ein Scheduled Task
    typischerweise ohne gesetztes LANG startet und jede deutsche Datei sonst als
    Binärdatei durchginge.
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return lines


def make_diff(snapshot_dir: str, version: str, out_path: str | None = None) -> dict:
    """Unified Diff zwischen einem Snapshot und dem aktuellen Zustand.

    Beide Bäume werden gewalkt und die Vereinigung der relativen Pfade
    gebildet. Ein naiver Datei-gegen-Datei-Vergleich sähe neu angelegte
    Dateien nicht und stempelte ein legitimes ``script_add`` als NO_OP ab, das
    dann nie evaluiert würde. Dasselbe gilt für Löschungen bei ``prune``.

    ``changed: false`` heisst: die Mutation hat byteweise nichts bewirkt. Ein
    solches Experiment liefert per Konstruktion Delta null und darf nicht als
    Neutralergebnis in die Statistik gehen.
    """
    src_root = Path(snapshot_dir) / version
    manifest_path = src_root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("kein Manifest unter %s" % manifest_path)
    manifest = json.loads(manifest_path.read_text())

    base = Path(manifest["base"])
    old_files = {Path(f) for f in manifest["files"]}
    try:
        _, current, _ = resolve_scope(manifest["target"])
    except FileNotFoundError:
        current = []
    new_files = set(current)

    lines = []
    added = removed = 0
    files_changed, files_added, files_deleted, binary = [], [], [], []

    for rel in sorted(old_files | new_files):
        old_path = src_root / "files" / rel
        new_path = base / rel
        old_exists = rel in old_files and old_path.is_file()
        new_exists = rel in new_files and new_path.is_file()
        try:
            old_lines = _diff_lines(old_path) if old_exists else []
            new_lines = _diff_lines(new_path) if new_exists else []
        except UnicodeDecodeError:
            same = (
                old_exists and new_exists
                and old_path.read_bytes() == new_path.read_bytes()
            )
            if not same:
                binary.append(str(rel))
                files_changed.append(str(rel))
            continue

        if old_lines == new_lines:
            continue

        hunk = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile="a/%s" % rel, tofile="b/%s" % rel,
        ))
        lines.extend(hunk)
        added += sum(1 for h in hunk if h.startswith("+") and not h.startswith("+++"))
        removed += sum(1 for h in hunk if h.startswith("-") and not h.startswith("---"))
        if not old_exists:
            files_added.append(str(rel))
        elif not new_exists:
            files_deleted.append(str(rel))
        else:
            files_changed.append(str(rel))

    text = "".join(lines)
    if out_path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)

    return {
        "changed": bool(files_changed or files_added or files_deleted),
        "lines_added": added,
        "lines_removed": removed,
        "files_changed": sorted(files_changed),
        "files_added": sorted(files_added),
        "files_deleted": sorted(files_deleted),
        "binary_files": sorted(binary),
        "diff_path": str(out_path) if out_path else None,
    }


# ─── Längsvergleich ───────────────────────────────────────────────────────


COMPARISON_ORDER = (
    ("regressed", "Regressionen (richtig zu falsch), HÖCHSTE PRIORITÄT"),
    ("persistent_fail", "Weiterhin falsch"),
    ("improved", "Neu gelöst"),
    ("stable_success", "Weiterhin richtig"),
)


def _eval_id_from(path: Path, exp_path: Path) -> str | None:
    """Eval-Kennung aus dem Pfad: alles zwischen runs/ und dem Seitenordner."""
    parts = list(path.relative_to(exp_path).parts)
    marker = None
    for index, part in enumerate(parts):
        if part in SIDES:
            marker = index
    if marker is None:
        return None
    head = parts[:marker]
    if head and head[0] == "runs":
        head = head[1:]
    return "/".join(head) or "eval"


def compare_runs(experiment_dir: str) -> dict:
    """Paarweiser Vergleich derselben Evals unter beiden Dokumentversionen.

    Ein Aggregatscore verschluckt Regressionen: fünf neue Treffer und drei
    neue Fehler ergeben netto plus zwei und sehen wie Fortschritt aus. Deshalb
    vergleicht SkillOpts Slow Update pro Task-ID und rendert Regressionen
    zuerst.

    Ein Eval gilt als bestanden, wenn alle seine Assertions bestanden sind.
    """
    exp = Path(experiment_dir)
    seen = {}
    for gf in sorted(exp.rglob("grading.json")):
        side = _side_of(gf, exp)
        eval_id = _eval_id_from(gf, exp)
        if side is None or eval_id is None:
            continue
        summary = json.loads(gf.read_text(encoding="utf-8")).get("summary", {})
        bucket = seen.setdefault(eval_id, {}).setdefault(
            side, {"passed": 0, "total": 0, "files": 0}
        )
        # Aggregieren statt überschreiben. Ein outputs/-Unterverzeichnis ist
        # laut SKILL.md erlaubt; vorher entschied die Sortierreihenfolge der
        # Pfade, welche grading.json gewinnt, und score_from_experiment_dir
        # zählte auf demselben Baum beide.
        bucket["passed"] += summary.get("passed", 0)
        bucket["total"] += summary.get("total", 0)
        bucket["files"] += 1

    categories = {name: [] for name, _ in COMPARISON_ORDER}
    unpaired, no_data = [], []
    for eval_id in sorted(seen):
        sides = seen[eval_id]
        if "baseline" not in sides or "with_mutation" not in sides:
            unpaired.append(eval_id)
            continue
        # total == 0 heisst "nichts gemessen", nicht "durchgefallen". Ein
        # abgestürztes Grading als Regression zu rendern schiebt einen
        # Infrastrukturfehler in die Kategorie mit der höchsten Priorität.
        if sides["baseline"]["total"] == 0 or sides["with_mutation"]["total"] == 0:
            no_data.append(eval_id)
            continue
        prev = sides["baseline"]["passed"] == sides["baseline"]["total"]
        curr = sides["with_mutation"]["passed"] == sides["with_mutation"]["total"]
        if not prev and curr:
            categories["improved"].append(eval_id)
        elif prev and not curr:
            categories["regressed"].append(eval_id)
        elif not prev and not curr:
            categories["persistent_fail"].append(eval_id)
        else:
            categories["stable_success"].append(eval_id)

    paired = sum(len(v) for v in categories.values())
    return {
        "total_pairs": paired,
        "counts": {name: len(categories[name]) for name, _ in COMPARISON_ORDER},
        "categories": categories,
        "unpaired": unpaired,
        "no_data": no_data,
        "net": len(categories["improved"]) - len(categories["regressed"]),
    }


def format_comparison(result: dict) -> str:
    """Menschenlesbar, Regressionen zuerst.

    Die Reihenfolge ist die eigentliche Anweisung: sie lenkt die knappe
    Aufmerksamkeit auf den Schadensfall statt auf die Erfolgsmeldung.
    """
    lines = ["Paare gesamt: %d" % result["total_pairs"]]
    for name, label in COMPARISON_ORDER:
        lines.append("  %-16s %d" % (name, result["counts"][name]))
    lines.append("  netto            %+d" % result["net"])
    if result["unpaired"]:
        lines.append("  ohne Gegenstück: %s" % ", ".join(result["unpaired"]))
    if result.get("no_data"):
        lines.append(
            "  ohne Messdaten: %s (total == 0, nicht als Regression gewertet)"
            % ", ".join(result["no_data"])
        )
    for name, label in COMPARISON_ORDER:
        items = result["categories"][name]
        if not items:
            continue
        lines.append("")
        lines.append("### %s" % label)
        for item in items:
            lines.append("- %s" % item)
    return "\n".join(lines)


# ─── Artefaktgrösse ───────────────────────────────────────────────────────


def count_tokens(text: str, chars_per_token: int = 3) -> int:
    """Grobe Token-Schätzung.

    Divisor 3, nicht 4: Skill Forges Artefakte sind deutsch, und deutsche
    Komposita tokenisieren schlechter. Mit 4 wäre das Budget rund 30 Prozent zu
    grosszügig. Die Zahl ist eine Schätzung und als solche gekennzeichnet, sie
    ersetzt keinen Tokenizer.
    """
    return len(text) // max(chars_per_token, 1)


def artifact_stats(paths: list, budget: int | None = None,
                   chars_per_token: int = 3) -> dict:
    """Grösse aller vom Loop erzeugten oder geänderten Artefakte.

    Der Scope umfasst bewusst mehr als die SKILL.md. Ein Budget, das nur die
    Hauptdatei zählt, ist über den Mutationstyp ``reference_add`` in einer Runde
    umgangen, und zwar genau durch den Typ, den der Loop unter Budgetdruck
    naheliegenderweise wählt.

    Die geschützten Regionen werden getrennt ausgewiesen. Der Appendix ist
    gedeckelt und wächst nicht unbegrenzt, aber er ist Text, den das Modell
    liest, und gehört deshalb in die Gesamtsumme.
    """
    files, seen = [], set()
    for pattern in paths:
        matches = (
            sorted(globlib.glob(pattern, recursive=True))
            if _GLOB_MAGIC & set(pattern) else [pattern]
        )
        for name in matches:
            # Dedup über den aufgelösten Pfad. Eine Datei, die von zwei Mustern
            # gematcht wird, ginge sonst doppelt ins Budget.
            try:
                key = str(Path(name).resolve())
            except OSError:
                key = name
            if key not in seen:
                seen.add(key)
                files.append(name)

    per_file, chars, lines, protected_chars, skipped = [], 0, 0, 0, []
    for name in files:
        path = Path(name)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Eine Binärdatei im Glob darf die Budgetmessung nicht abbrechen.
            skipped.append(str(path))
            continue
        stripped = strip_regions(text)
        chars += len(text)
        lines += len(text.splitlines())
        protected_chars += len(text) - len(stripped)
        per_file.append({
            "path": str(path),
            "chars": len(text),
            "tokens": count_tokens(text, chars_per_token),
        })

    tokens = chars // max(chars_per_token, 1)
    result = {
        "files": per_file,
        "file_count": len(per_file),
        "skipped_binary": skipped,
        "chars": chars,
        "lines": lines,
        "tokens": tokens,
        "protected_tokens": protected_chars // max(chars_per_token, 1),
        "chars_per_token": chars_per_token,
        "budget": budget,
        # Inklusiv: genau auf Budget ist noch in Ordnung.
        "budget_ok": True if budget is None else tokens <= budget,
        "estimate": True,
    }
    if budget is not None and not result["budget_ok"]:
        result["over_by"] = tokens - budget
        result["forced_category"] = "efficiency"
        result["forced_mutation_type"] = "prune"
    return result


def suggest_token_budget(current_tokens: int, floor: int = 2000,
                         headroom: float = 1.25) -> int:
    """Budget aus der Ausgangsgrösse: ``max(floor, ceil(current * headroom))``."""
    return max(floor, math.ceil(current_tokens * headroom))


# ─── Invarianten (Generic-Modus) ──────────────────────────────────────────


class ProtectedPathError(RuntimeError):
    """Ein als geschützt angegebener Pfad löst zu keiner Datei auf."""


def hash_paths(paths: list, strict: bool = False) -> dict:
    """sha256 je Datei. Globs werden aufgelöst, Verzeichnisse rekursiv gelesen.

    Der Verzeichnis-Zweig ist nicht optional: die Wizard-Vorschlagsliste für
    ``protected_paths`` nennt ``tests/`` als Verzeichnis. Eine frühere Fassung
    behandelte jeden nicht-Glob als einzelnen Dateinamen, liess Verzeichnisse
    durch ``is_file()`` fallen, und der gesamte Testordner war ungeschützt,
    ohne dass irgendwo eine Meldung erschien.
    """
    result = {}
    for pattern in paths:
        path = Path(pattern)
        if _GLOB_MAGIC & set(pattern) and not path.exists():
            matches = sorted(globlib.glob(pattern, recursive=True))
        elif path.is_dir():
            matches = sorted(str(q) for q in path.rglob("*"))
        else:
            matches = [pattern]
        found = 0
        for name in matches:
            candidate = Path(name)
            if candidate.is_file() and not candidate.is_symlink():
                result[str(candidate)] = hashlib.sha256(
                    candidate.read_bytes()
                ).hexdigest()
                found += 1
        if strict and found == 0:
            raise ProtectedPathError(
                "protected_path %r löst zu keiner Datei auf. Ein Schutz, der "
                "nichts schützt, ist schlimmer als keiner: er sieht im Log aus "
                "wie einer." % pattern
            )
    return result


def snapshot_scope(scope: str, protected_paths: list,
                   strict: bool = True) -> dict:
    """Zustand vor der Mutation: Hashes der geschützten Pfade plus Scope-Grösse.

    Die Scope-Grösse ist die Untergrenze gegen "weniger messen". Die optimale
    Mutation für ``flake8 src/ | wc -l`` ist, ``src/`` zu löschen; für
    Jest-Coverage, die ungedeckten Tests zu entfernen. Beides verbessert die
    Zahl und verschlechtert die Software.

    Erfasst werden Dateizahl, Gesamtgrösse UND die Liste der Pfade. Nur mit der
    Liste fällt auf, wenn die Mutation gemessene Dateien gegen neue austauscht
    und die Kardinalität dabei gleich bleibt.
    """
    files, total_bytes, rel_paths = [], 0, []
    try:
        base, files, _ = resolve_scope(scope)
        for rel in files:
            try:
                total_bytes += (base / rel).stat().st_size
                rel_paths.append(str(rel))
            except OSError:
                # Einzelne Datei ist zwischen Auflösung und stat verschwunden.
                # Das darf nicht die gesamte Zählung auf null setzen.
                continue
    except FileNotFoundError:
        pass
    return {
        "scope": scope,
        "protected_paths": list(protected_paths),
        "protected": hash_paths(protected_paths, strict=strict),
        "file_count": len(rel_paths),
        "total_bytes": total_bytes,
        "files": sorted(rel_paths),
        "created_at": _utc_now(),
    }


def check_invariants(before: dict, invariant_command: str | None = None,
                     min_scope_ratio: float = 0.9,
                     timeout: int = 900) -> dict:
    """Prüfe nach der Mutation, ob die Messung überhaupt noch vergleichbar ist.

    Vier Invarianten:

    1. Geschützte Pfade unverändert, weder geändert noch gelöscht noch neu
       angelegt. Das sind Metrik- und Test-Konfiguration, nicht die gemessenen
       Quelldateien.
    2. Die Anzahl der gemessenen Dateien ist nicht wesentlich gesunken.
    3. Die Gesamtgrösse ist nicht wesentlich gesunken, und die ursprünglich
       gemessenen Dateien existieren noch. Ohne diese Prüfung liesse sich der
       Scope durch Austausch alt gegen neu konstant halten, während der
       gemessene Inhalt verschwindet.
    4. Ein Invarianten-Command läuft weiterhin mit Exit 0 durch.

    Der Command läuft nur, wenn die geschützten Pfade unverändert sind. SkillOpt
    formuliert denselben Grundsatz: "Never execute a test file after detecting
    that the evaluated agent changed it."
    """
    after = snapshot_scope(
        before["scope"], before.get("protected_paths", []), strict=False
    )

    old_hashes = before.get("protected", {})
    new_hashes = after["protected"]
    violated = sorted(p for p, h in old_hashes.items()
                      if p in new_hashes and new_hashes[p] != h)
    vanished = sorted(p for p in old_hashes if p not in new_hashes)
    appeared = sorted(p for p in new_hashes if p not in old_hashes)

    before_count = before.get("file_count", 0)
    before_bytes = before.get("total_bytes", 0)
    before_files = set(before.get("files", []))

    if before_count == 0:
        # Leerer Ausgangs-Scope: die Verhältnisse sind nicht definiert, aber
        # ein leerer Scope kann auch nicht schrumpfen.
        count_ratio = byte_ratio = 1.0
    else:
        count_ratio = after["file_count"] / before_count
        byte_ratio = after["total_bytes"] / max(before_bytes, 1)

    missing_measured = sorted(before_files - set(after.get("files", [])))
    kept_ratio = (
        1.0 if not before_files
        else (len(before_files) - len(missing_measured)) / len(before_files)
    )

    scope_ok = (
        count_ratio >= min_scope_ratio
        and byte_ratio >= min_scope_ratio
        and kept_ratio >= min_scope_ratio
    )

    exit_code, command_ran, timed_out = None, False, False
    if invariant_command and not violated and not vanished and not appeared:
        command_ran = True
        try:
            proc = subprocess.run(
                invariant_command, shell=True, capture_output=True,
                text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = -1

    ok = (
        not violated and not vanished and not appeared and scope_ok
        and (exit_code is None or exit_code == 0)
    )
    reasons = []
    if violated:
        reasons.append("geschützte Pfade geändert: %s" % ", ".join(violated))
    if vanished:
        reasons.append("geschützte Pfade gelöscht: %s" % ", ".join(vanished))
    if appeared:
        reasons.append(
            "neue Dateien in geschützten Pfaden: %s. Eine zusätzliche Testdatei "
            "verändert das Verhalten des invariant_command genauso wie eine "
            "geänderte." % ", ".join(appeared)
        )
    if count_ratio < min_scope_ratio:
        reasons.append(
            "Scope von %d auf %d Dateien geschrumpft (Verhältnis %.2f < %.2f). "
            "Weniger zu messen ist keine Verbesserung."
            % (before_count, after["file_count"], count_ratio, min_scope_ratio)
        )
    if byte_ratio < min_scope_ratio:
        reasons.append(
            "Scope von %d auf %d Bytes geschrumpft (Verhältnis %.2f < %.2f)."
            % (before_bytes, after["total_bytes"], byte_ratio, min_scope_ratio)
        )
    if kept_ratio < min_scope_ratio:
        reasons.append(
            "%d der ursprünglich gemessenen Dateien fehlen: %s"
            % (len(missing_measured), ", ".join(missing_measured[:5]))
        )
    if exit_code not in (None, 0):
        reasons.append(
            "invariant_command endete mit Exit %s%s"
            % (exit_code, " (Timeout)" if timed_out else "")
        )

    return {
        "ok": ok,
        "decision": None if ok else "INVALID",
        "violated_paths": violated,
        "vanished_paths": vanished,
        "appeared_paths": appeared,
        "scope_before": before_count,
        "scope_after": after["file_count"],
        "scope_ratio": round(count_ratio, 4),
        "byte_ratio": round(byte_ratio, 4),
        "kept_ratio": round(kept_ratio, 4),
        "missing_measured": missing_measured[:20],
        "min_scope_ratio": min_scope_ratio,
        "invariant_command_ran": command_ran,
        "invariant_exit_code": exit_code,
        "reasons": reasons,
    }


# ─── Geschützte Regionen ──────────────────────────────────────────────────


PROTECTED_REGIONS = {
    "FORGE_KEEP": ("<!-- FORGE_KEEP_START -->", "<!-- FORGE_KEEP_END -->"),
    "FORGE_APPENDIX": ("<!-- FORGE_APPENDIX_START -->", "<!-- FORGE_APPENDIX_END -->"),
}

APPENDIX_NOTICE = "<!-- Vom Loop verwaltet. Der Mutator fasst diesen Block nicht an. -->"


def extract_regions(text: str) -> dict:
    """Inhalt und Markerzahl jeder geschützten Region.

    Gibt pro Region ``{"content": str|None, "starts": int, "ends": int}``
    zurück. Die Zählung ist nicht kosmetisch: eine frühere Fassung nahm nur das
    erste Vorkommen, und ein zweites Markerpaar am Dateiende wurde damit nie
    verglichen. Der Mutator konnte sich so einen Schutzraum anhängen, den die
    Prüfung nicht sah und den ``strip_regions`` zusätzlich aus jeder
    Längenmessung entfernte.
    """
    found = {}
    for name, (start, end) in PROTECTED_REGIONS.items():
        starts = text.count(start)
        ends = text.count(end)
        s = text.find(start)
        e = text.find(end, s + len(start)) if s != -1 else -1
        found[name] = {
            "content": text[s + len(start):e] if s != -1 and e != -1 else None,
            "starts": starts,
            "ends": ends,
        }
    return found


def region_content(text: str, name: str):
    """Bequemer Zugriff auf den Inhalt einer Region."""
    return extract_regions(text)[name]["content"]


def strip_regions(text: str) -> str:
    """Text ohne die geschützten Regionen, für Längenmessungen."""
    for start, end in PROTECTED_REGIONS.values():
        while True:
            s = text.find(start)
            if s == -1:
                break
            e = text.find(end, s)
            if e == -1:
                text = text[:s] + text[s + len(start):]
                break
            text = text[:s] + text[e + len(end):]
    return text


def verify_protected_regions(snapshot_path: str, mutated_path: str) -> dict:
    """Byteweiser Vergleich der geschützten Regionen vor und nach der Mutation.

    Die Durchsetzung gehört hierher und nicht in den Sanity-Check des Mutators.
    Ein Agent, der eine Regel nicht befolgt hat, per Prompt prüfen zu lassen, ob
    er sie befolgt hat, ist zirkulär.

    ``FORGE_KEEP`` gehört dem User: Invarianten, die der Loop unter keinen
    Umständen anfasst. ``FORGE_APPENDIX`` gehört dem Loop und nimmt die
    EXECUTION_LAPSE-Notizen auf, die das Gate umgehen. Beide sind für den
    Mutator tabu.

    Geprüft wird nicht nur der Inhalt, sondern auch die Anzahl der Marker. Ein
    zweites Markerpaar ist eine Verletzung, auch wenn der erste Block unberührt
    bleibt.
    """
    before = extract_regions(Path(snapshot_path).read_text(encoding="utf-8"))
    after = extract_regions(Path(mutated_path).read_text(encoding="utf-8"))

    violated, removed, added, duplicated, malformed = [], [], [], [], []
    for name in PROTECTED_REGIONS:
        b, a = before[name], after[name]
        if a["starts"] > 1 or a["ends"] > 1:
            duplicated.append(name)
        if a["starts"] != a["ends"]:
            malformed.append(name)
        if b["content"] is None and a["content"] is None:
            continue
        if b["content"] is None:
            added.append(name)
        elif a["content"] is None:
            removed.append(name)
        elif b["content"] != a["content"]:
            violated.append(name)

    return {
        "ok": not (violated or removed or added or duplicated or malformed),
        "violated": sorted(violated),
        "removed": sorted(removed),
        "added": sorted(added),
        "duplicated": sorted(duplicated),
        "malformed": sorted(malformed),
        "regions_present": sorted(
            n for n in after if after[n]["content"] is not None
        ),
    }


def _canonical(note: str) -> str:
    """Kanonform für den Dedup-Vergleich von Appendix-Notizen."""
    return re.sub(r"\s+", " ", note.lower()).strip().rstrip(" .;:,_-")


class AppendixError(RuntimeError):
    """Die Appendix-Region ist in einem Zustand, in dem Anhängen gefährlich wäre."""


def _neutralise_markers(note: str) -> str:
    """Entschärfe Regionsmarker im Notiztext.

    Eine Notiz, die wörtlich einen Marker enthält, verschiebt sonst die Grenze
    einer Region und legt den Loop still: ab dann meldet jede
    verify-regions-Prüfung eine Verletzung, und niemand sieht warum.
    """
    for start, end in PROTECTED_REGIONS.values():
        for marker in (start, end):
            note = note.replace(marker, marker.replace("<!--", "<!\u2011\u2011"))
    return note


def append_appendix_notes(skill_path: str, notes: list,
                          max_notes: int = 15) -> dict:
    """Hänge EXECUTION_LAPSE-Notizen an die geschützte Appendix-Region.

    Diese Notizen umgehen das Gate. Sie entstehen aus Fehlern, bei denen die
    korrekte Regel bereits im Skill stand und der Agent sie nur nicht befolgt
    hat. Eine Body-Mutation wäre dort falsch: sie schriebe eine gültige Regel
    wegen eines einmaligen Ausrutschers um.

    Weil sie das Gate umgehen, sind sie gedeckelt. Bei Überschreitung wird
    nichts still verworfen, sondern in ``dropped_oldest`` gemeldet.

    Eine halb vorhandene Region (nur START oder nur END) ist ein kaputter
    Zustand und kein Anlass zum Überschreiben. Eine frühere Fassung löschte in
    diesem Fall den gesamten Dateirest ab dem verwaisten START, inklusive der
    FORGE_KEEP-Region des Users, und meldete Erfolg.
    """
    if max_notes < 1:
        raise AppendixError(
            "max_notes muss mindestens 1 sein, war %r. Ein Deckel von 0 würde "
            "jede Notiz sofort wieder verwerfen." % max_notes
        )

    path = Path(skill_path)
    text = path.read_text(encoding="utf-8")
    start, end = PROTECTED_REGIONS["FORGE_APPENDIX"]
    n_start, n_end = text.count(start), text.count(end)

    if n_start != n_end:
        raise AppendixError(
            "Appendix-Region ist unvollständig: %d START, %d END in %s. "
            "Erst reparieren, dann anhängen." % (n_start, n_end, skill_path)
        )
    if n_start > 1:
        raise AppendixError(
            "%d Appendix-Regionen in %s. Mehrdeutig, kein Anhängen."
            % (n_start, skill_path)
        )
    if n_start == 1 and text.index(start) > text.index(end):
        raise AppendixError(
            "END steht vor START in %s. Kaputte Region, kein Anhängen." % skill_path
        )

    if n_start == 0:
        text = text.rstrip("\n") + "\n\n%s\n%s\n%s\n" % (start, APPENDIX_NOTICE, end)

    s = text.index(start) + len(start)
    e = text.index(end, s)
    body = text[s:e]

    existing = [
        line.strip()[2:].strip() for line in body.splitlines()
        if line.strip().startswith("- ")
    ]
    seen = {_canonical(x) for x in existing}

    added, duplicates = [], []
    for note in notes:
        note = _neutralise_markers(" ".join(str(note).split()))
        if not note:
            continue
        if _canonical(note) in seen:
            duplicates.append(note)
            continue
        seen.add(_canonical(note))
        existing.append(note)
        added.append(note)

    dropped = []
    if len(existing) > max_notes:
        dropped = existing[:-max_notes]
        existing = existing[-max_notes:]

    rendered = "\n%s\n" % APPENDIX_NOTICE
    if existing:
        rendered += "\n".join("- %s" % n for n in existing) + "\n"
    result_text = text[:s] + rendered + text[e:]

    # Letzte Sicherung: der Schreibvorgang darf die Markerlage nicht verändern.
    check = extract_regions(result_text)
    for name, info in check.items():
        if info["starts"] > 1 or info["starts"] != info["ends"]:
            raise AppendixError(
                "Schreibvorgang hätte die Region %s beschädigt (%d START, "
                "%d END). Nichts geschrieben."
                % (name, info["starts"], info["ends"])
            )
    path.write_text(result_text, encoding="utf-8")

    return {
        "added": added,
        "skipped_duplicate": duplicates,
        "dropped_oldest": dropped,
        "truncated": bool(dropped),
        "total": len(existing),
        "max_notes": max_notes,
    }


# ─── Verworfene Mutationen ────────────────────────────────────────────────


REJECTED_HEADER = (
    "Bereits verworfen. Nutze diese Liste, um wirkungslose Änderungen nicht zu "
    "wiederholen und ungelöste Fehlermuster zu priorisieren."
)


def append_rejected(path: str, record: dict, excerpt_chars: int = 200) -> dict:
    """Schreibe eine Nicht-KEEP-Entscheidung wörtlich fort.

    Eigene Datei, weil die History-Kompaktierung sie sonst kürzt. Erfasst
    werden REVERT und NEUTRAL, nicht nur Near-Misses: eine deutliche Regression
    ist mindestens so lehrreich wie ein Beinahe-Treffer.
    """
    entry = {
        "experiment": record.get("experiment"),
        "category": record.get("category"),
        "mutation_type": record.get("mutation_type"),
        "decision": record.get("decision"),
        "near_miss": bool(record.get("near_miss", False)),
        "hypothesis": (record.get("hypothesis") or "")[:excerpt_chars],
        "diff_excerpt": (record.get("diff_excerpt") or "")[:excerpt_chars],
        "score_before": record.get("score_before"),
        "score_after": record.get("score_after"),
        "timestamp": _utc_now(),
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # ensure_ascii=True, damit U+2028, U+2029 und U+0085 escaped werden. Sonst
    # zerlegt splitlines() den Datensatz in zwei Zeilen und die zweite Hälfte
    # gilt beim Lesen als kaputtes JSON und verschwindet still.
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
    return entry


def read_rejected(path: str) -> list:
    target = Path(path)
    if not target.exists():
        return []
    records = []
    for line in target.read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _flatten(text: str) -> str:
    """Fremdtext einzeilig und ohne Markdown-Struktur in den Prompt setzen."""
    flat = " ".join(str(text).split())
    return flat.replace("#", "\u2317")


def format_rejected(path: str, limit: int = 10) -> str:
    """Prompt-Block für den Hypothesis-Agent, nach SkillOpts step_buffer.

    Die Kopfzeile ist die eigentliche Anweisung. Ohne sie ist es eine Liste,
    mit ihr ein Auftrag.
    """
    records = read_rejected(path)[-limit:]
    if not records:
        return ""
    lines = [REJECTED_HEADER, ""]
    for entry in records:
        delta = ""
        before, after = entry.get("score_before"), entry.get("score_after")
        if isinstance(before, (int, float)) and isinstance(after, (int, float)):
            delta = " (Score %.4f zu %.4f)" % (before, after)
        lines.append("### %s %s%s%s" % (
            entry.get("experiment", "?"),
            entry.get("decision", "?"),
            delta,
            " [near_miss]" if entry.get("near_miss") else "",
        ))
        lines.append("Kategorie: %s | Typ: %s" % (
            entry.get("category", "?"), entry.get("mutation_type", "?")
        ))
        if entry.get("hypothesis"):
            lines.append("Hypothese: %s" % _flatten(entry["hypothesis"]))
        if entry.get("diff_excerpt"):
            # Einzeilig und ohne führende Markdown-Marker. Ein Diff-Auszug, der
            # mit "### " oder "## " beginnt, sähe im gerenderten Block sonst wie
            # eine eigene Überschrift aus und könnte Anweisungen vortäuschen.
            lines.append("Wortlaut: %s" % _flatten(entry["diff_excerpt"]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ─── Tiered History ──────────────────────────────────────────────────────


def compact_history(history_path: str, detailed_keep: int = 5) -> dict:
    """Komprimiere alte History-Einträge zu Kurzform.

    Behält die letzten `detailed_keep` Experimente vollständig,
    ältere werden auf Kernfelder reduziert. Verhindert Context-Overflow
    bei langen Experiment-Runs (>10 Experimente).

    Die Volldatensätze gehen vorher nach ``history.archive.jsonl``. Vorher
    löschte die Funktion das Feld ``hypothesis`` in-place und ohne Backup,
    also genau das Feld, das der Duplikat-Check in agents/hypothesis.md
    braucht. Ab Experiment 6 sah der Agent, dass eine Kategorie viermal
    reverted wurde, aber nicht mehr, was versucht worden war.

    Die Archivierung ist idempotent: SKILL.md lässt die Kompaktierung ab
    Experiment 6 in jeder Runde laufen, und ohne Filter würde exp-001 bei
    jedem Durchlauf erneut geschrieben.
    """
    path = Path(history_path)
    if not path.exists():
        return {}

    with open(path, "r") as f:
        history = json.load(f)

    experiments = history.get("experiments", [])
    if len(experiments) <= detailed_keep:
        return history

    to_compact = experiments[:-detailed_keep]
    fresh = [e for e in to_compact if not e.get("_compacted")]

    if fresh:
        archive_path = path.parent / "history.archive.jsonl"
        seen = set()
        if archive_path.exists():
            for line in archive_path.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    seen.add(json.loads(line).get("id"))
                except json.JSONDecodeError:
                    continue
        with open(archive_path, "a") as af:
            for exp in fresh:
                if exp.get("id") in seen:
                    continue
                af.write(json.dumps(exp, ensure_ascii=False) + "\n")

    # Ältere Einträge komprimieren
    compacted = []
    for exp in to_compact:
        compacted.append({
            "id": exp.get("id"),
            "version": exp.get("version"),
            "category": exp.get("category"),
            "mutation_type": exp.get("mutation_type"),
            "composite_score": exp.get("composite_score"),
            "delta": exp.get("delta"),
            "decision": exp.get("decision"),
            "near_miss": exp.get("near_miss", False),
            "timestamp": exp.get("timestamp"),
            "_compacted": True,
        })

    # Letzte N Einträge behalten
    detailed = experiments[-detailed_keep:]

    history["experiments"] = compacted + detailed
    history["_compaction_info"] = {
        "compacted_count": len(compacted),
        "detailed_count": len(detailed),
        "archive": "history.archive.jsonl",
        "last_compaction": _utc_now(),
    }

    with open(path, "w") as f:
        json.dump(history, f, indent=2)

    return history


def get_history_for_agent(history_path: str, detailed_keep: int = 5,
                          direction: str = "higher_is_better") -> dict:
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

    total = len(experiments)
    for index, exp in enumerate(experiments):
        if exp.get("_compacted"):
            summary.append(exp)
        elif total - index <= detailed_keep:
            detailed.append(exp)
        else:
            summary.append({
                "id": exp.get("id"),
                "category": exp.get("category"),
                "delta": exp.get("delta"),
                "decision": exp.get("decision"),
            })

    # Statistiken für schnellen Überblick
    all_exps = experiments
    keeps = sum(1 for e in all_exps if e.get("decision") == "KEEP")
    reverts = sum(1 for e in all_exps if e.get("decision") == "REVERT")
    neutrals = sum(1 for e in all_exps if e.get("decision") == "NEUTRAL")
    sign = 1.0 if direction == "higher_is_better" else -1.0
    best_delta = max(
        (sign * as_float(e.get("delta")) for e in all_exps), default=0.0
    )

    return {
        "experiments_detailed": detailed,
        "experiments_summary": summary,
        "stats": {
            "total": len(all_exps),
            "keeps": keeps,
            "reverts": reverts,
            "neutrals": neutrals,
            "best_delta": best_delta,
            "current_best": history.get("current_best"),
            "best_score": history.get("best_score"),
        },
    }


# ─── Checkpoint/Resume ────────────────────────────────────────────────────


def save_checkpoint(workspace_path: str, experiment_id: str,
                    baseline_score: float, coverage_state: dict,
                    next_category: str | None = None,
                    on_disk_version: str | None = None,
                    applied_but_undecided: bool = False,
                    best_version: str | None = None,
                    best_score: float | None = None,
                    experiment_index: int | None = None) -> dict:
    """Speichere einen Resume-Point nach jedem Experiment.

    Ermöglicht Unterbrechung und Fortsetzung über Sessions hinweg.

    Args:
        workspace_path: Pfad zum Skill-Forge Workspace
        experiment_id: ID des zuletzt abgeschlossenen Experiments
        baseline_score: Aktueller Baseline-Score
        coverage_state: Aktueller Coverage-Matrix-Zustand
        next_category: Geplante nächste Kategorie (optional)
        on_disk_version: Snapshot-Version, die aktuell auf der Platte liegt
        applied_but_undecided: Mutation ist angewendet, aber nicht entschieden
        best_version: Snapshot-Version mit dem bisher besten Score
        best_score: Bisher bester gemessener Score
        experiment_index: Laufende Nummer, damit ein Resume weiterzählt

    ``applied_but_undecided`` ist das entscheidende neue Feld. Ohne es kann ein
    Resume nach einem Crash zwischen Mutation und Entscheidung nicht wissen, ob
    die Zieldatei bereits mutiert ist, und misst gegen einen Zustand, den es
    für die Baseline hält.
    """
    checkpoint = {
        "last_completed_experiment": experiment_id,
        "experiment_index": experiment_index,
        "current_baseline_score": baseline_score,
        "best_version": best_version,
        "best_score": best_score,
        "on_disk_version": on_disk_version,
        "applied_but_undecided": applied_but_undecided,
        "coverage_snapshot": coverage_state.get("coverage_summary", {}),
        "next_planned_category": next_category,
        "timestamp": _utc_now(),
        "schema_version": 2,
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
    """Erzeuge eine menschenlesbare Resume-Info.

    Liest durchgehend mit ``.get()``. Die alte Fassung indizierte vier Felder
    direkt und warf bei einem Checkpoint aus einer früheren Version einen
    KeyError, also genau in dem Moment, in dem ein Resume gebraucht wird.
    """
    checkpoint = load_checkpoint(workspace_path)
    if checkpoint is None:
        return "Kein Checkpoint vorhanden, frischer Start."

    coverage = checkpoint.get("coverage_snapshot") or {}
    baseline = checkpoint.get("current_baseline_score")
    baseline_text = "%.4f" % baseline if isinstance(baseline, (int, float)) else "unbekannt"
    lines = [
        "Resume von Checkpoint:",
        "  Letztes Experiment: %s" % checkpoint.get("last_completed_experiment", "unbekannt"),
        "  Baseline-Score: %s" % baseline_text,
        "  Coverage: %.0f%%" % as_float(coverage.get("coverage_percent")),
        "  Gespeichert: %s" % checkpoint.get("timestamp", "unbekannt"),
        "  Nächste Kategorie: %s" % (checkpoint.get("next_planned_category") or "auto"),
    ]
    if checkpoint.get("applied_but_undecided"):
        lines.append(
            "  ACHTUNG: Mutation angewendet, aber nicht entschieden. "
            "Erst auf %s zurückrollen." % (checkpoint.get("on_disk_version") or "?")
        )
    return "\n".join(lines)


# ─── Context-Grouping ────────────────────────────────────────────────────


def group_history_by_category(history_path: str,
                              direction: str = "higher_is_better") -> dict:
    """Gruppiere Experiment-History nach Kategorien statt chronologisch.

    Ideal als Input für den Hypothesis Agent: Pro Kategorie sieht er
    die beste Mutation, häufigste Failure-Patterns und Saturation-Status.
    """
    path = Path(history_path)
    if not path.exists():
        return {}

    with open(path, "r") as f:
        history = json.load(f)

    sign = 1.0 if direction == "higher_is_better" else -1.0
    grouped = {}
    for exp in history.get("experiments", []):
        cat = exp.get("category", "unknown")
        if cat not in grouped:
            grouped[cat] = {
                "experiments": [],
                "total": 0,
                "keeps": 0,
                "reverts": 0,
                "neutrals": 0,
                "best_delta": None,
                "best_experiment": None,
            }

        g = grouped[cat]
        g["experiments"].append({
            "id": exp.get("id"),
            "delta": as_float(exp.get("delta")),
            "decision": exp.get("decision"),
            "near_miss": exp.get("near_miss", False),
            "hypothesis": (exp.get("hypothesis") or "")[:80],
        })
        g["total"] += 1

        decision = exp.get("decision")
        if decision == "KEEP":
            g["keeps"] += 1
        elif decision == "REVERT":
            g["reverts"] += 1
        elif decision == "NEUTRAL":
            g["neutrals"] += 1

        # Richtungsbewusst wie update_coverage_matrix. Bei lower_is_better
        # war sonst die schlimmste Regression der Bestwert, und der
        # Hypothesis-Agent bekam in der Spätphase die falsche Kategorie
        # empfohlen.
        delta = sign * as_float(exp.get("delta"))
        if g["best_delta"] is None or delta > g["best_delta"]:
            g["best_delta"] = delta
            g["best_experiment"] = exp.get("id")

    return grouped


# ─── CLI ──────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Skill Forge, Scoring und Entscheidung")
    parser.add_argument("--version", action="version", version="skill-forge %s" % __version__)
    subparsers = parser.add_subparsers(dest="command", help="Verfügbare Befehle")

    # Score-Berechnung (Skill-Modus)
    score_parser = subparsers.add_parser("score", help="Gate-Score berechnen")
    score_parser.add_argument("experiment_dir", help="Pfad zum Experiment-Verzeichnis")
    score_parser.add_argument(
        "--side",
        choices=list(SIDES),
        help="Nur diese Seite bewerten. Ohne Angabe werden Kandidat und "
             "Baseline gemischt, was fast immer ein Fehler ist.",
    )
    score_parser.add_argument(
        "--use-comparator",
        action="store_true",
        help="LLM-as-Judge Score einbeziehen",
    )
    score_parser.add_argument(
        "--config",
        help="Pfad zur config.json. Liest gate_weights, falls gesetzt.",
    )
    score_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")

    # Entscheidung
    decide_parser = subparsers.add_parser(
        "decide", help="Keep/Revert/Neutral aus zwei Scores bestimmen"
    )
    decide_parser.add_argument("--candidate", type=float, required=True)
    decide_parser.add_argument("--baseline", type=float, required=True)
    decide_parser.add_argument("--config", help="Pfad zur config.json (gewinnt über Defaults)")
    decide_parser.add_argument("--improvement", type=float)
    decide_parser.add_argument("--regression", type=float)
    decide_parser.add_argument("--near-miss-band", dest="near_miss_band", type=float)
    decide_parser.add_argument("--noise-floor", dest="noise_floor", type=float)
    decide_parser.add_argument(
        "--resolution", type=float,
        help="Auflösungsgrenze aus der Assertion-Zahl, siehe score --json",
    )
    decide_parser.add_argument(
        "--direction",
        choices=["higher_is_better", "lower_is_better"],
        default="higher_is_better",
    )
    decide_parser.add_argument(
        "--relative",
        action="store_true",
        help="Delta relativ zur Baseline rechnen (Generic-Modus)",
    )

    # Plateau
    plateau_parser = subparsers.add_parser(
        "plateau", help="Prüfen, ob die letzten N Entscheidungen ein Plateau sind"
    )
    plateau_parser.add_argument("history_path", help="Pfad zur history.json")
    plateau_parser.add_argument("--window", type=int, default=3)

    # Auflösungsgrenze
    res_parser = subparsers.add_parser(
        "resolution", help="Kleinste messbare Score-Differenz bestimmen"
    )
    res_parser.add_argument("--assertions", type=int, required=True)
    res_parser.add_argument("--flips", type=int, default=2)

    # Split-Zuordnung
    split_parser = subparsers.add_parser(
        "split-assign", help="Evals auf train/val/test verteilen"
    )
    split_parser.add_argument("evals_path", help="Pfad zur evals.json")
    split_parser.add_argument("--seed", type=int, default=42)
    split_parser.add_argument("--val", dest="val_fraction", type=float, default=0.25)
    split_parser.add_argument("--test", dest="test_fraction", type=float, default=0.25)
    split_parser.add_argument(
        "--dry-run", action="store_true",
        help="Zuordnung nur anzeigen, evals.json nicht schreiben",
    )

    # Diff
    diff_parser = subparsers.add_parser(
        "diff", help="Unified Diff zwischen Snapshot und aktuellem Zustand"
    )
    diff_parser.add_argument("--snapshot-dir", dest="snapshot_dir", required=True)
    diff_parser.add_argument("--version", dest="snapshot_version", required=True)
    diff_parser.add_argument("--out", dest="out_path", help="Zieldatei für den Diff")

    # Längsvergleich
    cmp_parser = subparsers.add_parser(
        "compare", help="Paarweiser Vergleich beider Seiten je Eval"
    )
    cmp_parser.add_argument("experiment_dir")
    cmp_parser.add_argument("--json", dest="as_json", action="store_true")

    # Artefaktgrösse
    stats_parser = subparsers.add_parser(
        "artifact-stats", help="Grösse der Loop-Artefakte gegen das Token-Budget"
    )
    stats_parser.add_argument("paths", nargs="+", help="Dateien oder Globs")
    stats_parser.add_argument("--budget", type=int)
    stats_parser.add_argument("--chars-per-token", dest="chars_per_token",
                              type=int, default=3)
    stats_parser.add_argument(
        "--suggest-budget", dest="suggest_budget", action="store_true",
        help="Budget aus der aktuellen Grösse vorschlagen: max(2000, 1.25x)",
    )

    # Invarianten
    inv_snap = subparsers.add_parser(
        "invariants-snapshot", help="Zustand der geschützten Pfade vor der Mutation"
    )
    inv_snap.add_argument("--scope", required=True, help="Datei, Verzeichnis oder Glob")
    inv_snap.add_argument("--protected", nargs="*", default=[],
                          help="Pfade oder Globs, die unverändert bleiben müssen")
    inv_snap.add_argument("--out", dest="out_path", required=True)

    inv_check = subparsers.add_parser(
        "invariants-check", help="Nach der Mutation prüfen, ob die Messung gilt"
    )
    inv_check.add_argument("--before", dest="before_path", required=True)
    inv_check.add_argument("--command", dest="invariant_command",
                           help="Muss weiterhin mit Exit 0 durchlaufen")
    inv_check.add_argument("--min-scope-ratio", dest="min_scope_ratio",
                           type=float, default=0.9)

    # Geschützte Regionen
    regions_parser = subparsers.add_parser(
        "verify-regions", help="Geschützte Regionen vor und nach der Mutation vergleichen"
    )
    regions_parser.add_argument("snapshot_file", help="Datei aus dem Snapshot")
    regions_parser.add_argument("mutated_file", help="Aktuelle, mutierte Datei")

    apx_parser = subparsers.add_parser(
        "appendix-append", help="EXECUTION_LAPSE-Notizen an die Appendix-Region hängen"
    )
    apx_parser.add_argument("skill_path")
    apx_parser.add_argument(
        "--from-json", dest="from_json", required=True,
        help="JSON-Datei mit einer Liste von Notizen oder {\"appendix_notes\": [...]}. "
             "Mehrzeiliger Text als CLI-Argument zerbricht am ersten Codeblock.",
    )
    apx_parser.add_argument("--max-notes", dest="max_notes", type=int, default=15)

    # Verworfene Mutationen
    rej_parser = subparsers.add_parser(
        "rejected-append", help="Nicht-KEEP-Entscheidung wörtlich fortschreiben"
    )
    rej_parser.add_argument("rejected_path", help="Pfad zur rejected.jsonl")
    rej_parser.add_argument(
        "--from-json", dest="from_json", required=True,
        help="JSON-Datei mit dem Datensatz, meist die decision.json des Experiments",
    )

    rejfmt_parser = subparsers.add_parser(
        "rejected-format", help="Prompt-Block für den Hypothesis-Agent rendern"
    )
    rejfmt_parser.add_argument("rejected_path")
    rejfmt_parser.add_argument("--limit", type=int, default=10)

    # Snapshot
    snap_parser = subparsers.add_parser("snapshot", help="Zustand vor der Mutation sichern")
    snap_parser.add_argument("--target", required=True, help="Datei, Verzeichnis oder Glob")
    snap_parser.add_argument("--snapshot-dir", dest="snapshot_dir", required=True)
    snap_parser.add_argument("--version", dest="snapshot_version", required=True)

    # Revert
    revert_parser = subparsers.add_parser("revert", help="Snapshot wiederherstellen")
    revert_parser.add_argument("--snapshot-dir", dest="snapshot_dir", required=True)
    revert_parser.add_argument("--version", dest="snapshot_version", required=True)

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
    metric_parser.add_argument(
        "--invariants-before", dest="invariants_before",
        help="JSON aus invariants-snapshot. Ohne bestandene Prüfung gibt es "
             "keinen Metrikwert, sondern INVALID.",
    )
    metric_parser.add_argument("--invariant-command", dest="invariant_command")

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
    tsv_append_parser.add_argument("--decision", required=True, choices=list(DECISIONS))
    tsv_append_parser.add_argument("--category", required=True)
    tsv_append_parser.add_argument("--duration", type=float, default=0)
    tsv_append_parser.add_argument(
        "--direction",
        choices=["higher_is_better", "lower_is_better"],
        default="higher_is_better",
        help="Bei lower_is_better wird das Delta orientiert geschrieben, "
             "damit ein positives Delta im Log immer eine Verbesserung ist.",
    )

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
    cov_update_parser.add_argument("--decision", required=True, choices=list(DECISIONS))
    cov_update_parser.add_argument("--delta", type=float, required=True)
    cov_update_parser.add_argument(
        "--direction",
        choices=["higher_is_better", "lower_is_better"],
        default="higher_is_better",
    )

    # v3 Features: Tiered History, Checkpoint, Grouping
    _register_new_subcommands(subparsers)

    args = parser.parse_args()

    if args.command == "score":
        try:
            result = score_from_experiment_dir(
                args.experiment_dir,
                load_use_comparator(args.config, args.use_comparator),
                side=args.side,
                weights=load_gate_weights(args.config),
            )
        except (NoGradingDataError, NoJudgeDataError) as exc:
            print("Fehler: %s" % exc, file=sys.stderr)
            sys.exit(2)
        except ValueError as exc:
            print("Fehler: %s" % exc, file=sys.stderr)
            sys.exit(2)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            details = result["details"]
            print(f"Gate-Score: {result['composite_score']:.2%}")
            print(f"  Assertion Pass Rate: {result['assertion_pass_rate']:.2%}")
            if result["llm_judge_score"] is not None:
                print(f"  LLM Judge Score:     {result['llm_judge_score']:.2%}")
            if details["efficiency_score"] is None:
                print("  Efficiency (nur Report): keine Timing-Daten")
            else:
                print(f"  Efficiency (nur Report): {details['efficiency_score']:.2%}")
            print(f"  Seite: {result['side'] or 'alle (gemischt!)'}")
            print(f"  Tokens: {details['total_tokens']}")
            print(f"  Duration: {details['total_duration_seconds']}s")

    elif args.command == "decide":
        thresholds = load_thresholds(args.config)
        for key in ("improvement", "regression", "near_miss_band",
                    "noise_floor", "resolution"):
            override = getattr(args, key, None)
            if override is not None:
                thresholds[key] = override
        result = decide(
            args.candidate,
            args.baseline,
            direction=args.direction,
            relative=args.relative,
            **thresholds,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "artifact-stats":
        result = artifact_stats(args.paths, args.budget, args.chars_per_token)
        if args.suggest_budget:
            result["suggested_budget"] = suggest_token_budget(result["tokens"])
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if args.budget is not None and not result["budget_ok"]:
            sys.exit(1)

    elif args.command == "invariants-snapshot":
        state = snapshot_scope(args.scope, args.protected)
        out = Path(args.out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        print(json.dumps({
            "scope": state["scope"],
            "file_count": state["file_count"],
            "protected_files": len(state["protected"]),
            "out": str(out),
        }, indent=2, ensure_ascii=False))

    elif args.command == "invariants-check":
        before = json.loads(Path(args.before_path).read_text())
        result = check_invariants(
            before, args.invariant_command, args.min_scope_ratio
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if not result["ok"]:
            sys.exit(3)

    elif args.command == "verify-regions":
        result = verify_protected_regions(args.snapshot_file, args.mutated_file)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if not result["ok"]:
            sys.exit(1)

    elif args.command == "appendix-append":
        payload = json.loads(Path(args.from_json).read_text())
        notes = payload if isinstance(payload, list) else payload.get("appendix_notes", [])
        result = append_appendix_notes(args.skill_path, notes, args.max_notes)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "rejected-append":
        record = json.loads(Path(args.from_json).read_text())
        entry = append_rejected(args.rejected_path, record)
        print(json.dumps(entry, indent=2, ensure_ascii=False))

    elif args.command == "rejected-format":
        block = format_rejected(args.rejected_path, args.limit)
        print(block, end="")

    elif args.command == "resolution":
        value = min_detectable_delta(args.assertions, args.flips)
        print(json.dumps({
            "total_assertions": args.assertions,
            "flips": args.flips,
            "resolution": round(value, 6),
            "note": (
                "Änderungen unterhalb dieses Werts sind mit %d Assertions "
                "nicht messbar." % args.assertions
            ),
        }, indent=2, ensure_ascii=False))

    elif args.command == "split-assign":
        data = json.loads(Path(args.evals_path).read_text())
        evals = data["evals"] if isinstance(data, dict) else data
        try:
            summary = assign_splits(
                evals, args.seed, args.val_fraction, args.test_fraction
            )
        except ValueError as exc:
            print("Fehler: %s" % exc, file=sys.stderr)
            sys.exit(2)
        if not args.dry_run:
            if isinstance(data, dict):
                data["evals"] = evals
                data.setdefault("version", 1)
                data["split_seed"] = args.seed
            else:
                data = {"version": 1, "split_seed": args.seed, "evals": evals}
            Path(args.evals_path).write_text(
                json.dumps(data, indent=2, ensure_ascii=False)
            )
        summary["written"] = not args.dry_run
        summary["assignment"] = {e["id"]: e["split"] for e in evals}
        print(json.dumps(summary, indent=2, ensure_ascii=False))

    elif args.command == "diff":
        try:
            result = make_diff(args.snapshot_dir, args.snapshot_version, args.out_path)
        except FileNotFoundError as exc:
            print("Fehler: %s" % exc, file=sys.stderr)
            sys.exit(2)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "compare":
        result = compare_runs(args.experiment_dir)
        if args.as_json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(format_comparison(result))

    elif args.command == "plateau":
        history = json.loads(Path(args.history_path).read_text())
        decisions = [e.get("decision") for e in history.get("experiments", [])]
        reached = is_plateau(decisions, window=args.window)
        print(json.dumps({
            "plateau": reached,
            "window": args.window,
            "last_decisions": decisions[-args.window:],
            "reason": (
                "%d aufeinanderfolgende Nicht-KEEP" % args.window if reached
                else "kein Plateau"
            ),
        }, indent=2, ensure_ascii=False))

    elif args.command == "snapshot":
        try:
            manifest = snapshot(args.target, args.snapshot_dir, args.snapshot_version)
        except (SnapshotConflictError, FileNotFoundError) as exc:
            print("Fehler: %s" % exc, file=sys.stderr)
            sys.exit(2)
        print(json.dumps(manifest, indent=2, ensure_ascii=False))

    elif args.command == "revert":
        try:
            result = revert(args.snapshot_dir, args.snapshot_version)
        except (ScopeMismatchError, FileNotFoundError) as exc:
            print("Fehler: %s" % exc, file=sys.stderr)
            sys.exit(2)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "metric":
        # stdin ZUERST lesen. Im dokumentierten Pipeline-Aufruf steht dort der
        # Metrik-Output, und ein invariant_command, der stdin anfasst, würde ihn
        # sonst wegfressen.
        output = sys.stdin.read() if args.output == "-" else args.output
        if args.invariant_command and not args.invariants_before:
            print(
                "Fehler: --invariant-command ohne --invariants-before hat keine "
                "Wirkung. Ohne Ausgangszustand gibt es nichts zu vergleichen.",
                file=sys.stderr,
            )
            sys.exit(2)
        if args.invariants_before:
            before = json.loads(Path(args.invariants_before).read_text())
            inv = check_invariants(before, args.invariant_command)
            if not inv["ok"]:
                # Kein Wert, sondern INVALID. Sonst könnte der Prompt den Check
                # überspringen und trotzdem eine Zahl bekommen.
                print(json.dumps(
                    {"decision": "INVALID", "invariants": inv},
                    indent=2, ensure_ascii=False,
                ))
                sys.exit(3)
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
        if args.direction == "lower_is_better":
            delta = -delta
        # Negative Null vermeiden: "%+.4f" % -0.0 ergibt "-0.0000" und sieht im
        # Log wie eine Verschlechterung aus, obwohl sich nichts bewegt hat.
        if delta == 0:
            delta = 0.0
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
            args.matrix_path, args.category, args.experiment, args.decision,
            args.delta, direction=args.direction
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
        result = get_history_for_agent(args.history_path, args.keep, args.direction)
        print(json.dumps(result, indent=2))

    # Checkpoint speichern
    elif args.command == "checkpoint-save":
        coverage = {}
        if args.coverage_path:
            cov_path = Path(args.coverage_path)
            if cov_path.exists():
                coverage = json.loads(cov_path.read_text())
        checkpoint = save_checkpoint(
            args.workspace, args.experiment, args.baseline, coverage,
            next_category=args.next_category,
            on_disk_version=args.on_disk_version,
            applied_but_undecided=args.applied_but_undecided,
            best_version=args.best_version,
            best_score=args.best_score,
            experiment_index=args.experiment_index,
        )
        print(f"Checkpoint gespeichert: {checkpoint['last_completed_experiment']}")

    # Checkpoint laden / Resume-Info
    elif args.command == "checkpoint-info":
        print(get_resume_info(args.workspace))

    # History nach Kategorien gruppieren
    elif args.command == "group-history":
        result = group_history_by_category(args.history_path, args.direction)
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
    agent_hist_parser.add_argument(
        "--direction", choices=["higher_is_better", "lower_is_better"],
        default="higher_is_better")

    # Checkpoint speichern
    cp_save_parser = subparsers.add_parser(
        "checkpoint-save", help="Resume-Point speichern"
    )
    cp_save_parser.add_argument("workspace", help="Workspace-Pfad")
    cp_save_parser.add_argument("--experiment", required=True)
    cp_save_parser.add_argument("--baseline", type=float, required=True)
    cp_save_parser.add_argument("--coverage-path", dest="coverage_path")
    cp_save_parser.add_argument("--next-category", dest="next_category")
    cp_save_parser.add_argument("--on-disk-version", dest="on_disk_version")
    cp_save_parser.add_argument(
        "--applied-but-undecided", dest="applied_but_undecided", action="store_true",
        help="Mutation liegt auf der Platte, ist aber noch nicht entschieden",
    )
    cp_save_parser.add_argument("--best-version", dest="best_version")
    cp_save_parser.add_argument("--best-score", dest="best_score", type=float)
    cp_save_parser.add_argument("--experiment-index", dest="experiment_index", type=int)

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
    group_parser.add_argument(
        "--direction", choices=["higher_is_better", "lower_is_better"],
        default="higher_is_better")


if __name__ == "__main__":
    main()
