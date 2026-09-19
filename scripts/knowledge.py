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
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

__version__ = "2.2.0"


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
    skill_path: str | None = None,
) -> dict:
    """Melde eine Wissenslücke, falls sie neu ist und der Bestand sie nicht deckt.

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

    Mit ``skill_path`` wird zuerst der Wissensbestand durchsucht. Liegt die
    Antwort dort schon, wird **keine** Lücke angelegt: dann fehlt nicht das
    Wissen, sondern der Weg dorthin, und das ist ein SKILL_DEFECT auf den
    Verweis. Ohne diese Prüfung entsteht eine Schleife — der Hypothesis-Agent
    meldet die Lücke, der Librarian findet die Antwort im Bestand, wo sie schon
    war, und ``claim-add`` weist sie als Near-Duplicate ab. Eine Runde
    verbrannt, und die eigentliche Ursache bleibt unerkannt. Betroffen sind vor
    allem Fakten, die beim Wizard eingelegt wurden: die sind nie durch die
    Gap-Queue gegangen, also greift die Dedup-Prüfung über die Frage nicht.

    Rückgabe enthält das Flag ``created``. Ist es ``False``, wurde nichts
    geschrieben und ``status`` sagt, wie der bestehende Eintrag steht, bzw.
    ``covered_by_vault`` markiert den Bestandstreffer. Der
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

    if skill_path:
        coverage = vault_covers(skill_path, question)
        if coverage["covered"]:
            return {
                "created": False,
                "duplicate": False,
                "covered_by_vault": True,
                "gap_id": None,
                "status": None,
                "unresolved": False,
                "coverage": coverage,
            }

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


# ══ Wissensbestand ════════════════════════════════════════════════════════
#
# Ab hier verwaltet dieses Script nicht mehr nur Fragen, sondern Antworten.
# Der Bestand liegt beim Ziel-Skill, nicht im Workspace: Wissen, das der Skill
# braucht, gehört zum Skill und wird mit ihm weitergegeben. Ein Bestand im
# Workspace bliebe beim Optimierer liegen, und der weitergegebene Skill wüsste
# wieder nichts.
#
# Das Format ist eine Teilmenge des SkillSafe-Wissenstresors und bleibt
# formatkompatibel: dieselben ID-Präfixe (C-nnnn Claim, S-nnnn Quelle), dieselbe
# Trennung Quelle/Claim/Index. Ein hier erzeugter Bestand lässt sich später ohne
# Umschreiben in einen echten Tresor einlesen. Übernommen wird das Konzept,
# nicht der Code — SkillSafe bleibt unangetastet und ist keine Abhängigkeit.
#
# Die eiserne Regel dahinter: **kein Claim ohne Quelle.** Ob eine Formulierung
# besser ist, entscheidet die Messung; ob eine Tatsache stimmt, entscheidet die
# Quelle. Ein Eval-Score ist kein Wahrheitskriterium, und eine plausibel
# klingende Erfindung besteht Assertions besser als eine sperrige Wahrheit.

KNOWLEDGE_DIR = "knowledge"
PAGES_DIR = "pages"
SOURCES_FILE = "SOURCES.md"
INDEX_FILE = "INDEX.md"
QUARANTINE_DIR = "quarantine"

REGION_START = "<!-- FORGE_KNOWLEDGE_START -->"
REGION_END = "<!-- FORGE_KNOWLEDGE_END -->"

TRUST_LEVELS = ("T1", "T2", "T3")
# T1 amtliches oder normatives Primärdokument — die Norm selbst
# T2 Hersteller- oder Sekundärquelle — ein Bericht ÜBER etwas anderes
# T3 Web oder unbestätigt
RIGHTS = ("volltext", "verweis")

CLAIM_RE = re.compile(
    r"^-\s+\*\*(?P<id>C-\d{4})\*\*\s+"
    r"\[(?P<source>S-\d{4})(?:\s*\|\s*(?P<fundstelle>[^\]]*))?\]\s*"
    r"(?P<text>\S.*)$"
)
SOURCE_ROW_RE = re.compile(r"^\|\s*(S-\d{4})\s*\|")


def knowledge_root(skill_path: str) -> Path:
    """``<verzeichnis der ziel-SKILL.md>/knowledge``."""
    return Path(skill_path).resolve().parent / KNOWLEDGE_DIR


# ─── Frontmatter ──────────────────────────────────────────────────────────


def parse_frontmatter(text: str) -> tuple:
    """Minimaler Parser für ``key: wert`` und ``key: [a, b]``.

    Keine YAML-Abhängigkeit: ``composite_score.py`` kommt mit der
    Standardbibliothek aus, und ein Wissensbestand, der mit dem Skill
    weitergegeben wird, soll nicht an einem pip-Paket auf der Zielmaschine
    hängen. Der Preis ist ein enger Formatvertrag, und der ist hier erwünscht:
    was der Parser nicht liest, soll auch nicht dastehen.
    """
    if not text.startswith("---"):
        return {}, text
    parts = text.split("\n---", 1)
    if len(parts) != 2:
        return {}, text
    head = parts[0][3:]
    body = parts[1].lstrip("\n")
    data: dict = {}
    for line in head.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            data[key] = [v.strip() for v in inner.split(",") if v.strip()]
        else:
            data[key] = value.strip("'\"")
    return data, body


def render_frontmatter(data: dict) -> str:
    lines = ["---"]
    for key, value in data.items():
        if isinstance(value, (list, tuple)):
            lines.append("%s: [%s]" % (key, ", ".join(str(v) for v in value)))
        else:
            lines.append("%s: %s" % (key, value))
    lines.append("---")
    return "\n".join(lines)


# ─── Seiten und Claims ────────────────────────────────────────────────────


def parse_page(path) -> dict:
    """Frontmatter plus Claims einer Wissensseite."""
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    front, body = parse_frontmatter(text)
    claims = []
    for line in body.splitlines():
        match = CLAIM_RE.match(line.strip())
        if match:
            claims.append({
                "claim_id": match.group("id"),
                "source": match.group("source"),
                "fundstelle": (match.group("fundstelle") or "").strip().strip('"'),
                "text": match.group("text").strip(),
                "page": target.name,
            })
    return {
        "path": str(target),
        "slug": target.stem,
        "frontmatter": front,
        "claims": claims,
    }


def read_pages(skill_path: str) -> list:
    pages_dir = knowledge_root(skill_path) / PAGES_DIR
    if not pages_dir.is_dir():
        return []
    return [parse_page(p) for p in sorted(pages_dir.glob("*.md"))]


def all_claims(skill_path: str) -> list:
    claims = []
    for page in read_pages(skill_path):
        veraltet = set(page["frontmatter"].get("veraltet", []) or [])
        for claim in page["claims"]:
            claim = dict(claim)
            claim["slug"] = page["slug"]
            claim["domain"] = page["frontmatter"].get("domain", "")
            claim["status"] = (
                "veraltet" if claim["claim_id"] in veraltet else "aktiv"
            )
            claims.append(claim)
    return claims


def next_claim_id(skill_path: str) -> str:
    highest = 0
    for claim in all_claims(skill_path):
        highest = max(highest, int(claim["claim_id"].split("-")[1]))
    return "C-%04d" % (highest + 1)


# ─── Quellenregister ──────────────────────────────────────────────────────


SOURCES_HEADER = """# Quellenregister

Jede Quelle dieses Wissensbestands. SHA-256 ist der Hash der Datei unter
*Ablage*; `knowledge.py verify` rechnet nach. Weicht der Hash ab, hat sich die
Quelle geändert, und die davon abhängigen Claims gelten als zu prüfen — sie
werden nicht automatisch aktualisiert, denn was sich inhaltlich geändert hat,
ist keine Rechenaufgabe.

Trust-Stufen, damit die Einordnung nicht bei jeder Aufnahme neu verhandelt
wird: **T1** amtliches oder normatives Primärdokument, also die Norm
beziehungsweise Spezifikation selbst; **T2** Hersteller- oder Sekundärquelle,
also ein Bericht ÜBER etwas anderes; **T3** Web oder unbestätigt.

Rechte bestimmen die Ablage: `volltext` liegt kopiert unter `sources/`,
`verweis` bleibt ein Zeiger auf den Originalpfad. Bei `verweis` kann `verify`
den Hash nur nachrechnen, solange der Pfad erreichbar ist; sonst meldet es
`unpruefbar` — nicht `falsch`.

| ID | Titel | Stand | SHA-256 | Trust | Rechte | Ablage |
|---|---|---|---|---|---|---|
"""


def sources_path(skill_path: str) -> Path:
    return knowledge_root(skill_path) / SOURCES_FILE


def read_sources(skill_path: str) -> list:
    path = sources_path(skill_path)
    if not path.exists():
        return []
    sources = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not SOURCE_ROW_RE.match(line.strip()):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7:
            continue
        sources.append({
            "source_id": cells[0], "title": cells[1], "stand": cells[2],
            "sha256": cells[3], "trust": cells[4], "rights": cells[5],
            "ablage": cells[6],
        })
    return sources


def next_source_id(skill_path: str) -> str:
    highest = 0
    for source in read_sources(skill_path):
        highest = max(highest, int(source["source_id"].split("-")[1]))
    return "S-%04d" % (highest + 1)


def sha256_of(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ─── Gates ────────────────────────────────────────────────────────────────

# (d) Secrets. Gesucht werden **Werte**, keine Wörter. Ein Claim darf das Wort
# "Passwort" enthalten — das ist womöglich genau die Regel, die der Skill
# braucht. Was nicht hinein darf, ist ein echtes Geheimnis, und das erkennt man
# an der Form. Dokumentationsplatzhalter zählen ausdrücklich nicht.
_SECRET_PATTERNS = [
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "privater Schlüssel"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS Access Key"),
    (r"\b(?:sk|pk|rk)-[A-Za-z0-9]{20,}\b", "API-Key mit bekanntem Präfix"),
    (r"\bghp_[A-Za-z0-9]{30,}\b", "GitHub-Token"),
    (r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b", "Slack-Token"),
    (r"(?i)\b(?:bearer|authorization)\s*[:=]\s*[A-Za-z0-9._\-]{20,}", "Bearer-Token"),
    (r"(?i)\b(?:passwor(?:t|d)|secret|api[_-]?key|token)\s*[:=]\s*"
     r"[\"']?(?![<{\[])[^\s\"'<>{}]{8,}", "Zugangsdatum als Wert"),
]
_PLACEHOLDER_RE = re.compile(
    r"(?i)^(?:x{3,}|\.{3,}|\*{3,}|dein[-_ ]?\w*|your[-_ ]?\w*|"
    r"beispiel\w*|example\w*|placeholder|redacted|geheim|changeme)$"
)

# (c) Injection. Eingelesenes Material ist Daten, nie Anweisung. Ein Abschnitt,
# der Imperative an das System richtet, wird nicht aufgenommen.
_INJECTION_PATTERNS = [
    (r"(?i)ignorier\w*\s+(?:alle\s+)?(?:vorherige|bisherige|obige)", "Anweisungsumkehr (de)"),
    (r"(?i)ignore\s+(?:all\s+)?(?:previous|prior|above)", "Anweisungsumkehr (en)"),
    (r"(?i)disregard\s+(?:the\s+)?(?:above|previous|prior)", "Anweisungsumkehr (en)"),
    (r"(?i)\b(?:du bist|you are)\s+(?:jetzt|now)\b", "Rollenübernahme"),
    (r"(?i)\b(?:system[- ]?prompt|systemanweisung)\b", "Verweis auf den Systemprompt"),
    (r"(?i)\b(?:neue|new)\s+(?:anweisung|instruction)en?\b", "neue Anweisung"),
    (r"(?i)\b(?:führe|execute|run)\s+(?:folgende|the following|den folgenden)",
     "Ausführungsaufforderung"),
]


def scan_secrets(text: str) -> list:
    """Treffer der Secret-Muster, Dokumentationsplatzhalter ausgenommen."""
    findings = []
    for pattern, label in _SECRET_PATTERNS:
        for match in re.finditer(pattern, text):
            value = match.group(0)
            tail = re.split(r"[:=]\s*[\"']?", value)[-1].strip("\"' ")
            if _PLACEHOLDER_RE.match(tail):
                continue
            findings.append({"kind": label, "excerpt": value[:40]})
    return findings


def scan_injection(text: str) -> list:
    """Treffer der Injection-Muster."""
    findings = []
    for pattern, label in _INJECTION_PATTERNS:
        match = re.search(pattern, text)
        if match:
            findings.append({"kind": label, "excerpt": match.group(0)[:60]})
    return findings


# (b) Leak. Das grösste Risiko des ganzen Vorhabens: der Loop trägt die
# erwarteten Eval-Antworten als "Wissen" ein. Der val-Score steigt, nichts
# generalisiert, und der Overfitting-Schutz ist unterlaufen.
LEAK_NGRAM = 8


def _words(text: str) -> list:
    return normalise_question(text).split()


def ngrams(text: str, n: int = LEAK_NGRAM) -> set:
    words = _words(text)
    if len(words) < n:
        return set()
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def eval_corpus(evals_path: str, splits=("val", "test")) -> list:
    """Prompts und Assertion-Texte der genannten Splits, als Fliesstext."""
    payload = json.loads(Path(evals_path).read_text(encoding="utf-8"))
    corpus = []
    for item in payload.get("evals", []):
        if splits and item.get("split") not in splits:
            continue
        parts = [str(item.get("prompt", ""))]
        for assertion in item.get("assertions", []) or []:
            parts.append(str(assertion.get("check", "")))
            parts.append(str(assertion.get("expected", "")))
        corpus.append({"id": item.get("id"), "text": " ".join(parts)})
    return corpus


def leak_check(text: str, evals_path: str, n: int = LEAK_NGRAM,
               splits=("val", "test")) -> list:
    """Wörtliche Überschneidungen eines Claims mit val- oder test-Evals.

    Geprüft wird über **alle** genannten Splits, nicht nur über val: ein Claim,
    der eine Testantwort enthält, ist auch dann Leakage, wenn er zufällig aus
    einem Dokument stammt. Die Fenstergrösse ist ein Kompromiss — acht Wörter
    sind lang genug, dass eine gemeinsame Fachwendung nicht anschlägt, und kurz
    genug, dass eine abgeschriebene Antwort auffällt.
    """
    claim_grams = ngrams(text, n)
    if not claim_grams:
        return []
    hits = []
    for entry in eval_corpus(evals_path, splits):
        shared = claim_grams & ngrams(entry["text"], n)
        if shared:
            hits.append({"eval_id": entry["id"], "shared": sorted(shared)[:3]})
    return hits


# (e) Near-Duplicate. Bewusst nicht "Widerspruchserkennung" genannt: eine
# semantische Widerspruchsprüfung ist das hier nicht und könnte es auch nicht
# leisten. Was die Funktion kann, ist zwei Aussagen zu erkennen, die weitgehend
# dieselben Wörter benutzen und trotzdem verschieden sind — der Fall "gleiche
# Entität, andere Zahl". Das ist der häufige Fall beim Nachtragen aktualisierter
# Fakten, und er darf nicht still überschrieben werden.
NEAR_DUPLICATE_RATIO = 0.6


def near_duplicates(text: str, existing: list,
                    ratio: float = NEAR_DUPLICATE_RATIO) -> list:
    new_words = set(_words(text))
    if not new_words:
        return []
    hits = []
    for claim in existing:
        if claim.get("status") == "veraltet":
            continue
        old_words = set(_words(claim["text"]))
        if not old_words:
            continue
        overlap = len(new_words & old_words) / len(new_words | old_words)
        if overlap >= ratio and _words(text) != _words(claim["text"]):
            hits.append({
                "claim_id": claim["claim_id"],
                "overlap": round(overlap, 3),
                "text": claim["text"][:120],
            })
    return sorted(hits, key=lambda h: -h["overlap"])


# ─── Bestand anlegen und befüllen ─────────────────────────────────────────


def init_knowledge(skill_path: str) -> dict:
    """Legt den Wissensbaum neben der Ziel-SKILL.md an. Idempotent."""
    target = Path(skill_path)
    if not target.is_file():
        raise FileNotFoundError("Keine Ziel-SKILL.md unter %s" % skill_path)
    root = knowledge_root(skill_path)
    (root / PAGES_DIR).mkdir(parents=True, exist_ok=True)
    created = []
    if not sources_path(skill_path).exists():
        sources_path(skill_path).write_text(SOURCES_HEADER, encoding="utf-8")
        created.append(SOURCES_FILE)
    index = root / INDEX_FILE
    if not index.exists():
        build_index(skill_path)
        created.append(INDEX_FILE)
    return {"root": str(root), "created": created}


def add_source(skill_path: str, file_path: str, *, title: str, trust: str,
               rights: str, stand: str | None = None,
               source_id: str | None = None) -> dict:
    """Nimmt eine Quelle ins Register auf, mit Hash und Rechten.

    Bei ``rights=volltext`` wird die Datei in den Bestand kopiert, damit die
    Provenienz auch nach der Weitergabe des Skills nachprüfbar bleibt. Bei
    ``verweis`` bleibt nur der Zeiger: der Hash belegt, welchen Stand die Claims
    gesehen haben, auch wenn die Datei später nicht mehr erreichbar ist.
    """
    if trust not in TRUST_LEVELS:
        raise ValueError("Unbekannte Trust-Stufe %r. Erlaubt: %s"
                         % (trust, ", ".join(TRUST_LEVELS)))
    if rights not in RIGHTS:
        raise ValueError("Unbekannte Rechteangabe %r. Erlaubt: %s"
                         % (rights, ", ".join(RIGHTS)))
    origin = Path(file_path)
    if not origin.is_file():
        raise FileNotFoundError("Quelle nicht gefunden: %s" % file_path)

    init_knowledge(skill_path)
    digest = sha256_of(origin)
    for existing in read_sources(skill_path):
        if existing["sha256"] == digest:
            return {"created": False, "duplicate": True,
                    "source_id": existing["source_id"],
                    "reason": "identischer Hash bereits im Register"}

    sid = source_id or next_source_id(skill_path)
    if rights == "volltext":
        store = knowledge_root(skill_path) / "sources"
        store.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", origin.stem.lower()).strip("-")[:40]
        ablage_path = store / ("%s__%s%s" % (sid, slug or "quelle", origin.suffix))
        ablage_path.write_bytes(origin.read_bytes())
        ablage = "%s/sources/%s" % (KNOWLEDGE_DIR, ablage_path.name)
    else:
        ablage = str(origin)

    row = "| %s | %s | %s | %s | %s | %s | %s |\n" % (
        sid, title.replace("|", "/"), stand or _utc_now()[:10],
        digest, trust, rights, ablage,
    )
    with open(sources_path(skill_path), "a", encoding="utf-8") as handle:
        handle.write(row)
    return {"created": True, "duplicate": False, "source_id": sid,
            "sha256": digest, "ablage": ablage, "trust": trust,
            "rights": rights}


def add_claims(skill_path: str, page_slug: str, claims: list, *,
               title: str | None = None, domain: str = "",
               stichworte: list | None = None, confidence: str = "mittel",
               evals_path: str | None = None,
               supersedes: list | None = None,
               allow_near_duplicate: bool = False) -> dict:
    """Schreibt Claims auf eine Seite — erst nachdem alle Gates bestanden sind.

    Kein Claim ohne Quelle, und keiner an den Gates vorbei. Die Prüfungen laufen
    hier in Python und nicht als Punkt auf einer Prompt-Checkliste: einen
    Agenten, der eine Regel nicht befolgt hat, per Prompt prüfen zu lassen, ob er
    sie befolgt hat, ist zirkulär.
    """
    init_knowledge(skill_path)
    known = {s["source_id"] for s in read_sources(skill_path)}
    existing = all_claims(skill_path)
    rejected, accepted = [], []
    next_number = int(next_claim_id(skill_path).split("-")[1])

    for raw in claims:
        text = " ".join(str(raw.get("text", "")).split())
        source = str(raw.get("source", "")).strip()
        reasons = []

        if not text:
            reasons.append({"gate": "form", "detail": "leerer Claim-Text"})
        # (a) Provenienz
        if not source:
            reasons.append({"gate": "provenienz",
                            "detail": "kein Quellenverweis"})
        elif source not in known:
            reasons.append({"gate": "provenienz",
                            "detail": "Quelle %s steht nicht im Register" % source})
        if not str(raw.get("fundstelle", "")).strip():
            reasons.append({"gate": "provenienz",
                            "detail": "keine Fundstelle in der Quelle"})
        # (b) Leak
        if evals_path and text:
            hits = leak_check(text, evals_path)
            if hits:
                reasons.append({"gate": "leak", "detail": hits})
        # (c) Injection
        for hit in scan_injection(text):
            reasons.append({"gate": "injection", "detail": hit})
        # (d) Secrets
        for hit in scan_secrets(text):
            reasons.append({"gate": "secret", "detail": hit})
        # (e) Near-Duplicate
        if text and not allow_near_duplicate:
            dupes = near_duplicates(text, existing)
            if dupes:
                reasons.append({"gate": "near_duplicate", "detail": dupes})

        if reasons:
            rejected.append({"text": text[:160], "source": source,
                             "reasons": reasons})
            continue

        claim_id = "C-%04d" % next_number
        next_number += 1
        entry = {"claim_id": claim_id, "source": source,
                 "fundstelle": str(raw.get("fundstelle", "")).strip(),
                 "text": text}
        accepted.append(entry)
        existing.append(dict(entry, status="aktiv"))

    if not accepted:
        return {"written": 0, "accepted": [], "rejected": rejected,
                "page": None}

    root = knowledge_root(skill_path)
    page_path = root / PAGES_DIR / ("%s.md" % page_slug)
    if page_path.exists():
        page = parse_page(page_path)
        front = dict(page["frontmatter"])
        body = page_path.read_text(encoding="utf-8").split("\n---", 1)[1]
        body = body.lstrip("\n")
    else:
        front = {
            "type": "wissen",
            "title": title or page_slug.replace("-", " ").title(),
            "domain": domain,
            "status": "aktiv",
            "confidence": confidence,
            "stichworte": stichworte or [],
            "sources": [],
        }
        body = "# %s\n\n## Kurzfassung\n%s\n\n## Claims\n" % (
            front["title"],
            "Belegte Aussagen zu diesem Thema. Ergänzt vom Skill Forge Loop.",
        )

    used = sorted({c["source"] for c in accepted} | set(front.get("sources", [])))
    front["sources"] = used
    front["stand"] = _utc_now()[:10]
    if stichworte:
        merged = list(dict.fromkeys(list(front.get("stichworte", [])) + stichworte))
        front["stichworte"] = merged
    if supersedes:
        front["veraltet"] = sorted(
            set(front.get("veraltet", []) or []) | set(supersedes)
        )

    lines = [
        "- **%s** [%s | \"%s\"] %s" % (
            c["claim_id"], c["source"], c["fundstelle"], c["text"]
        )
        for c in accepted
    ]
    body = body.rstrip("\n") + "\n" + "\n".join(lines) + "\n"
    page_path.write_text(
        render_frontmatter(front) + "\n\n" + body, encoding="utf-8"
    )
    build_index(skill_path)
    return {"written": len(accepted), "accepted": accepted,
            "rejected": rejected, "page": str(page_path)}


# ─── Index, Prüfung, Pflege ───────────────────────────────────────────────


INDEX_HEADER = """# Wissensbestand — Navigationsmap

<!-- Erzeugt von knowledge.py index. Nicht von Hand editieren. -->

Zuerst hier nachsehen, welche Seite zum Thema passt, dann nur diese Seite
lesen. Steht das Thema nicht in dieser Tabelle, ist es **nicht im Bestand**:
dann sag das, statt aus eigenem Wissen zu ergänzen.

Diese Datei liegt bei jedem Lauf im Kontext und zählt deshalb gegen das
strenge Token-Budget. Die Seiten selbst werden nur bei Bedarf gelesen und
zählen gegen das Wissensbudget.
"""


def build_index(skill_path: str) -> str:
    """Erzeugt ``knowledge/INDEX.md`` deterministisch aus den Seiten."""
    root = knowledge_root(skill_path)
    root.mkdir(parents=True, exist_ok=True)
    pages = read_pages(skill_path)
    lines = [INDEX_HEADER]
    if not pages:
        lines.append("\n_Der Bestand ist leer._\n")
    else:
        by_domain: dict = {}
        for page in pages:
            by_domain.setdefault(
                page["frontmatter"].get("domain") or "ohne Domäne", []
            ).append(page)
        for domain in sorted(by_domain):
            lines.append("\n## %s\n" % domain)
            lines.append("| Seite | Stichworte | Claims | Stand | Status |")
            lines.append("|---|---|---|---|---|")
            for page in sorted(by_domain[domain], key=lambda p: p["slug"]):
                front = page["frontmatter"]
                stichworte = ", ".join(front.get("stichworte", []) or []) or "—"
                lines.append("| [%s](%s/%s.md) | %s | %d | %s | %s |" % (
                    front.get("title", page["slug"]), PAGES_DIR, page["slug"],
                    stichworte, len(page["claims"]),
                    front.get("stand", "—"), front.get("status", "aktiv"),
                ))
        lines.append("")
    text = "\n".join(lines).rstrip("\n") + "\n"
    (root / INDEX_FILE).write_text(text, encoding="utf-8")
    return text


def verify_knowledge(skill_path: str) -> dict:
    """Struktur, Provenienz und Quellendrift. Fail closed bei echten Fehlern.

    Drei Abstufungen, und die Unterscheidung ist der eigentliche Inhalt dieser
    Funktion:

    * **errors** — der Bestand ist nicht vertrauenswürdig: ein Claim ohne
      registrierte Quelle, eine doppelte ID, ein Hash, der nicht mehr stimmt.
      Exit 1.
    * **warnings** — etwas ist nicht nachprüfbar, aber nicht falsch: eine
      `verweis`-Quelle, deren Pfad auf dieser Maschine nicht existiert. Der
      Claim wurde bei der Aufnahme gegen sie geprüft; dass der Rechner ein
      anderer ist, macht ihn nicht ungültig. Fail-closed an dieser Stelle machte
      jeden weitergegebenen Skill sofort rot.
    * **stale** — die Quelle ist erreichbar und hat sich geändert. Das ist ein
      Fehler, denn die Claims beschreiben jetzt einen Stand, den es nicht mehr
      gibt. Automatisch aktualisiert wird nichts: was sich inhaltlich geändert
      hat, ist keine Rechenaufgabe.
    """
    root = knowledge_root(skill_path)
    result = {"root": str(root), "errors": [], "warnings": [], "stale": [],
              "claims": 0, "pages": 0, "sources": 0}
    if not root.is_dir():
        result["errors"].append({"kind": "kein_bestand",
                                 "detail": "%s existiert nicht" % root})
        return result

    sources = read_sources(skill_path)
    result["sources"] = len(sources)
    by_id = {}
    for source in sources:
        if source["source_id"] in by_id:
            result["errors"].append({"kind": "doppelte_quellen_id",
                                     "detail": source["source_id"]})
        by_id[source["source_id"]] = source

    for source in sources:
        ablage = Path(source["ablage"])
        if not ablage.is_absolute():
            ablage = root.parent / ablage
        if not ablage.is_file():
            result["warnings"].append({
                "kind": "quelle_unpruefbar", "source_id": source["source_id"],
                "detail": "Ablage nicht erreichbar: %s" % source["ablage"],
            })
            continue
        if sha256_of(ablage) != source["sha256"]:
            result["stale"].append({
                "kind": "quelle_geaendert", "source_id": source["source_id"],
                "detail": "SHA-256 weicht vom Register ab",
            })

    pages = read_pages(skill_path)
    result["pages"] = len(pages)
    seen_claims = {}
    stale_sources = {e["source_id"] for e in result["stale"]}
    for page in pages:
        veraltet = set(page["frontmatter"].get("veraltet", []) or [])
        for claim in page["claims"]:
            result["claims"] += 1
            cid = claim["claim_id"]
            if cid in seen_claims:
                result["errors"].append({
                    "kind": "doppelte_claim_id", "claim_id": cid,
                    "detail": "auch in %s" % seen_claims[cid],
                })
            seen_claims[cid] = page["slug"]
            if claim["source"] not in by_id:
                result["errors"].append({
                    "kind": "claim_ohne_quelle", "claim_id": cid,
                    "detail": "Quelle %s steht nicht im Register" % claim["source"],
                })
            if not claim["fundstelle"]:
                result["errors"].append({
                    "kind": "claim_ohne_fundstelle", "claim_id": cid,
                    "detail": "keine Fundstelle angegeben",
                })
            if claim["source"] in stale_sources and cid not in veraltet:
                result["stale"].append({
                    "kind": "claim_zu_pruefen", "claim_id": cid,
                    "detail": "Quelle %s hat sich geändert" % claim["source"],
                })
        for cid in veraltet:
            if cid not in [c["claim_id"] for c in page["claims"]]:
                result["warnings"].append({
                    "kind": "veraltet_verweist_ins_leere", "claim_id": cid,
                    "detail": "auf Seite %s nicht vorhanden" % page["slug"],
                })

    skill_text = Path(skill_path).read_text(encoding="utf-8")
    if result["claims"] and REGION_START not in skill_text:
        result["warnings"].append({
            "kind": "kein_verweis",
            "detail": "Bestand vorhanden, aber die SKILL.md hat keine "
                      "FORGE_KNOWLEDGE-Region — der Agent findet ihn nicht",
        })
    result["ok"] = not result["errors"] and not result["stale"]
    return result


def knowledge_stats(skill_path: str, budget: int | None = None,
                    chars_per_token: int = 3) -> dict:
    """Grösse des Bestands, getrennt nach Index und Seiten.

    Zwei Budgets statt einem, und die Trennung folgt der Ladelogik: ``INDEX.md``
    liegt bei jedem Lauf im Kontext und gehört deshalb ins strenge
    ``token_budget``; die Seiten werden nur gelesen, wenn der Index auf sie
    zeigt, und zählen gegen das weite ``knowledge_budget``. Mit einem einzigen
    Budget schlüge ``artifact-stats`` nach wenigen Claims an und zwänge den
    Orchestrator in ``forced_category: efficiency`` — der Loop finge also an,
    das gerade erworbene Wissen wieder wegzukürzen.
    """
    root = knowledge_root(skill_path)
    index_chars = 0
    index = root / INDEX_FILE
    if index.is_file():
        index_chars = len(index.read_text(encoding="utf-8"))
    page_chars = 0
    for page in sorted((root / PAGES_DIR).glob("*.md")) if (root / PAGES_DIR).is_dir() else []:
        page_chars += len(page.read_text(encoding="utf-8"))
    divisor = max(chars_per_token, 1)
    result = {
        "index_tokens": index_chars // divisor,
        "page_tokens": page_chars // divisor,
        "claims": len(all_claims(skill_path)),
        "pages": len(read_pages(skill_path)),
        "sources": len(read_sources(skill_path)),
        "budget": budget,
    }
    if budget is not None:
        result["over_budget"] = result["page_tokens"] > budget
        result["headroom"] = budget - result["page_tokens"]
    return result


# ─── Retrieval: liegt die Antwort schon im Bestand? ───────────────────────

# Deterministische Lexik-Suche, kein Embedding. Für Bestände dieser Grösse
# reicht das, und es hat den entscheidenden Vorteil, nachvollziehbar zu sein:
# wer wissen will, warum ein Claim als Treffer galt, sieht die geteilten Wörter.

_STOPWORDS = {
    "aber", "alle", "allem", "allen", "aller", "alles", "als", "also", "andere",
    "auch", "auf", "aus", "bei", "beim", "bis", "dann", "das", "dass", "dem",
    "den", "der", "des", "die", "dies", "diese", "diesem", "diesen", "dieser",
    "dieses", "doch", "dort", "durch", "ein", "eine", "einem", "einen", "einer",
    "eines", "für", "gegen", "hat", "hier", "ich", "ihr", "immer", "ist", "kann",
    "man", "mit", "muss", "nach", "nicht", "noch", "nur", "oder", "ohne", "sich",
    "sie", "sind", "soll", "über", "und", "unter", "vom", "von", "vor", "was",
    "wenn", "wer", "werden", "wie", "wird", "wo", "zum", "zur",
    "and", "are", "for", "from", "has", "its", "not", "the", "that", "this",
    "was", "were", "what", "when", "which", "with",
    # Fragewörter, die in fast jeder Wissensfrage stehen und nichts trennen
    "welche", "welchem", "welchen", "welcher", "welches", "wann", "warum",
    "wieviel", "wieviele", "gilt", "gelten",
}

# Anteil der Inhaltswörter einer Frage, die in einem Claim vorkommen müssen,
# damit die Frage als beantwortet gilt. Bewusst hoch: siehe covered_by_vault.
VAULT_COVERAGE_THRESHOLD = 0.6


def content_words(text: str) -> set:
    """Inhaltswörter: normalisiert, ohne Stoppwörter, ab vier Zeichen."""
    return {
        w for w in normalise_question(text).split()
        if len(w) >= 4 and w not in _STOPWORDS
    }


def search_vault(skill_path: str, query: str, limit: int = 5) -> list:
    """Claims, die zur Frage passen, absteigend nach Deckungsgrad.

    Der Score ist der Anteil der Inhaltswörter der **Frage**, die im
    Suchraum eines Claims vorkommen — nicht Jaccard. Ein langer Claim soll
    nicht dafür bestraft werden, dass er mehr sagt als die Frage fragt.

    Durchsucht werden Claim-Text, Fundstelle, Seitentitel und Stichworte: die
    Frage nennt oft das Thema ("Belegstil") und der Claim die Sache
    ("Kurzbeleg"), und die Brücke dazwischen ist die Seite.
    """
    wanted = content_words(query)
    if not wanted:
        return []
    pages = {p["slug"]: p for p in read_pages(skill_path)}
    hits = []
    for claim in all_claims(skill_path):
        if claim.get("status") == "veraltet":
            continue
        page = pages.get(claim["slug"], {})
        front = page.get("frontmatter", {})
        haystack = " ".join([
            claim["text"], claim.get("fundstelle", ""), claim["slug"],
            str(front.get("title", "")),
            " ".join(front.get("stichworte", []) or []),
            str(front.get("domain", "")),
        ])
        shared = wanted & content_words(haystack)
        if not shared:
            continue
        hits.append({
            "claim_id": claim["claim_id"],
            "slug": claim["slug"],
            "source": claim["source"],
            "score": round(len(shared) / len(wanted), 3),
            "shared": sorted(shared),
            "text": claim["text"][:160],
        })
    hits.sort(key=lambda h: (-h["score"], h["claim_id"]))
    return hits[:limit]


def vault_covers(skill_path: str, query: str,
                 threshold: float = VAULT_COVERAGE_THRESHOLD) -> dict:
    """Prüft, ob der Bestand die Frage schon beantwortet.

    Die Schwelle ist bewusst hoch, und die Asymmetrie hat einen Grund. Ein
    falsches "gedeckt" heisst: die Lücke wird nie gemeldet, die fehlende
    Tatsache nie beschafft — ein dauerhafter blinder Fleck. Ein falsches
    "nicht gedeckt" kostet eine Runde, in der der Librarian die Antwort im
    Bestand findet oder ``claim-add`` sie als Near-Duplicate abweist. Der
    zweite Fehler ist erholbar, der erste nicht.

    Deshalb ist das hier auch nur die **mechanische Rückfallebene**. Die
    eigentliche Unterscheidung trifft der Hypothesis-Agent, der den Bestands-
    index in seinem Kontext sieht.
    """
    hits = search_vault(skill_path, query, limit=5)
    best = hits[0]["score"] if hits else 0.0
    return {
        "covered": best >= threshold,
        "best_score": best,
        "threshold": threshold,
        "candidates": hits,
    }


# ─── Nutzungsverfolgung ───────────────────────────────────────────────────

_CLAIM_REF = re.compile(r"\bC-\d{4}\b")


def _page_slugs(skill_path: str) -> list:
    return [p["slug"] for p in read_pages(skill_path)]


def scan_transcripts(skill_path: str, experiment_dir: str) -> dict:
    """Welcher Run welche Claims und Seiten gelesen hat.

    Warum das nötig ist: unsere train-Runs lesen den Bestand. Besteht ein
    train-Eval, weil der Bestand die Tatsache geliefert hat, sieht der
    Hypothesis-Agent einen Erfolg, den der Skill nicht verursacht hat — und
    leitet daraus ein ``success_pattern`` ab, das die Schutzliste des Mutators
    füllt. Umgekehrt: scheitert ein Eval, obwohl der passende Claim gelesen
    wurde, fehlt nicht das Wissen, sondern der Weg dorthin. Das ist ein
    SKILL_DEFECT auf den Verweis, keine Wissenslücke.

    Ohne diese Zuordnung lassen sich beide Fälle nicht von ihren Gegenstücken
    unterscheiden, und die Klassifikation in ``agents/hypothesis.md`` rät.

    Gesucht wird nach Claim-IDs und Seiten-Slugs im Text der Transcripts. Das
    ist eine Untergrenze, keine exakte Messung: ein Agent, der eine Seite liest
    und nichts davon zitiert, taucht nicht auf. Für die beiden Fragen oben
    reicht es, und es kostet nichts.
    """
    exp_path = Path(experiment_dir)
    if not exp_path.is_dir():
        raise FileNotFoundError("Kein Experiment-Verzeichnis: %s" % experiment_dir)
    slugs = _page_slugs(skill_path)
    by_run: dict = {}
    for path in sorted(exp_path.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        parts = path.relative_to(exp_path).parts
        side = next((p for p in reversed(parts) if p in ("with_mutation", "baseline")), None)
        if side is None:
            continue
        marker = len(parts) - 1 - list(reversed(parts)).index(side)
        head = list(parts[:marker])
        if head and head[0] == "runs":
            head = head[1:]
        eval_id = "/".join(head) or "eval"

        claims = set(_CLAIM_REF.findall(text))
        pages = {s for s in slugs if s and s in text}
        if not claims and not pages:
            continue
        key = "%s|%s" % (eval_id, side)
        entry = by_run.setdefault(
            key, {"eval": eval_id, "side": side, "claims": set(), "pages": set()}
        )
        entry["claims"] |= claims
        entry["pages"] |= pages

    runs = []
    counts: dict = {}
    for entry in sorted(by_run.values(), key=lambda e: (e["eval"], e["side"])):
        for cid in entry["claims"]:
            counts[cid] = counts.get(cid, 0) + 1
        runs.append({
            "eval": entry["eval"], "side": entry["side"],
            "claims": sorted(entry["claims"]), "pages": sorted(entry["pages"]),
        })
    known = {c["claim_id"] for c in all_claims(skill_path)}
    return {
        "runs": runs,
        "claims_used": counts,
        "claims_unknown": sorted(set(counts) - known),
        "runs_with_vault_access": len(runs),
    }


def update_usage(usage_path: str, skill_path: str, experiment_dir: str,
                 experiment_id: str) -> dict:
    """Schreibt die Nutzung eines Experiments fort und summiert über den Lauf.

    ``experiments_since_use`` je Claim ist die Zahl, aus der später ein
    Prune-Vorschlag wird: ein Claim, der über viele Experimente nie gelesen
    wurde, belegt Budget, ohne etwas zu tun. Gelöscht wird deswegen nichts —
    der Vorschlag gehört in den Report, die Entscheidung zum Menschen.
    """
    scan = scan_transcripts(skill_path, experiment_dir)
    path = Path(usage_path)
    if path.exists():
        usage = json.loads(path.read_text(encoding="utf-8"))
    else:
        usage = {"experiments": [], "totals": {}}

    usage["experiments"] = [
        e for e in usage["experiments"] if e.get("experiment") != experiment_id
    ]
    usage["experiments"].append({
        "experiment": experiment_id,
        "runs": scan["runs"],
        "claims_used": scan["claims_used"],
        "timestamp": _utc_now(),
    })
    usage["experiments"].sort(key=lambda e: e["experiment"])

    totals: dict = {}
    seen_experiments = [e["experiment"] for e in usage["experiments"]]
    for entry in usage["experiments"]:
        for cid, count in entry["claims_used"].items():
            row = totals.setdefault(cid, {"uses": 0, "last_experiment": None})
            row["uses"] += count
            row["last_experiment"] = entry["experiment"]
    for claim in all_claims(skill_path):
        row = totals.setdefault(
            claim["claim_id"], {"uses": 0, "last_experiment": None}
        )
        if row["last_experiment"] is None:
            row["experiments_since_use"] = len(seen_experiments)
        else:
            after = seen_experiments[seen_experiments.index(row["last_experiment"]) + 1:]
            row["experiments_since_use"] = len(after)
    usage["totals"] = dict(sorted(totals.items()))
    usage["never_used"] = sorted(c for c, r in totals.items() if r["uses"] == 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(usage, indent=2, ensure_ascii=False), encoding="utf-8")
    return usage


# Ab wie vielen Experimenten ohne einen einzigen Lesezugriff ein Claim als
# Vorschlag im Report auftaucht. Bewusst hoch: ein Bestand wird für den Fall
# gepflegt, der selten eintritt, und genau dann ist er wertvoll.
STALE_EXPERIMENTS = 20


def prune_suggestions(usage_path: str, skill_path: str,
                      stale_after: int = STALE_EXPERIMENTS) -> dict:
    """Claims, die über viele Experimente nie gelesen wurden.

    **Ein Vorschlag, keine Löschung.** Der Loop entfernt im Auto-Modus keinen
    Claim, und zwar aus einem asymmetrischen Grund: ein zu Unrecht behaltener
    Claim kostet ein paar Token im Bestandsbudget, das ohnehin weit bemessen
    ist; ein zu Unrecht gelöschter kostet die Quelle, die Fundstelle und die
    Arbeit, die in seiner Beschaffung steckte — und er fehlt genau dann, wenn
    der seltene Fall eintritt, für den er aufgenommen wurde.

    Nichtnutzung ist ausserdem ein schwaches Signal. Sie kann heissen: der
    Claim ist überflüssig. Sie kann genauso heissen: die Evals decken sein
    Thema nicht ab, oder der Index findet ihn nicht. Die beiden letzten Fälle
    behebt man nicht durch Löschen, und deshalb nennt die Ausgabe sie mit.
    """
    path = Path(usage_path)
    if not path.exists():
        return {"suggestions": [], "experiments": 0, "stale_after": stale_after,
                "reason": "keine Nutzungsdaten"}
    usage = json.loads(path.read_text(encoding="utf-8"))
    seen = len(usage.get("experiments", []))
    totals = usage.get("totals", {})
    claims = {c["claim_id"]: c for c in all_claims(skill_path)}

    suggestions = []
    for claim_id, row in sorted(totals.items()):
        if row.get("uses", 0) > 0:
            continue
        if row.get("experiments_since_use", 0) < stale_after:
            continue
        claim = claims.get(claim_id)
        if claim is None or claim.get("status") == "veraltet":
            continue
        suggestions.append({
            "claim_id": claim_id,
            "slug": claim["slug"],
            "source": claim["source"],
            "experiments_since_use": row["experiments_since_use"],
            "text": claim["text"][:140],
        })
    return {
        "suggestions": suggestions,
        "experiments": seen,
        "stale_after": stale_after,
        "reason": "" if seen >= stale_after else
                  "zu wenige Experimente für eine Aussage",
    }


PRUNE_HEADER = (
    "Nie gelesene Claims. Das ist ein Vorschlag an den Menschen, keine "
    "Löschliste: Nichtnutzung kann heissen, dass der Claim überflüssig ist — "
    "oder dass die Evals sein Thema nicht abdecken, oder dass der Index ihn "
    "nicht findet. Die letzten beiden Fälle behebt Löschen nicht."
)


def format_prune(usage_path: str, skill_path: str,
                 stale_after: int = STALE_EXPERIMENTS) -> str:
    result = prune_suggestions(usage_path, skill_path, stale_after)
    if not result["suggestions"]:
        return ""
    lines = [PRUNE_HEADER, "",
             "Stand nach %d Experimenten, Schwelle %d:"
             % (result["experiments"], result["stale_after"]), ""]
    for entry in result["suggestions"]:
        lines.append("- **%s** (%s, Quelle %s, seit %d Experimenten ungelesen): %s" % (
            entry["claim_id"], entry["slug"], entry["source"],
            entry["experiments_since_use"], _flatten(entry["text"]),
        ))
    lines += ["", "Entfernen heisst: den Claim aus der Seite streichen und "
                  "`knowledge.py index` neu laufen lassen. Im Zweifel stehen "
                  "lassen — der Bestand wird für den seltenen Fall gepflegt."]
    return "\n".join(lines).rstrip() + "\n"


def format_usage(usage_path: str, experiment_id: str | None = None) -> str:
    """Block für den Hypothesis-Agenten.

    Die Kopfzeile ist die Anweisung, nicht die Tabelle. Ohne sie ist das eine
    Statistik, mit ihr die Regel, nach der Erfolge und Fehlschläge zu lesen
    sind.
    """
    path = Path(usage_path)
    if not path.exists():
        return ""
    usage = json.loads(path.read_text(encoding="utf-8"))
    entries = usage.get("experiments", [])
    if experiment_id:
        entries = [e for e in entries if e["experiment"] == experiment_id]
    entries = entries[-1:] if entries else []
    if not entries or not entries[0]["runs"]:
        return ""
    lines = [
        "Bestandsnutzung im letzten Experiment. Zwei Regeln beim Lesen der "
        "Ergebnisse:",
        "",
        "1. Ein bestandener train-Eval, dessen Run Claims gelesen hat, belegt "
        "NICHT, dass der Skill gut ist — die Tatsache kam womöglich aus dem "
        "Bestand. Solche Runs taugen nicht als success_pattern.",
        "2. Ein gescheiterter Eval, dessen Run den passenden Claim gelesen hat, "
        "ist KEINE Wissenslücke. Das Wissen war da und hat nicht getragen: "
        "SKILL_DEFECT auf den Verweis.",
        "",
    ]
    for run in entries[0]["runs"]:
        lines.append("- %s [%s]: Claims %s | Seiten %s" % (
            run["eval"], run["side"],
            ", ".join(run["claims"]) or "—",
            ", ".join(run["pages"]) or "—",
        ))
    never = usage.get("never_used") or []
    if never:
        lines.append("")
        lines.append("Nie gelesen: %s" % ", ".join(never))
    return "\n".join(lines).rstrip() + "\n"


# ─── CLI ──────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="knowledge.py",
        description="Wissenslücken und Wissensbestand für Skill Forge.",
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
    append.add_argument(
        "--skill",
        help="Pfad zur Ziel-SKILL.md. Prüft den Bestand, bevor eine Lücke "
             "angelegt wird. Ohne die Angabe entfällt die Prüfung",
    )

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

    # ── Wissensbestand ──

    init = sub.add_parser("init", help="Wissensbaum neben der Ziel-SKILL.md anlegen")
    init.add_argument("skill_path", help="Pfad zur Ziel-SKILL.md")

    src = sub.add_parser("source-add", help="Quelle ins Register aufnehmen")
    src.add_argument("skill_path")
    src.add_argument("file_path", help="Die aufzunehmende Datei")
    src.add_argument("--title", required=True)
    src.add_argument("--trust", required=True, choices=list(TRUST_LEVELS))
    src.add_argument("--rights", required=True, choices=list(RIGHTS))
    src.add_argument("--stand")

    claim = sub.add_parser(
        "claim-add", help="Claims auf eine Seite schreiben, nach allen Gates"
    )
    claim.add_argument("skill_path")
    claim.add_argument("--page", required=True, help="Slug der Wissensseite")
    claim.add_argument(
        "--from-json", required=True,
        help="Librarian-Ausgabe mit dem Block claims",
    )
    claim.add_argument("--title")
    claim.add_argument("--domain", default="")
    claim.add_argument("--stichwort", action="append", default=[], dest="stichworte")
    claim.add_argument(
        "--evals", help="evals.json des Workspace; ohne sie entfällt der Leak-Check",
    )
    claim.add_argument("--supersedes", action="append", default=[])
    claim.add_argument(
        "--allow-near-duplicate", action="store_true",
        help="Near-Duplicate-Sperre übergehen; nur mit --supersedes sinnvoll",
    )

    verify = sub.add_parser("verify", help="Struktur, Provenienz, Quellendrift")
    verify.add_argument("skill_path")

    index = sub.add_parser("index", help="INDEX.md deterministisch neu erzeugen")
    index.add_argument("skill_path")

    kstats = sub.add_parser("stats", help="Grösse des Bestands, Index getrennt")
    kstats.add_argument("skill_path")
    kstats.add_argument("--budget", type=int)
    kstats.add_argument("--chars-per-token", type=int, default=3)

    leak = sub.add_parser(
        "leak-check", help="Bestand gegen val- und test-Evals prüfen"
    )
    leak.add_argument("skill_path")
    leak.add_argument("--evals", required=True)

    search = sub.add_parser(
        "search", help="Liegt die Antwort auf eine Frage schon im Bestand?"
    )
    search.add_argument("skill_path")
    search.add_argument("query", help="Die Frage im Wortlaut")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--threshold", type=float,
                        default=VAULT_COVERAGE_THRESHOLD)

    usage = sub.add_parser(
        "usage-update",
        help="Aus den Transcripts erfassen, welcher Run welche Claims las",
    )
    usage.add_argument("usage_path", help="Pfad zur knowledge-usage.json")
    usage.add_argument("--skill", required=True, help="Ziel-SKILL.md")
    usage.add_argument("--experiment-dir", required=True)
    usage.add_argument("--experiment", required=True)

    ufmt = sub.add_parser(
        "usage-format", help="Nutzungsblock für den Hypothesis-Agenten"
    )
    ufmt.add_argument("usage_path")
    ufmt.add_argument("--experiment")

    prune = sub.add_parser(
        "prune-suggest",
        help="Nie gelesene Claims als Vorschlag für den Report. Löscht nichts",
    )
    prune.add_argument("usage_path")
    prune.add_argument("--skill", required=True)
    prune.add_argument("--stale-after", type=int, default=STALE_EXPERIMENTS)
    prune.add_argument("--as-json", action="store_true")

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
        fields["skill_path"] = args.skill
        try:
            result = append_gap(args.gaps_path, **fields)
        except ValueError as exc:
            print(json.dumps(
                {"error": str(exc)}, indent=2, ensure_ascii=False
            ), file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2, ensure_ascii=False))
        # Exit 3: der Bestand deckt die Frage bereits. Der Aufrufer soll das
        # nicht mit einem Duplikat verwechseln — hier ist nichts zu fragen,
        # sondern der Verweis auf den Bestand zu reparieren.
        return 3 if result.get("covered_by_vault") else 0

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

    if args.command == "init":
        try:
            result = init_knowledge(args.skill_path)
        except FileNotFoundError as exc:
            print(json.dumps({"error": str(exc)}, indent=2, ensure_ascii=False),
                  file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.command == "source-add":
        try:
            result = add_source(
                args.skill_path, args.file_path, title=args.title,
                trust=args.trust, rights=args.rights, stand=args.stand,
            )
        except (ValueError, FileNotFoundError) as exc:
            print(json.dumps({"error": str(exc)}, indent=2, ensure_ascii=False),
                  file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.command == "claim-add":
        payload = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        claims = payload.get("claims")
        if not claims:
            print(json.dumps(
                {"error": "Kein Block claims in %s. Ein Librarian-Lauf ohne "
                          "Claims ist kein Fehler, aber auch nichts zum "
                          "Schreiben." % args.from_json},
                indent=2, ensure_ascii=False), file=sys.stderr)
            return 1
        result = add_claims(
            args.skill_path, args.page, claims,
            title=args.title, domain=args.domain or payload.get("domain", ""),
            stichworte=args.stichworte or payload.get("stichworte"),
            evals_path=args.evals, supersedes=args.supersedes,
            allow_near_duplicate=args.allow_near_duplicate,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        # Exit 2, wenn kein einziger Claim durchkam: der Aufrufer soll das
        # nicht mit einem leeren, aber erfolgreichen Lauf verwechseln.
        return 0 if result["written"] else 2

    if args.command == "verify":
        result = verify_knowledge(args.skill_path)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("ok") else 1

    if args.command == "index":
        build_index(args.skill_path)
        print(json.dumps(
            {"index": str(knowledge_root(args.skill_path) / INDEX_FILE)},
            indent=2, ensure_ascii=False))
        return 0

    if args.command == "stats":
        result = knowledge_stats(
            args.skill_path, budget=args.budget,
            chars_per_token=args.chars_per_token,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1 if result.get("over_budget") else 0

    if args.command == "leak-check":
        hits = []
        for claim in all_claims(args.skill_path):
            found = leak_check(claim["text"], args.evals)
            if found:
                hits.append({"claim_id": claim["claim_id"], "hits": found})
        print(json.dumps({"leaks": hits, "clean": not hits},
                         indent=2, ensure_ascii=False))
        return 1 if hits else 0

    if args.command == "search":
        result = vault_covers(args.skill_path, args.query,
                              threshold=args.threshold)
        result["candidates"] = search_vault(
            args.skill_path, args.query, limit=args.limit
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["covered"] else 1

    if args.command == "usage-update":
        try:
            usage = update_usage(args.usage_path, args.skill,
                                 args.experiment_dir, args.experiment)
        except FileNotFoundError as exc:
            print(json.dumps({"error": str(exc)}, indent=2, ensure_ascii=False),
                  file=sys.stderr)
            return 1
        latest = usage["experiments"][-1]
        print(json.dumps({
            "experiment": latest["experiment"],
            "runs_with_vault_access": len(latest["runs"]),
            "claims_used": latest["claims_used"],
            "never_used": usage["never_used"],
        }, indent=2, ensure_ascii=False))
        return 0

    if args.command == "usage-format":
        block = format_usage(args.usage_path, args.experiment)
        if block:
            print(block, end="")
        return 0

    if args.command == "prune-suggest":
        if args.as_json:
            print(json.dumps(
                prune_suggestions(args.usage_path, args.skill, args.stale_after),
                indent=2, ensure_ascii=False))
        else:
            block = format_prune(args.usage_path, args.skill, args.stale_after)
            if block:
                print(block, end="")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
