#!/usr/bin/env python3
"""Das Gedächtnis des Optimierers, als verdichteter Musterbestand.

Bis hierher war dieses Gedächtnis eine Datei mit acht Bullets, die alle fünf
Experimente **neu geschrieben** wurde (`editing-notes.md`). Das war bewusst
vergesslich: der Deckel sollte den Kontext klein halten. Der Preis war, dass
jede Erkenntnis nach spätestens zwei Runden aus der Datei fiel, sobald eine
neuere wichtiger schien — und dass am Ende eines Laufs nichts übrig blieb,
worauf der nächste hätte aufbauen können.

WikiSkill (arXiv:2608.27454, Tang et al., Google Research) misst genau diesen
Unterschied. In ihrer Ablation bringt ein persistentes, über Iterationen
verdichtetes Wissen für den Optimierer **+15,0 Punkte** im Schnitt über vier
Benchmarks (48,7 % auf 63,7 %), auf einem davon +21,3. Es ist der grösste
Einzeleffekt in ihrer Arbeit. Ihr Wiki hat kein Limit, wird patch-basiert
verfeinert und nie zurückgesetzt; Musterseiten sammeln Evidenz über Iterationen.

Der Bestand hier ist der Analog dazu, mit zwei Anleihen und einer eigenen Regel:

* **Index im Kontext, Seiten auf Abruf.** Das ist der Trick, der die Sache
  bezahlbar macht: permanent kostet nur die Indextabelle, eine Musterseite wird
  gelesen, wenn ihr Titel zur Frage passt. Ohne diese Trennung wäre ein
  unbegrenzter Bestand genau das Kontextproblem, gegen das der Achter-Deckel
  einmal gebaut wurde.
* **Evidenz ist programmatisch, Deutung ist Sache des Agenten.** Die
  Evidenzzeilen schreibt der Orchestrator aus `decision.json`, nicht der
  Meta-Agent. Ein Agent, der seine eigene Belegzahl schreibt, belegt sich
  selbst.
* **Optimiererseitig, nie zielseitig.** Der Inhalt sagt, *wie* für diesen Skill
  eine gute Änderung aussieht — nicht, was der Skill tun soll. Deshalb ist das
  ein eigenes Script und nicht Teil von `knowledge.py`: dort liegt das Wissen
  des Ziel-Skills, und die beiden zu koppeln wäre genau die Vermischung, vor
  der `agents/meta.md` warnt.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

__version__ = "1.0.0"

PATTERNS_DIR = "patterns"
INDEX_FILE = "INDEX.md"

# Frontmatter-Parser und -Renderer sind eine Kopie aus ``knowledge.py``.
# Absichtlich: die beiden Bestände sollen nicht aneinander hängen. Ein
# gemeinsames Hilfsmodul für zwanzig Zeilen Formatvertrag koppelte den
# Musterbestand des Optimierers an den Wissensbestand des Ziels, und genau
# diese Trennung ist der Zweck der Übung.

EVIDENCE_RE = re.compile(
    r"^-\s+(?P<experiment>exp-\d+)\s*\|\s*(?P<mutation_type>[^|]*)\|"
    r"\s*(?P<decision>[A-Z_]+)\s*\|\s*(?P<delta>[-+0-9.]+)\s*$"
)
DECISIONS = ("KEEP", "REVERT", "NEUTRAL", "SKIP", "NO_OP", "INVALID", "DEFERRED")
MEASURED = ("KEEP", "REVERT", "NEUTRAL")
STATUSES = ("aktiv", "widerlegt")

# Ab wie vielen Belegen ein Muster nicht mehr als vorläufig gilt. Dieselbe Zahl
# wie ``min_support_count`` bei den Hypothesen, aus demselben Grund: ein Muster
# aus einem einzigen Experiment ist eine Anekdote.
MIN_SUPPORT = 2


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def parse_frontmatter(text: str) -> tuple:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("\n---", 1)
    if len(parts) != 2:
        return {}, text
    data: dict = {}
    for line in parts[0][3:].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            data[key] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        else:
            data[key] = value.strip("'\"")
    return data, parts[1].lstrip("\n")


def render_frontmatter(data: dict) -> str:
    lines = ["---"]
    for key, value in data.items():
        if isinstance(value, (list, tuple)):
            lines.append("%s: [%s]" % (key, ", ".join(str(v) for v in value)))
        else:
            lines.append("%s: %s" % (key, value))
    lines.append("---")
    return "\n".join(lines)


# ─── Bestand lesen ────────────────────────────────────────────────────────


def patterns_root(workspace: str) -> Path:
    return Path(workspace).resolve() / PATTERNS_DIR


def parse_pattern(path) -> dict:
    target = Path(path)
    front, body = parse_frontmatter(target.read_text(encoding="utf-8"))
    evidence = []
    for line in body.splitlines():
        match = EVIDENCE_RE.match(line.strip())
        if match:
            evidence.append({
                "experiment": match.group("experiment"),
                "mutation_type": match.group("mutation_type").strip(),
                "decision": match.group("decision"),
                "delta": float(match.group("delta")),
            })
    return {
        "path": str(target),
        "pattern_id": front.get("id", target.stem.split("__")[0]),
        "frontmatter": front,
        "body": body,
        "evidence": evidence,
        **derive(front, evidence),
    }


def derive(front: dict, evidence: list) -> dict:
    """Abgeleitete Kennzahlen, bei jedem Lesen neu gerechnet.

    Nicht gespeichert, und das ist kein Detail. Die Coverage-Matrix hatte
    genau hier einen Fehler: ``saturated`` wurde gesetzt und nie zurückgenommen,
    eine Kategorie erholte sich nach einem späteren Treffer nie mehr. Ein
    abgeleiteter Wert, der auf der Platte steht, ist ein Wert, der veraltet.

    Bewusst **keine** Trefferquote. Ein Muster kann positiv behaupten
    ("Beispiele nehmen hier") oder negativ ("Prosa-Umformulierungen nicht") —
    im zweiten Fall belegen NEUTRAL-Zeilen das Muster und KEEP-Zeilen
    widersprächen ihm. Eine einzelne Quote hiesse für die beiden Fälle
    Gegenteiliges. Ausgewiesen wird deshalb die Verteilung, und die Deutung
    bleibt beim Leser.
    """
    counts = {d: 0 for d in DECISIONS}
    for row in evidence:
        if row["decision"] in counts:
            counts[row["decision"]] += 1
    measured = [r for r in evidence if r["decision"] in MEASURED]
    best = max((r["delta"] for r in measured), default=None)
    support = len(measured)
    return {
        "support": support,
        "counts": counts,
        "best_delta": best,
        "provisional": support < MIN_SUPPORT,
        "status": front.get("status", "aktiv"),
    }


def read_patterns(workspace: str) -> list:
    root = patterns_root(workspace)
    if not root.is_dir():
        return []
    return [
        parse_pattern(p) for p in sorted(root.glob("P-*.md"))
        if p.name != INDEX_FILE
    ]


def find_pattern(workspace: str, pattern_id: str) -> dict | None:
    for pattern in read_patterns(workspace):
        if pattern["pattern_id"] == pattern_id:
            return pattern
    return None


def next_pattern_id(workspace: str) -> str:
    highest = 0
    for pattern in read_patterns(workspace):
        match = re.fullmatch(r"P-(\d{4})", pattern["pattern_id"])
        if match:
            highest = max(highest, int(match.group(1)))
    return "P-%04d" % (highest + 1)


# ─── Bestand schreiben ────────────────────────────────────────────────────


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:48] or "muster"


def _render(front: dict, observation: str, consequence: str,
            evidence: list) -> str:
    lines = [
        render_frontmatter(front), "",
        "# %s" % front["title"], "",
        "## Beobachtung", observation.strip(), "",
        "## Konsequenz für die nächste Mutation", consequence.strip(), "",
        "## Evidenz",
    ]
    if evidence:
        lines += [
            "- %s | %s | %s | %+.4f" % (
                row["experiment"], row["mutation_type"] or "—",
                row["decision"], row["delta"],
            )
            for row in evidence
        ]
    else:
        lines.append("_Noch kein Beleg. Das Muster gilt als vorläufig._")
    return "\n".join(lines).rstrip("\n") + "\n"


def init_patterns(workspace: str) -> dict:
    root = patterns_root(workspace)
    root.mkdir(parents=True, exist_ok=True)
    created = []
    if not (root / INDEX_FILE).exists():
        build_index(workspace)
        created.append(INDEX_FILE)
    return {"root": str(root), "created": created}


def add_pattern(workspace: str, *, title: str, observation: str,
                consequence: str, category: str = "",
                mutation_types: list | None = None) -> dict:
    """Legt ein Muster an. Ohne Evidenz, die kommt programmatisch dazu."""
    for field, value in (("title", title), ("observation", observation),
                         ("consequence", consequence)):
        if not str(value or "").strip():
            raise ValueError("Pflichtfeld fehlt oder ist leer: %s" % field)

    init_patterns(workspace)
    existing = {p["frontmatter"].get("title", "").casefold()
                for p in read_patterns(workspace)}
    if title.casefold() in existing:
        raise ValueError(
            "Ein Muster mit diesem Titel existiert schon. Ergänze es über "
            "'update', statt ein zweites danebenzustellen — sonst zerfällt "
            "die Evidenz auf zwei Seiten und beide bleiben vorläufig."
        )

    pattern_id = next_pattern_id(workspace)
    front = {
        "id": pattern_id,
        "title": " ".join(title.split()),
        "category": category,
        "mutation_types": mutation_types or [],
        "status": "aktiv",
        "stand": _utc_now()[:10],
    }
    path = patterns_root(workspace) / ("%s__%s.md" % (pattern_id, _slugify(title)))
    path.write_text(_render(front, observation, consequence, []), encoding="utf-8")
    build_index(workspace)
    return {"pattern_id": pattern_id, "path": str(path)}


def add_evidence(workspace: str, pattern_id: str, *, experiment: str,
                 decision: str, delta: float, mutation_type: str = "") -> dict:
    """Hängt eine Evidenzzeile an. Wird vom Orchestrator aufgerufen, nicht vom Agenten.

    Idempotent über die Experiment-ID: ein Resume, das dasselbe Experiment
    erneut verbucht, verdoppelt den Beleg nicht. Ohne diese Sperre wüchse die
    Stützzahl eines Musters durch Wiederholung statt durch Bestätigung.
    """
    if decision not in DECISIONS:
        raise ValueError("Unbekannte Entscheidung %r. Erlaubt: %s"
                         % (decision, ", ".join(DECISIONS)))
    pattern = find_pattern(workspace, pattern_id)
    if pattern is None:
        raise KeyError("Unbekanntes Muster: %s" % pattern_id)

    evidence = [r for r in pattern["evidence"] if r["experiment"] != experiment]
    duplicate = len(evidence) != len(pattern["evidence"])
    evidence.append({
        "experiment": experiment, "mutation_type": mutation_type,
        "decision": decision, "delta": float(delta),
    })
    evidence.sort(key=lambda r: r["experiment"])

    front = dict(pattern["frontmatter"])
    front["stand"] = _utc_now()[:10]
    observation, consequence = _sections(pattern["body"])
    Path(pattern["path"]).write_text(
        _render(front, observation, consequence, evidence), encoding="utf-8"
    )
    build_index(workspace)
    result = parse_pattern(pattern["path"])
    return {
        "pattern_id": pattern_id, "replaced": duplicate,
        "support": result["support"], "counts": result["counts"],
        "provisional": result["provisional"],
    }


def _sections(body: str) -> tuple:
    def grab(name: str) -> str:
        match = re.search(
            r"^## %s\s*\n(.*?)(?=^## |\Z)" % re.escape(name),
            body, re.MULTILINE | re.DOTALL,
        )
        return (match.group(1).strip() if match else "")
    return grab("Beobachtung"), grab("Konsequenz für die nächste Mutation")


def update_pattern(workspace: str, pattern_id: str, *,
                   observation: str | None = None,
                   consequence: str | None = None,
                   status: str | None = None,
                   refuted_by: str = "") -> dict:
    """Verfeinert ein Muster, statt es zu ersetzen.

    ``status: widerlegt`` verlangt ``refuted_by``: welches Experiment dem
    Muster widersprochen hat. Ein Muster stillschweigend abzuräumen wäre
    dasselbe Vergessen, gegen das dieser Bestand gebaut ist — die Seite bleibt
    stehen, damit derselbe Irrtum nicht in drei Runden neu entdeckt wird.
    """
    pattern = find_pattern(workspace, pattern_id)
    if pattern is None:
        raise KeyError("Unbekanntes Muster: %s" % pattern_id)
    if status is not None and status not in STATUSES:
        raise ValueError("Unbekannter Status %r. Erlaubt: %s"
                         % (status, ", ".join(STATUSES)))
    if status == "widerlegt" and not str(refuted_by or "").strip():
        raise ValueError(
            "status=widerlegt ohne refuted_by. Nenne das Experiment, das dem "
            "Muster widersprochen hat."
        )

    old_observation, old_consequence = _sections(pattern["body"])
    front = dict(pattern["frontmatter"])
    if status:
        front["status"] = status
    if refuted_by:
        front["widerlegt_durch"] = refuted_by
    front["stand"] = _utc_now()[:10]
    Path(pattern["path"]).write_text(
        _render(front,
                observation if observation is not None else old_observation,
                consequence if consequence is not None else old_consequence,
                pattern["evidence"]),
        encoding="utf-8",
    )
    build_index(workspace)
    return parse_pattern(pattern["path"])


# ─── Index und Ausgabe ────────────────────────────────────────────────────


INDEX_HEADER = """# Muster des Optimierers

<!-- Erzeugt von patterns.py index. Nicht von Hand editieren. -->

Wie für **diesen** Skill eine gute Änderung aussieht. Optimiererseitig: nichts
hier gehört in die Ziel-SKILL.md.

Vorrangregel: Bevorzuge diese Muster, wenn die aktuelle Evidenz mehrdeutig ist.
Ignoriere sie, wenn die aktuellen Ergebnisse ihnen klar widersprechen.

Nur diese Tabelle liegt permanent im Kontext. Lies eine Seite, wenn ihr Titel
zur aktuellen Frage passt:

    python3 scripts/patterns.py show <workspace> P-0003

`vorläufig` heisst: weniger als zwei gemessene Belege, also noch eine Anekdote.
`widerlegt` heisst: ein späteres Experiment hat dem Muster widersprochen; die
Seite bleibt stehen, damit derselbe Irrtum nicht neu entdeckt wird.
"""


def build_index(workspace: str) -> str:
    root = patterns_root(workspace)
    root.mkdir(parents=True, exist_ok=True)
    patterns = read_patterns(workspace)
    lines = [INDEX_HEADER]
    if not patterns:
        lines.append("\n_Noch keine Muster._\n")
    else:
        lines.append("")
        lines.append("| ID | Muster | Kategorie | Belege | K/R/N | Bestes Delta | Status |")
        lines.append("|---|---|---|---|---|---|---|")
        for p in patterns:
            counts = p["counts"]
            status = p["status"]
            if status == "aktiv" and p["provisional"]:
                status = "vorläufig"
            lines.append("| %s | %s | %s | %d | %d/%d/%d | %s | %s |" % (
                p["pattern_id"], p["frontmatter"].get("title", "—"),
                p["frontmatter"].get("category") or "—", p["support"],
                counts["KEEP"], counts["REVERT"], counts["NEUTRAL"],
                ("%+.4f" % p["best_delta"]) if p["best_delta"] is not None else "—",
                status,
            ))
        lines.append("")
    text = "\n".join(lines).rstrip("\n") + "\n"
    (root / INDEX_FILE).write_text(text, encoding="utf-8")
    return text


def format_index(workspace: str) -> str:
    """Der Block für den Hypothesis-Prompt: nur der Index, nie die Seiten."""
    index = patterns_root(workspace) / INDEX_FILE
    if not index.exists():
        return ""
    if not read_patterns(workspace):
        return ""
    return index.read_text(encoding="utf-8")


def show_pattern(workspace: str, pattern_id: str) -> str:
    pattern = find_pattern(workspace, pattern_id)
    if pattern is None:
        raise KeyError("Unbekanntes Muster: %s" % pattern_id)
    return Path(pattern["path"]).read_text(encoding="utf-8")


def pattern_stats(workspace: str) -> dict:
    patterns = read_patterns(workspace)
    return {
        "total": len(patterns),
        "aktiv": sum(1 for p in patterns if p["status"] == "aktiv"),
        "widerlegt": sum(1 for p in patterns if p["status"] == "widerlegt"),
        "vorlaeufig": sum(
            1 for p in patterns if p["status"] == "aktiv" and p["provisional"]
        ),
        "evidence_rows": sum(len(p["evidence"]) for p in patterns),
        "index_tokens": len(format_index(workspace)) // 3,
    }


# ─── CLI ──────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="patterns.py",
        description="Musterbestand des Optimierers (Meta-Memory).",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Musterbestand im Workspace anlegen")
    init.add_argument("workspace")

    add = sub.add_parser("add", help="Neues Muster anlegen")
    add.add_argument("workspace")
    add.add_argument("--title", required=True)
    add.add_argument("--observation", required=True)
    add.add_argument("--consequence", required=True)
    add.add_argument("--category", default="")
    add.add_argument("--mutation-type", action="append", default=[],
                     dest="mutation_types")
    add.add_argument("--from-json",
                     help="Meta-Agent-Ausgabe mit dem Block patterns")

    ev = sub.add_parser(
        "evidence", help="Evidenzzeile anhängen (programmatisch, aus decision.json)"
    )
    ev.add_argument("workspace")
    ev.add_argument("pattern_id")
    ev.add_argument("--experiment", required=True)
    ev.add_argument("--decision", required=True, choices=list(DECISIONS))
    ev.add_argument("--delta", type=float, required=True)
    ev.add_argument("--mutation-type", default="")

    up = sub.add_parser("update", help="Muster verfeinern oder widerlegen")
    up.add_argument("workspace")
    up.add_argument("pattern_id")
    up.add_argument("--observation")
    up.add_argument("--consequence")
    up.add_argument("--status", choices=list(STATUSES))
    up.add_argument("--refuted-by", default="")

    idx = sub.add_parser("index", help="INDEX.md deterministisch neu erzeugen")
    idx.add_argument("workspace")

    fmt = sub.add_parser("format", help="Indexblock für den Agent-Prompt")
    fmt.add_argument("workspace")

    show = sub.add_parser("show", help="Eine Musterseite im Wortlaut")
    show.add_argument("workspace")
    show.add_argument("pattern_id")

    stats = sub.add_parser("stats", help="Bestandszahlen")
    stats.add_argument("workspace")

    return parser


def _fail(message: str) -> int:
    print(json.dumps({"error": message}, indent=2, ensure_ascii=False),
          file=sys.stderr)
    return 1


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "init":
        print(json.dumps(init_patterns(args.workspace), indent=2,
                         ensure_ascii=False))
        return 0

    if args.command == "add":
        entries = []
        if args.from_json:
            payload = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
            entries = payload.get("patterns") or []
            if not entries:
                return _fail("Kein Block patterns in %s." % args.from_json)
        else:
            entries = [{
                "title": args.title, "observation": args.observation,
                "consequence": args.consequence, "category": args.category,
                "mutation_types": args.mutation_types,
            }]
        created, skipped = [], []
        for entry in entries:
            try:
                created.append(add_pattern(
                    args.workspace,
                    title=entry.get("title", ""),
                    observation=entry.get("observation", ""),
                    consequence=entry.get("consequence", ""),
                    category=entry.get("category", ""),
                    mutation_types=entry.get("mutation_types"),
                ))
            except ValueError as exc:
                skipped.append({"title": entry.get("title"), "reason": str(exc)})
        print(json.dumps({"created": created, "skipped": skipped},
                         indent=2, ensure_ascii=False))
        return 0 if created else 2

    if args.command == "evidence":
        try:
            result = add_evidence(
                args.workspace, args.pattern_id, experiment=args.experiment,
                decision=args.decision, delta=args.delta,
                mutation_type=args.mutation_type,
            )
        except (KeyError, ValueError) as exc:
            return _fail(str(exc))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.command == "update":
        try:
            result = update_pattern(
                args.workspace, args.pattern_id, observation=args.observation,
                consequence=args.consequence, status=args.status,
                refuted_by=args.refuted_by,
            )
        except (KeyError, ValueError) as exc:
            return _fail(str(exc))
        print(json.dumps({
            "pattern_id": result["pattern_id"], "status": result["status"],
            "support": result["support"],
        }, indent=2, ensure_ascii=False))
        return 0

    if args.command == "index":
        build_index(args.workspace)
        print(json.dumps(
            {"index": str(patterns_root(args.workspace) / INDEX_FILE)},
            indent=2, ensure_ascii=False))
        return 0

    if args.command == "format":
        block = format_index(args.workspace)
        if block:
            print(block, end="")
        return 0

    if args.command == "show":
        try:
            print(show_pattern(args.workspace, args.pattern_id), end="")
        except KeyError as exc:
            return _fail(str(exc))
        return 0

    if args.command == "stats":
        print(json.dumps(pattern_stats(args.workspace), indent=2,
                         ensure_ascii=False))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
