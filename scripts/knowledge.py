#!/usr/bin/env python3
"""Wissenslücken-Queue für Skill Forge (Phase 1).

Dieses Script verwaltet ausschliesslich die *Fragen*: Was weiss der Ziel-Skill
nicht, das er wissen müsste? Es schreibt keinen Wissensbestand, nimmt keine
Quellen auf und fasst die Ziel-SKILL.md nicht an. Das ist Absicht — Phase 1
ist reine Erkennung, damit der Loop sagen kann "hier fehlt mir genau das",
bevor irgendein Mechanismus existiert, der Wissen ablegt.

Eigenes Script neben ``composite_score.py``, weil dort die Entscheidungslogik
liegt und genau eine Aufgabe hat: aus zwei Zahlen ein Urteil machen. Eine
Frageliste hat einen anderen Fehlermodus und bekommt eine eigene Testdatei.

Ablage ist ``<workspace>/knowledge-gaps.jsonl``, append-only und neben der
History, nicht darin: die History-Kompaktierung würde eine offene Frage sonst
nach fünf Experimenten wegkürzen. Jede Zeile ist ein vollständiger Datensatz;
der jeweils letzte Datensatz je ``gap_id`` beschreibt den aktuellen Stand. So
bleibt nachvollziehbar, wann eine Frage gestellt und wann sie wie beantwortet
wurde, ohne dass eine Zeile je überschrieben wird.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

__version__ = "1.0.0"


# ─── Status ───────────────────────────────────────────────────────────────

# open      Frage gestellt, wartet auf den Menschen oder eine Quelle
# sourced   Aus einer freigegebenen Quelle beantwortet (ab Phase 2/3)
# answered  Vom Menschen beantwortet (ab Phase 2)
# rejected  Der Mensch hält die Frage für irrelevant — nie erneut stellen
# conflict  Antwort widerspricht dem Bestand, Mensch entscheidet (ab Phase 4)
STATUSES = ("open", "sourced", "answered", "rejected", "conflict")

# Ein Gap in diesem Status blockiert das erneute Stellen derselben Frage und
# rechtfertigt ein weiteres DEFERRED. Alles andere ist bereits geklärt: dort
# ist eine Wiederholung ein Hinweis darauf, dass das Wissen den Agenten nicht
# erreicht, und das ist ein Verweis-Problem (Spur B), keine Wissenslücke.
UNRESOLVED = ("open", "conflict")

GAPS_HEADER = (
    "Offene Wissensfragen. Diese Lücken sind bereits gemeldet und warten auf "
    "eine Antwort. Stelle keine davon erneut. Eine Frage mit Status answered "
    "oder sourced ist beantwortet: taucht das Fehlermuster trotzdem wieder "
    "auf, fehlt nicht das Wissen, sondern der Verweis darauf — das ist ein "
    "SKILL_DEFECT, keine Wissenslücke."
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


# ─── Normalisierung und Dedup ─────────────────────────────────────────────


_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def normalise_question(question: str) -> str:
    """Vergleichsform einer Frage: Unicode-normalisiert, ohne Satzzeichen.

    Bewusst nur exakte Gleichheit nach dieser Normalisierung, keine Ähnlichkeit.
    Ein unscharfer Abgleich verschluckt still zwei verschiedene Fragen, die
    zufällig ähnlich klingen, und das ist der teurere Fehler: eine doppelte
    Frage kostet den Menschen zehn Sekunden, eine verschluckte kostet eine
    Nacht. Nahe Duplikate fängt der Hypothesis-Agent ab, der die offene Liste
    in seinem Kontext sieht — nicht diese Funktion.
    """
    text = unicodedata.normalize("NFKC", str(question)).casefold()
    text = _PUNCT.sub(" ", text)
    return " ".join(text.split())


def _flatten(text: str) -> str:
    """Fremdtext einzeilig und ohne Markdown-Struktur in den Prompt setzen.

    Die Frage stammt aus einem Agenten, der Transcripts gelesen hat, und
    Transcripts enthalten fremde Ausgaben. Ein Text, der mit "## " beginnt,
    sähe im gerenderten Block wie eine eigene Überschrift aus und könnte
    Anweisungen vortäuschen. Gleiche Behandlung wie bei ``rejected-format``.
    """
    flat = " ".join(str(text).split())
    return flat.replace("#", "⌗")


# ─── Lesen und Falten ─────────────────────────────────────────────────────


def read_gaps(path: str) -> list:
    """Alle Datensätze in Dateireihenfolge, kaputte Zeilen übersprungen."""
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


def fold_gaps(path: str) -> list:
    """Aktueller Stand je ``gap_id``: der letzte Datensatz gewinnt.

    Reihenfolge ist die des ersten Auftretens, damit gap-001 oben bleibt und
    die Liste zwischen zwei Läufen nicht springt.
    """
    order: list = []
    latest: dict = {}
    for record in read_gaps(path):
        gap_id = record.get("gap_id")
        if not gap_id:
            continue
        if gap_id not in latest:
            order.append(gap_id)
        latest[gap_id] = record
    return [latest[gap_id] for gap_id in order]


def find_gap(path: str, question: str) -> dict | None:
    """Bestehendes Gap mit derselben normalisierten Frage, oder None."""
    key = normalise_question(question)
    if not key:
        return None
    for record in fold_gaps(path):
        if normalise_question(record.get("question", "")) == key:
            return record
    return None


def next_gap_id(path: str) -> str:
    highest = 0
    for record in read_gaps(path):
        match = re.fullmatch(r"gap-(\d+)", str(record.get("gap_id", "")))
        if match:
            highest = max(highest, int(match.group(1)))
    return "gap-%03d" % (highest + 1)


# ─── Schreiben ────────────────────────────────────────────────────────────


def _write(path: str, entry: dict) -> dict:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # ensure_ascii=True, damit U+2028, U+2029 und U+0085 escaped werden. Sonst
    # zerlegt splitlines() den Datensatz in zwei Zeilen und die zweite Hälfte
    # gilt beim Lesen als kaputtes JSON und verschwindet still.
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
    return entry


def append_gap(
    path: str,
    *,
    question: str,
    why_needed: str,
    answer_shape: str,
    eval_ids: list,
    experiment: str | None = None,
    domain: str | None = None,
    single_eval_accepted: bool = False,
    generalizability: str = "",
) -> dict:
    """Melde eine Wissenslücke, falls sie neu ist.

    Drei Pflichtfelder, und keines davon ist Beiwerk:

    * ``question`` — was genau fehlt
    * ``why_needed`` — woran man es gemerkt hat
    * ``answer_shape`` — wie eine brauchbare Antwort aussieht. Das ist der
      Unterschied zwischen einer Frage, die der Mensch morgens in dreissig
      Sekunden beantwortet, und einer, die er wegklickt.

    ``eval_ids`` trägt dieselbe Regel wie ``support_count`` in
    ``agents/hypothesis.md``: mindestens zwei train-Evals müssen das Muster
    zeigen. Geprüft wird die ID-Liste, nicht ein Zähler — eine Liste ist beim
    Lesen nachprüfbar, eine nackte Zahl nicht. Die Ausnahme für einen
    Einzelfall verlangt eine Begründung, sonst ist sie keine.

    Rückgabe enthält das Flag ``created``. Ist es ``False``, wurde nichts
    geschrieben und ``status`` sagt, wie der bestehende Eintrag steht. Der
    Zeitstempel im Datensatz heisst ``created_at`` und nicht ``created``: ein
    Schlüssel, der auf der Platte ein Zeitstempel und im Rückgabewert ein
    Boolean ist, liest sich beim Debuggen falsch herum.
    """
    for field, value in (
        ("question", question),
        ("why_needed", why_needed),
        ("answer_shape", answer_shape),
    ):
        if not str(value or "").strip():
            raise ValueError("Pflichtfeld fehlt oder ist leer: %s" % field)

    ids = [str(e).strip() for e in (eval_ids or []) if str(e).strip()]
    if len(ids) < 2:
        if not single_eval_accepted:
            raise ValueError(
                "Zu wenig Belege: %d eval_ids. Mindestens zwei train-Evals "
                "müssen das Muster zeigen, sonst ist es ein Einzelfall. "
                "Ausnahme nur mit single_eval_accepted und einer Begründung "
                "in generalizability." % len(ids)
            )
        if not str(generalizability or "").strip():
            raise ValueError(
                "single_eval_accepted ohne generalizability. Die Ausnahme "
                "verlangt die Begründung, warum die fehlende Tatsache über "
                "diesen einen Fall hinaus trägt."
            )
        if not ids:
            raise ValueError("eval_ids ist leer — auch die Ausnahme braucht einen Beleg.")

    existing = find_gap(path, question)
    if existing is not None:
        return {
            "created": False,
            "duplicate": True,
            "gap_id": existing.get("gap_id"),
            "status": existing.get("status"),
            "unresolved": existing.get("status") in UNRESOLVED,
        }

    entry = {
        "gap_id": next_gap_id(path),
        "question": " ".join(str(question).split()),
        "why_needed": " ".join(str(why_needed).split()),
        "answer_shape": " ".join(str(answer_shape).split()),
        "eval_ids": ids,
        "experiment": experiment,
        "domain": domain,
        "single_eval_accepted": bool(single_eval_accepted),
        "generalizability": " ".join(str(generalizability).split()),
        "tried_sources": [],
        "status": "open",
        "resolved_by": None,
        "note": "",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }
    _write(path, entry)
    result = dict(entry)
    result["created"] = True
    result["duplicate"] = False
    result["unresolved"] = True
    return result


def resolve_gap(
    path: str,
    gap_id: str,
    status: str,
    *,
    resolved_by: str | None = None,
    note: str = "",
) -> dict:
    """Schreibe einen neuen Stand für ein bestehendes Gap fort.

    Kein Überschreiben: die alte Zeile bleibt stehen, die neue gewinnt beim
    Falten. Wer wissen will, wie lange eine Frage offen war, findet beides.
    """
    if status not in STATUSES:
        raise ValueError(
            "Unbekannter Status %r. Erlaubt: %s" % (status, ", ".join(STATUSES))
        )
    current = None
    for record in fold_gaps(path):
        if record.get("gap_id") == gap_id:
            current = record
            break
    if current is None:
        raise KeyError("Unbekanntes Gap: %s" % gap_id)

    entry = dict(current)
    entry["status"] = status
    entry["resolved_by"] = resolved_by
    entry["note"] = " ".join(str(note).split())
    entry["updated_at"] = _utc_now()
    _write(path, entry)
    return entry


# ─── Auswertung ───────────────────────────────────────────────────────────


def gap_stats(path: str) -> dict:
    """Zählung je Status plus die beiden Zahlen, die der Loop braucht."""
    gaps = fold_gaps(path)
    counts = {status: 0 for status in STATUSES}
    for gap in gaps:
        status = gap.get("status")
        if status in counts:
            counts[status] += 1
    return {
        "total": len(gaps),
        "by_status": counts,
        "unresolved": sum(counts[s] for s in UNRESOLVED),
        "open": counts["open"],
    }


def format_gaps(path: str, limit: int = 10, status: str | None = None) -> str:
    """Prompt-Block für den Hypothesis-Agent und den Morning Report.

    Die Kopfzeile ist die eigentliche Anweisung. Ohne sie ist es eine Liste,
    mit ihr ein Auftrag — dieselbe Konstruktion wie bei ``rejected-format``.
    """
    gaps = fold_gaps(path)
    if status:
        gaps = [g for g in gaps if g.get("status") == status]
    gaps = gaps[-limit:] if limit else gaps
    if not gaps:
        return ""
    lines = [GAPS_HEADER, ""]
    for gap in gaps:
        lines.append("### %s [%s]" % (
            gap.get("gap_id", "?"), gap.get("status", "?")
        ))
        lines.append("Frage: %s" % _flatten(gap.get("question", "")))
        lines.append("Woran erkannt: %s" % _flatten(gap.get("why_needed", "")))
        lines.append("Brauchbare Antwort: %s" % _flatten(gap.get("answer_shape", "")))
        belege = ", ".join(str(e) for e in gap.get("eval_ids", [])) or "—"
        lines.append("Belegt durch: %s | Experiment: %s | Domäne: %s" % (
            belege, gap.get("experiment") or "—", gap.get("domain") or "—",
        ))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ─── CLI ──────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="knowledge.py",
        description="Wissenslücken-Queue für Skill Forge (Phase 1).",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    append = sub.add_parser(
        "gap-append", help="Wissenslücke melden, falls sie neu ist"
    )
    append.add_argument("gaps_path", help="Pfad zur knowledge-gaps.jsonl")
    append.add_argument(
        "--from-json",
        help="hypothesis.json; liest den Block knowledge_request",
    )
    append.add_argument("--question")
    append.add_argument("--why-needed")
    append.add_argument("--answer-shape")
    append.add_argument("--eval-id", action="append", default=[], dest="eval_ids")
    append.add_argument("--experiment")
    append.add_argument("--domain")
    append.add_argument("--single-eval-accepted", action="store_true")
    append.add_argument("--generalizability", default="")

    resolve = sub.add_parser(
        "gap-resolve", help="Stand eines Gaps fortschreiben"
    )
    resolve.add_argument("gaps_path")
    resolve.add_argument("gap_id")
    resolve.add_argument("--status", required=True, choices=list(STATUSES))
    resolve.add_argument("--resolved-by")
    resolve.add_argument("--note", default="")

    listing = sub.add_parser("gap-list", help="Aktueller Stand als JSON")
    listing.add_argument("gaps_path")
    listing.add_argument("--status", choices=list(STATUSES))

    fmt = sub.add_parser(
        "gap-format", help="Textblock für Agent-Kontext und Report"
    )
    fmt.add_argument("gaps_path")
    fmt.add_argument("--limit", type=int, default=10)
    fmt.add_argument("--status", choices=list(STATUSES))

    stats = sub.add_parser("gap-stats", help="Zählung je Status")
    stats.add_argument("gaps_path")

    return parser


def _request_from_json(source: str) -> dict:
    payload = json.loads(Path(source).read_text(encoding="utf-8"))
    request = payload.get("knowledge_request") or {}
    if not request:
        raise ValueError(
            "Kein Block knowledge_request in %s. Eine Hypothese ohne diesen "
            "Block hat keine Wissenslücke gemeldet." % source
        )
    return {
        "question": request.get("question", ""),
        "why_needed": request.get("why_needed", ""),
        "answer_shape": request.get("answer_shape", ""),
        "eval_ids": request.get("eval_ids", []),
        "domain": request.get("domain"),
        "experiment": payload.get("experiment") or payload.get("hypothesis_id"),
        "single_eval_accepted": bool(payload.get("single_eval_accepted", False)),
        "generalizability": payload.get("generalizability", ""),
    }


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "gap-append":
        if args.from_json:
            fields = _request_from_json(args.from_json)
            if args.experiment:
                fields["experiment"] = args.experiment
        else:
            fields = {
                "question": args.question or "",
                "why_needed": args.why_needed or "",
                "answer_shape": args.answer_shape or "",
                "eval_ids": args.eval_ids,
                "domain": args.domain,
                "experiment": args.experiment,
                "single_eval_accepted": args.single_eval_accepted,
                "generalizability": args.generalizability,
            }
        try:
            result = append_gap(args.gaps_path, **fields)
        except ValueError as exc:
            print(json.dumps(
                {"error": str(exc)}, indent=2, ensure_ascii=False
            ), file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.command == "gap-resolve":
        try:
            entry = resolve_gap(
                args.gaps_path, args.gap_id, args.status,
                resolved_by=args.resolved_by, note=args.note,
            )
        except (KeyError, ValueError) as exc:
            print(json.dumps(
                {"error": str(exc)}, indent=2, ensure_ascii=False
            ), file=sys.stderr)
            return 1
        print(json.dumps(entry, indent=2, ensure_ascii=False))
        return 0

    if args.command == "gap-list":
        gaps = fold_gaps(args.gaps_path)
        if args.status:
            gaps = [g for g in gaps if g.get("status") == args.status]
        print(json.dumps(gaps, indent=2, ensure_ascii=False))
        return 0

    if args.command == "gap-format":
        block = format_gaps(args.gaps_path, limit=args.limit, status=args.status)
        if block:
            print(block, end="")
        return 0

    if args.command == "gap-stats":
        print(json.dumps(gap_stats(args.gaps_path), indent=2, ensure_ascii=False))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
