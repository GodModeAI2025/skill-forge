# Plan: Wissenslücken erkennen, Wissen beschaffen, Wissen pflegen

Stand: 2026-09-19. Betrifft ausschließlich `skill-forge`. SkillSafe wird als
Konzept übernommen, nicht als Abhängigkeit und nicht durch eine Änderung an
jenem Repository.

**Umsetzungsstand:** Phase 1 und Phase 2 sind implementiert.

* **Phase 1 — erkennen und fragen:** dritte Fehlerklasse `KNOWLEDGE_GAP`,
  `knowledge-gaps.jsonl`, die Entscheidung `DEFERRED`, Report-Abschnitt.
* **Phase 2 — Wissen entgegennehmen:** Wissensbestand beim Ziel-Skill,
  Quellenregister mit SHA-256, `claim-add` mit fünf Gates, `verify`, `index`,
  getrennte Budgets, `agents/librarian.md`.
* Aus Phase 4 vorgezogen, weil das Format es ohnehin tragen musste:
  Quellendrift-Erkennung und Supersession statt Überschreiben.

Offen sind Phase 3 (freigegebene Quellen), der Rest von Phase 4
(Nutzungsverfolgung aus Transcripts, Prune-Vorschläge) und Phase 5.

**Zu den Fragen in Abschnitt 13:** Frage 1 und 2 sind entschieden — der Bestand
liegt beim Ziel-Skill und der Loop darf dort `knowledge/` anlegen. Grundlage
ist die ursprüngliche Anforderung, der Skill solle dieses Wissen „in sich
enthalten". Frage 3 ist als Default gesetzt (`knowledge_budget`, 4× das
Token-Budget) und überschreibbar. Frage 4 ist offen.

---

## 1. Das Problem

Skill Forge kennt heute genau zwei Hebel, mit denen ein Skill besser wird:

1. **Formulierung** — `instruction_edit`, `example_add`, `structure_change`, `prune`
2. **Determinismus** — `script_add`, `script_fix`, also: Regeln in Code gießen,
   damit das Modell sie nicht mehr interpretieren muss

Beide Hebel setzen dieselbe Annahme voraus: *Der Agent könnte die Aufgabe lösen,
wenn man ihm nur klar genug sagt, wie.* Für eine ganze Klasse von Fehlern stimmt
das nicht. Wenn ein Lektorats-Skill die Zitierregel eines bestimmten Verlags
nicht kennt, wenn ein Requirements-Skill die konzerninterne Rollenbezeichnung
nicht kennt, wenn ein Code-Skill die tatsächliche Signatur einer internen API
nicht kennt — dann ist keine Umformulierung der Welt die Lösung. Es fehlt eine
**Tatsache**, kein Verhalten.

Der heutige Loop reagiert auf solche Fehler falsch, und zwar auf zwei Arten:

- Der Hypothesis-Agent klassifiziert binär: `SKILL_DEFECT` oder
  `EXECUTION_LAPSE`. Eine fehlende Tatsache hat in diesem Raster keinen Platz
  und landet als `SKILL_DEFECT`. Der Mutator bekommt also den Auftrag, eine
  Anweisung zu schärfen, die schon präzise ist.
- Der Mutationstyp `reference_add` existiert bereits mit der Beschreibung
  „Agent braucht Domänenwissen". Es gibt aber keinen Prozess, dieses Wissen zu
  **beschaffen**. Der Mutator schreibt die Referenzdatei also aus dem
  Modellgedächtnis. Genau dort entstehen selbstbewusst formulierte falsche
  Fakten, und das Gate merkt es nicht: ein plausibel klingender Satz besteht
  Assertions und einen LLM-Judge oft besser als ein sperriger richtiger.

Das ist die schlechteste aller Varianten — der Loop erfindet Wissen und misst
sich dabei selbst ein gutes Zeugnis aus.

## 2. Was gebaut werden soll

Drei Fähigkeiten, in dieser Reihenfolge abhängig voneinander:

1. **Identifizieren** — Der Loop erkennt, dass ein Fehler auf fehlendem Wissen
   beruht, und benennt präzise, welche Tatsache fehlt.
2. **Beschaffen** — Der Loop holt sich diese Tatsache aus (a) vorab
   bereitgestelltem Material, (b) einer Allowlist freigegebener Quellen, oder
   (c) einer Frage an den Menschen. Nie aus dem eigenen Gedächtnis.
3. **Pflegen** — Das beschaffte Wissen liegt belegt, versioniert und
   nachprüfbar im Skill, wird auf Nutzung und Veralterung überwacht und bei
   Widerspruch fail-closed behandelt.

---

## 3. Die Kernentscheidung: zwei Spuren

Das schwierigste Problem des Vorhabens ist nicht die Beschaffung, sondern das
Gate. Skill Forge lebt davon, dass jede Änderung mechanisch gemessen wird —
Mutation, Score, KEEP oder REVERT. Wissen passt dort nicht hinein, und zwar aus
einem grundsätzlichen Grund:

> Ob eine Formulierung besser ist, entscheidet die Messung. Ob eine Tatsache
> stimmt, entscheidet die Quelle. Ein Eval-Score ist kein Wahrheitskriterium.

Ein sauber belegter Satz, der im aktuellen Eval-Set zufällig nichts bewegt, ist
trotzdem richtig und gehört in den Bestand. Ein erfundener Satz, der den Score
hebt, gehört es nicht. Wer beides über dieselbe Schwelle laufen lässt,
bekommt einen Loop, der Wissen nach Nützlichkeit statt nach Wahrheit auswählt.

Deshalb wird getrennt:

| | Spur A — Inhalt | Spur B — Verweis |
|---|---|---|
| **Was** | Die Claims im Wissensbestand | Die Regel in der SKILL.md, die auf den Bestand zeigt |
| **Beispiel** | „C-0007: Verlag X verlangt Kurzbeleg im Fließtext, Vollbeleg nur im Verzeichnis." | „Vor jedem Beleg: `knowledge/INDEX.md` konsultieren. Nicht im Bestand → nachfragen, nicht erfinden." |
| **Torwächter** | Provenienz: Quelle vorhanden, Hash stimmt, kein Leak, kein Widerspruch | Das normale Gate: `decide`, KEEP/REVERT auf val |
| **Entscheidet** | Script + im Zweifel der Mensch | Der Composite Score |
| **Bei Ablehnung** | Claim wird nicht geschrieben, Frage bleibt offen | Snapshot zurück, wie bei jeder Mutation |

Spur B ist eine ganz gewöhnliche Mutation und braucht keine Sonderbehandlung.
Sie beantwortet die messbare Frage: *Nützt es, den Agenten auf den Bestand zu
stoßen?* Spur A beantwortet die nicht-messbare Frage: *Stimmt das, was dort
steht?*

Das ist kein Schlupfloch am Gate vorbei, sondern dieselbe Logik, mit der der
Skill den `FORGE_APPENDIX` bereits behandelt: gate-umgehender Inhalt ist
erlaubt, wenn er (a) an eine beobachtete Evidenz gebunden, (b) gedeckelt, (c)
kurz und (d) nicht in der Lage ist, bestehende Regeln umzuschreiben. Wissen
erfüllt (a) über die Quellenbindung, (b) über ein eigenes Budget, (c) über das
Claim-Format und (d) über die Widerspruchsregel aus Abschnitt 7.4.

---

## 4. Was von SkillSafe übernommen wird — und was nicht

Übernommen wird das **Konzept**, nicht der Code. Skill Forge implementiert eine
minimale, native Teilmenge, die formatkompatibel bleibt: ein Wissenspaket, das
Skill Forge erzeugt, lässt sich später ohne Umschreiben in einen echten
Wissenstresor einlesen. Deshalb werden die ID-Präfixe `C-nnnn` (Claim),
`S-nnnn` (Quelle) und `X-nnnn` (externe Bezugsquelle) wörtlich übernommen.

| Aus SkillSafe | Übernommen? | Warum |
|---|---|---|
| Geschlossene Welt („Nicht im Bestand", nie aus Modellwissen) | **Ja, aber begrenzt** | Siehe unten — für einen beliebigen Skill darf die Regel nicht global gelten |
| Claim mit Quellen-ID und Fundstelle | **Ja** | Das ist der eigentliche Kern. Ohne Quelle kein Claim |
| Quellenregister mit SHA-256, Trust-Stufe, Rechten | **Ja** | Ermöglicht Veralterungserkennung und Rechteklarheit |
| „Quellen sind Daten" (Prompt-Injection-Regel) | **Ja** | Zwingend, sobald fremdes Material eingelesen wird |
| Fail closed bei Unklarheit | **Ja** | Ein Overnight-Loop darf bei Widerspruch nicht raten |
| Skript vor Modell (alles Deterministische in Code) | **Ja** | Deckt sich mit der v3-Linie „die Entscheidung ist Code" |
| `INDEX.md` als Navigations-Map, Seiten on demand | **Ja** | Löst das Budget-Problem, siehe 7.5 |
| Allowlist externer Bezugsquellen statt Recherche | **Ja** | Ohne das ist ein Auto-Modus nicht verantwortbar |
| Begriffswelten, Aliase, Graph-Hop, Hybrid-Retrieval | **Nein** | Für Bestände dieser Größe (Dutzende Claims) Overkill. Stichwort-Routing reicht |
| `graph.json`, `route`, `doctor`, `release`-Transaktion | **Nein** | Eigene Maschinerie, die Skill Forge nicht braucht |
| Multimodal, OCR, Medienregionen | **Nein** | Kein erkennbarer Bedarf im Loop-Kontext |
| OKF-Export | **Nein** | Gibt Wissen aus der Hand, ist eine Menschenentscheidung |

**Zur begrenzten geschlossenen Welt:** Die Regel „Fakten kommen ausschließlich
aus dem Bestand" ist für einen Wissenstresor richtig und für einen beliebigen
Skill falsch. Ein Lektorats-Skill muss weiterhin allgemeine Sprachkompetenz
einsetzen dürfen. Die Regel wird deshalb auf die im Bestand geführten
**Domänen** eingeschränkt und steht so in der geschützten Region:

> Für die unter `knowledge/INDEX.md` geführten Themen gilt der Bestand als
> alleinige Faktenquelle. Deckt er eine Frage dort nicht, sag das, statt aus
> eigenem Wissen zu ergänzen. Außerhalb dieser Themen gilt die Regel nicht.

---

## 5. Zielseitiges Artefakt

Der optimierte Skill bekommt einen Unterbaum und eine geschützte Region:

```
<ziel-skill>/
├── SKILL.md                    ← + FORGE_KNOWLEDGE-Region (~12 Zeilen, permanent)
└── knowledge/
    ├── INDEX.md                ← Stichwort → Seite. Klein, permanent im Kontext
    ├── SOURCES.md              ← Register: ID, Titel, Stand, SHA-256, Trust, Rechte, Ablage
    ├── pages/<slug>.md         ← Claims. Werden nur bei Bedarf gelesen
    └── MANIFEST.sha256         ← Prüfsummen des Bestands
```

Eine Seite folgt dem Vault-Format in Kurzform:

```markdown
---
type: wissen
title: Belegregeln Verlag X
domain: lektorat
status: aktiv
confidence: hoch
stand: 2026-09-19
sources: [S-0002]
---

# Belegregeln Verlag X

## Kurzfassung
Zwei Sätze, die die Seite abfragbar machen.

## Claims
- **C-0007** [S-0002 | "Abschnitt 4.2 Belege" | Wortlaut] Im Fließtext steht der
  Kurzbeleg (Autor, Jahr, Seite); der Vollbeleg erscheint ausschließlich im
  Literaturverzeichnis.
```

Die dritte geschützte Region in der Ziel-SKILL.md, neben `FORGE_KEEP` (gehört
dem User) und `FORGE_APPENDIX` (gehört dem Loop):

```markdown
<!-- FORGE_KNOWLEDGE_START -->
Wissensbestand: knowledge/INDEX.md
Für die dort geführten Themen ist der Bestand die alleinige Faktenquelle.
Nicht im Bestand → sag das, ergänze nicht aus eigenem Wissen.
<!-- FORGE_KNOWLEDGE_END -->
```

**Korrektur gegenüber der ersten Fassung dieses Plans.** Dort stand, die Region
werde von `verify-regions` byteweise mitgeprüft „wie die beiden anderen" — und
im selben Absatz, ihr Inhalt sei Spur B und damit gate-pflichtig. Beides
zusammen geht nicht: was byteweise geschützt ist, kann der Mutator nicht
ändern, und was er nicht ändern kann, kann das Gate nicht bewerten. Die erste
Formulierung des Verweises wäre für immer eingefroren.

Richtig ist: Die Region steht **nicht** in `PROTECTED_REGIONS`. Ihr Inhalt ist
gewöhnlicher, gate-pflichtiger SKILL.md-Text; die Marker dienen dazu, den
Verweis mechanisch wiederzufinden, nicht ihn festzunageln. Die Frage „gibt es
den Verweis überhaupt?" beantwortet stattdessen ein Lint in
`knowledge.py verify`: liegen Claims im Bestand, aber die SKILL.md hat keine
`FORGE_KNOWLEDGE`-Region, ist das eine Warnung — der Agent findet den Bestand
sonst nie. Löscht der Mutator den Verweis und war er nützlich, fällt der Score
und das Gate rollt zurück. Genau dafür ist es da.

## 6. Workspace-seitige Artefakte

```
<workspace>/
├── knowledge-gaps.jsonl      ← erkannte Lücken; status: open|sourced|answered|rejected|conflict
├── knowledge-sources.json    ← Allowlist der freigegebenen Quellen + Bindungen
├── knowledge-usage.json      ← welcher Claim in welchem Run gelesen wurde
└── knowledge-inbox/          ← vom User bereitgestelltes Rohmaterial
```

`knowledge-gaps.jsonl` ist das zentrale neue Artefakt. Es ist append-only und
kompaktierungsfest, aus demselben Grund wie `rejected.jsonl`: eine offene Frage
darf nicht aus der History herausgekürzt werden.

Ein Eintrag:

```json
{
  "gap_id": "gap-003",
  "experiment": "exp-004",
  "question": "Welchen Belegstil verlangt Verlag X im Fließtext?",
  "why_needed": "3/4 train-Evals mit Beleg im Text failen Assertion 'beleg_kurzform'",
  "eval_ids": ["belege-fliesstext", "belege-fussnote", "belege-tabelle"],
  "answer_shape": "Eine Regel: Kurzbeleg oder Vollbeleg, plus Ausnahmen",
  "tried_sources": ["S-0001", "X-0001"],
  "status": "open",
  "resolved_by": null,
  "created_at": "2026-09-19T02:14:00Z"
}
```

Das Feld `answer_shape` ist kein Beiwerk. Es ist der Unterschied zwischen einer
Frage, die der Mensch in dreißig Sekunden beantwortet, und einer, die er
wegklickt.

---

## 7. Die Bausteine im Einzelnen

### 7.1 Identifikation: die dritte Fehlerklasse

`agents/hypothesis.md`, Abschnitt 2c, wird von zwei auf drei Klassen erweitert.
Die Klassifikation läuft als Kaskade, Reihenfolge ist bindend:

1. **Stand die Regel schon da und wurde ignoriert?** → `EXECUTION_LAPSE`.
   Unverändert, bleibt der erste Test.
2. **Hätte eine perfekte Anweisung gereicht, oder braucht die richtige Antwort
   eine Tatsache, die im Skill nicht steht und die der Agent nicht zuverlässig
   herleiten kann?** → Tatsache nötig = `KNOWLEDGE_GAP`.
3. Sonst → `SKILL_DEFECT`. Unverändert.

Mechanische Hilfsmarker für Schritt 2, weil die Frage sonst zur Geschmackssache
wird:

- Die gescheiterte Assertion prüft einen **Wert** (Name, Zahl, Norm, Signatur,
  Termin, Bezeichnung), nicht eine **Form** (Struktur, Reihenfolge, Ton, Länge).
- Der Agent hat in den Transcripts etwas Konkretes **behauptet**, das falsch
  war — statt die Aufgabe formal falsch zu erledigen. Erfundene Spezifik ist das
  stärkste Signal für eine Wissenslücke.
- Die Antworten **streuen über Runs**: derselbe Prompt, drei verschiedene
  erfundene Werte. Ein Formfehler ist stabil, eine Wissenslücke würfelt.
- Der Agent hat in den Transcripts nach einer Information **gesucht** und sie
  nicht gefunden.

**Der Default ist asymmetrisch, und zwar gegen `KNOWLEDGE_GAP`.** Bei echter
Unsicherheit gilt `SKILL_DEFECT`. Begründung: der Wissenszweig ist der teuerste
von dreien. Er unterbricht den Menschen, belegt dauerhaft Budget und erzeugt
Pflegeaufwand. Eine als Wissenslücke fehlklassifizierte Formulierungsschwäche
kostet eine Nachtrunde und eine überflüssige Frage im Morgenreport; umgekehrt
kostet es nur einen normalen REVERT. Zusätzlich gilt die bestehende
Support-Regel unverändert: `support_count >= 2` über train-Evals, mit
`eval_ids` als Nachweis. Eine Lücke, die sich in genau einem Eval zeigt, ist
keine Lücke, sondern ein Einzelfall.

**Deckel:** höchstens ein `KNOWLEDGE_GAP` pro Experiment
(`max_knowledge_gaps_per_experiment: 1`). Der Loop soll Wissen erwerben, nicht
Fragebögen produzieren.

Neue Felder im Output-Schema des Hypothesis-Agenten:

```json
"failure_summary": [{"failure_class": "SKILL_DEFECT | EXECUTION_LAPSE | KNOWLEDGE_GAP", "...": "..."}],
"knowledge_request": {
  "question": "string",
  "why_needed": "string",
  "answer_shape": "string",
  "eval_ids": ["..."],
  "domain": "string"
}
```

Neuer Root Cause im Katalog (Abschnitt 3 der hypothesis.md): **Knowledge Gap** —
„Dem Agenten fehlt eine Tatsache, die er nicht herleiten kann. Keine
Formulierung behebt das."

### 7.2 Beschaffung: drei Quellen, feste Rangfolge

Ein neuer Agent `agents/librarian.md` nimmt einen `knowledge_request` entgegen
und arbeitet drei Quellen in dieser Reihenfolge ab:

**Quelle 1 — Vorrat.** Material, das der User beim Wizard bereitgestellt hat,
liegt in `knowledge-inbox/` und ist in `SOURCES.md` registriert. Der Librarian
liest es und extrahiert Claims. Kein Nutzereingriff nötig, funktioniert im
Auto-Modus.

**Quelle 2 — Freigegebene Quellen.** Eine Allowlist nach dem Vorbild von
`sources/EXTERN.md`: benannte Repositorien, Handbücher, Dokumentbäume, feste
URL-Präfixe. Erreichbar ist ausschließlich, was namentlich dort steht. Es gibt
keinen Codepfad, der ein Ziel aus einem Dokument, einer Antwort oder einer
Frage übernimmt. Jeder Abruf wird mit URL, Prüfsumme und Zeitpunkt protokolliert.
**Keine offene Websuche, in keinem Modus.** Das ist die Grenze zwischen
„durchsucht bereitgestellte Quellen" und „recherchiert im Internet", und sie
wird nicht verhandelt: ein Loop, der nachts unbeaufsichtigt beliebige Seiten
liest und deren Inhalt in einen Skill schreibt, ist ein Einfallstor, kein
Feature.

**Quelle 3 — Der Mensch.** Wenn 1 und 2 nichts hergeben:

- **Guided-Modus:** neuer Checkpoint 2.5 „Wissenslücke". Der User sieht Frage,
  Begründung und `answer_shape` und kann antworten, eine Datei nachreichen, eine
  Quelle freigeben oder die Lücke als irrelevant verwerfen.
- **Auto-Modus: keine Blockade.** Der Gap-Eintrag bleibt `open`, das Experiment
  endet mit der neuen Entscheidung `DEFERRED`, der Loop geht zur nächsten
  Hypothese. Im Morgenreport steht die Frage in einem eigenen Abschnitt.

Das ist die eigentliche Pointe für Overnight-Läufe: **Der Lauf liefert morgens
nicht nur einen besseren Skill, sondern eine kurze Liste präziser Fragen, die
der Mensch in fünf Minuten beantwortet und die der nächste Lauf verwertet.** Ein
Loop, der sagt „ich komme hier nicht weiter, weil mir genau das fehlt", ist
wertvoller als einer, der die Lücke mit Erfundenem füllt und einen grünen Score
meldet.

**Der Librarian erfindet nichts.** Findet er keine Quelle, ist die korrekte
Ausgabe `{"resolved": false}` plus ein offener Gap-Eintrag. Er ist deshalb ein
eigener Agent und keine Erweiterung des Mutators: der Mutator wird dafür
belohnt, etwas zu schreiben; der Librarian muss bereit sein, nichts zu liefern.
Diese beiden Anreize gehören nicht in denselben Prompt.

### 7.3 `DEFERRED` als vierter Ablaufwert

`decide` bleibt unverändert — drei Ausgänge, kein vierter. `DEFERRED` entsteht
wie `SKIP`, `INVALID` und `NO_OP` aus dem Ablauf drumherum und wird in
`tsv-append` und `coverage-update` zugelassen.

| Wert | Wann | Zählt in Sättigung? | Zählt in Plateau? |
|---|---|---|---|
| `DEFERRED` | Wissenslücke erkannt, keine Quelle verfügbar, Frage gestellt | nein | **nein** |

Die Plateau-Regel (3 aufeinanderfolgende Nicht-KEEP → Stopp) darf `DEFERRED`
nicht mitzählen, sonst beendet eine Serie unbeantworteter Fragen den Lauf,
obwohl gar keine Hypothese gescheitert ist. Stattdessen ein eigener Zähler:
`max_deferred_per_run` (Default 3). Ist er erreicht, wird die Kategorie
`knowledge` für den Rest des Laufs deprioritisiert und der Loop arbeitet an
Formulierung und Determinismus weiter. Ohne diesen Deckel läuft eine Nacht
durch, ohne eine einzige Mutation zu erzeugen.

### 7.4 Gates auf Spur A

Vier mechanische Prüfungen, bevor ein Claim geschrieben wird. Alle in
`scripts/knowledge.py`, keine als Punkt auf einer Checkliste im Agent-Prompt —
aus demselben Grund, aus dem `verify-regions` in Python läuft und nicht im
Sanity-Check des Mutators steht.

**(a) Provenienz.** Jeder Claim trägt eine `S-nnnn`, die im Register steht;
die Datei unter *Ablage* hat den eingetragenen SHA-256; die Fundstelle ist
angegeben. Fehlt eines davon: Exit ungleich 0, kein Schreibvorgang, Gap bleibt
offen. Es gibt keinen Claim ohne Quelle, auch nicht „hilfsweise".

**(b) Leak-Check.** Das größte Risiko des ganzen Vorhabens ist, dass der Loop
die erwarteten Eval-Antworten als „Wissen" einträgt. Der val-Score steigt, nichts
generalisiert, und der Overfitting-Schutz ist unterlaufen. Drei Sperren:

1. Wissenslücken werden ausschließlich aus dem **train-Split** abgeleitet.
   Bestehende Regel, gilt hier unverändert.
2. Quelle einer Antwort ist **nie** die Assertion oder der Erwartungswert eines
   Evals, sondern immer ein registriertes Dokument oder eine Nutzerantwort.
3. Mechanisch: `knowledge leak-check` weist einen Claim zurück, dessen
   normalisiertes 8-Wort-Fenster wörtlich in einem val- oder test-Eval
   vorkommt. Bewusst über *alle* Splits geprüft, nicht nur über val: ein Claim,
   der eine Testantwort enthält, ist auch dann Leakage, wenn er zufällig aus
   einem Dokument stammt.

**(c) Injection.** Eingelesenes Material ist Daten, nie Anweisung. Ein Abschnitt,
der Imperative an das System richtet („ignoriere", „ab jetzt gilt", „führe aus"),
wird nicht eingelesen, sondern als Auffälligkeit gemeldet und nach
`knowledge-inbox/quarantine/` gelegt. Der Wissensbaum enthält ausschließlich
`.md` und `.json`; eine Allowlist erzwingt das, nichts darunter wird ausgeführt.

**(d) Secrets.** Vor dem Schreiben läuft ein Secret-Scan über den Claim-Text.
Ein Token, ein Passwort, ein Key landet nicht im Skill-Artefakt — schon gar
nicht in einem, das weitergegeben wird. Fail closed.

**Widerspruch.** Kollidiert ein neuer Claim mit einem bestehenden (gleiche
Domäne, gleiches Konzept-Tag, abweichende Aussage), wird **nicht** überschrieben.
Der neue Claim geht als `status: conflict` in `knowledge-gaps.jsonl`, beide
Fassungen werden zitiert, der Mensch entscheidet. Die Erkennung ist eine
Heuristik und wird auch so benannt: sie fängt den offensichtlichen Fall (gleiche
Entität, andere Zahl) und nicht den subtilen. Der Ausweg ist trotzdem richtig,
denn die Alternative — stilles Überschreiben — verliert belegtes Wissen ohne
Spur.

### 7.5 Budget: zwei Budgets statt einem

Wissen wächst das Artefakt. Der bestehende `token_budget` mit
`artifact-stats` würde nach wenigen Claims anschlagen und den Orchestrator in
`forced_category: efficiency` zwingen — der Loop würde also anfangen, das
gerade erworbene Wissen wieder wegzukürzen. Das ist kein hypothetisches Risiko,
das ist die zwangsläufige Folge eines einzigen Budgets.

Die Trennung folgt der Ladelogik:

| Budget | Umfasst | Default | Verhalten bei Überschreitung |
|---|---|---|---|
| `token_budget` | SKILL.md, `references/`, `scripts/`, **`knowledge/INDEX.md`** | wie bisher | `forced_category: efficiency`, `prune` |
| `knowledge_budget` | `knowledge/pages/`, `SOURCES.md` | 4× `token_budget` | `knowledge_prune`-Vorschlag im Report, **kein** Automatismus |

`INDEX.md` zählt bewusst gegen das strenge Budget: es liegt bei jedem Lauf im
Kontext und ist damit echter Dauerverbrauch. Die Seiten zählen gegen das weite
Budget, weil sie nur gelesen werden, wenn der Index auf sie zeigt. Das ist
exakt der Grund, warum der Wissenstresor `INDEX.md` und `knowledge/` trennt,
und der Grund, warum Wissen überhaupt in einen Unterbaum gehört statt in die
SKILL.md.

`artifact-stats` bekommt dafür ein `--exclude`-Argument oder, sauberer, einen
zweiten Aufruf mit eigenem Budget. Entscheidung dazu in Phase 2.

### 7.6 Pflege

Vier Mechanismen, alle mechanisch, keiner löscht automatisch.

**Nutzungsverfolgung.** Nach jedem Skill-Modus-Experiment scannt
`knowledge usage-update --from-transcripts <dir>` die Transcripts nach gelesenen
Seitenpfaden und zitierten Claim-IDs und schreibt sie nach
`knowledge-usage.json`. Kostet nichts und beantwortet die einzige Frage, die bei
der Pflege zählt: *Wird das überhaupt angefasst?*

**Veralterung.** `knowledge verify` rechnet die Quell-Hashes nach. Weicht eine
Ablage ab, oder liefert eine freigegebene URL einen anderen Hash als beim
Ingest, werden die abhängigen Claims auf `status: pruefen` gesetzt und im Report
aufgeführt. Sie werden **nicht** automatisch aktualisiert: was sich in der
Quelle geändert hat, ist eine inhaltliche Frage.

**Prune-Vorschläge.** Ein Claim, der über `knowledge_stale_experiments` (Default
20) Experimente nie gelesen wurde und dessen Seite im Index nie getroffen wurde,
erscheint als Vorschlag im Morgenreport. Gelöscht wird er im Guided-Modus nach
Bestätigung, im Auto-Modus gar nicht — nur markiert. Wissen ist billig, solange
es on demand liegt; der Druck zu löschen ist gering, das Risiko eines
Fehllöschens hoch. Die `success_patterns`-Schutzliste, die den Mutator heute vor
`prune` schützt, gilt sinngemäß auch hier.

**Supersession statt Überschreiben.** `knowledge_update` ersetzt einen Claim
nicht, sondern setzt ihn auf `status: veraltet` mit Verweis auf den Nachfolger.
Die History bleibt lesbar, und ein falsch beschafftes Update ist rückgängig zu
machen.

---

## 8. Messbarkeit — und die ehrliche Grenze

Wissen ist nur messbar, wenn das Eval-Set wissenssensitive Fälle enthält. Ein
Set aus reinen Formatierungs-Evals wird durch keinen Claim besser. Der Loop
würde dann NEUTRAL messen, Spur B zurückrollen und daraus die falsche Lehre
ziehen, Wissen helfe nicht.

Drei Konsequenzen:

1. **Wizard-Hinweis.** Wenn der User beim Setup Wissensquellen angibt, weist
   der Wizard darauf hin, dass mindestens zwei Evals eine Frage stellen müssen,
   die ohne dieses Wissen nicht zu beantworten ist.
2. **Selbstkorrektur.** Eine aus train-Failures abgeleitete Wissenslücke ist per
   Konstruktion wissenssensitiv. Ob val dieselbe Empfindlichkeit hat, ist offen
   und hängt an der Split-Verteilung.
3. **Ehrlicher Report.** Ein eigener Abschnitt weist aus: *n* Claims aus *m*
   Quellen aufgenommen, davon *k* mit messbarer val-Wirkung, *n−k* ungemessen.
   Und, falls `n−k > 0`, die Empfehlung, welches Eval fehlt. Ungemessenes Wissen
   wird als ungemessen ausgewiesen und nicht als Erfolg verbucht.

Dieselbe Trennung gilt für den test-Split: er bleibt der einzige nicht
mitoptimierte Wert und wird weiterhin genau zweimal angefasst.

---

## 9. Änderungen, Datei für Datei

| Datei | Änderung | Phase |
|---|---|---|
| `agents/hypothesis.md` | Dritte Fehlerklasse in 2c, Root Cause `knowledge_gap` in 3, Feld `knowledge_request` im Output-Schema, Mutationstypen-Tabelle ergänzt | 1 |
| `agents/librarian.md` | **Neu.** Beschaffung aus drei Quellen, Rangfolge, „nichts finden ist ein gültiges Ergebnis" | 2 |
| `agents/mutator.md` | Mutationstypen `knowledge_link`, `knowledge_add/update/prune`; Schutzliste gilt auch für Claims; Regelform für den Verweistext | 2 |
| `agents/orchestrator.md` | Gap-Queue in die Context Assembly; `DEFERRED`-Ablauf; `max_deferred_per_run` | 2 |
| `agents/meta.md` | Wissens-Mutationen in der Meta-Memory getrennt führen (andere Wirkungslogik als Formulierungsmutationen) | 4 |
| `scripts/knowledge.py` | **Neu.** `init`, `source-add`, `claim-add`, `verify`, `leak-check`, `index`, `stats`, `usage-update`, `stale`, `gap-append`, `gap-resolve` | 1–4 |
| `scripts/composite_score.py` | `DEFERRED` in die erlaubten Werte von `tsv-append`/`coverage-update`; Plateau-Zählung schließt `DEFERRED` aus; `verify-regions` kennt `FORGE_KNOWLEDGE`; `artifact-stats` trennt die Budgets | 1–2 |
| `SKILL.md` | Wizard-Schritt 3.5 „Wissensquellen"; Guided-Checkpoint 2.5; Abschnitt „Wissen"; dritte geschützte Region; neue Config-Keys; Coverage-Kategorie `knowledge` | 1–4 |
| `templates/morning_report.md` | Abschnitte „Offene Wissensfragen", „Wissensbestand", „Prune-Vorschläge" | 1, 4 |
| `templates/agent_context.md` | Offene Gaps und Bestandsüberblick in den Laufzeitkontext | 2 |
| `references/architecture.md` | Zwei-Spuren-Modell, Budget-Trennung, Sicherheitsgrenzen | 2 |
| `tests/test_knowledge.py` | **Neu.** Provenienz, Leak-Check, Injection, Secrets, Widerspruch, Index-Determinismus, Budget-Trennung, `DEFERRED`-Ablauf | 1–4 |
| `examples/wissensluecke-lauf.md` | **Neu.** Ein durchgelaufenes Beispiel mit ausgelösten Sperren, analog `generic-mode-lauf.md` | 4 |

Warum ein eigenes `scripts/knowledge.py` und nicht mehr Subcommands in
`composite_score.py`: die Entscheidungslogik dort ist durch 283 Tests
festgenagelt und hat genau eine Aufgabe — aus zwei Zahlen ein Urteil machen.
Provenienz und Quellenverwaltung sind eine andere Aufgabe mit anderem
Fehlermodus. Zwei Scripts, zwei Testdateien.

---

## 10. Phasen

Jede Phase ist für sich nützlich und einzeln lieferbar. Die Reihenfolge ist
nicht verhandelbar: ohne Identifikation gibt es nichts zu beschaffen, ohne
Beschaffung nichts zu pflegen.

**Phase 1 — Nur erkennen und fragen.** Dritte Fehlerklasse, `knowledge_request`,
`knowledge-gaps.jsonl`, `DEFERRED`, Report-Abschnitt „Offene Wissensfragen".
Kein Schreibzugriff auf irgendein Wissen. Der Loop lernt zu sagen: „Hier fehlt
mir etwas, und zwar genau das."
*Risiko: minimal — es wird nichts geschrieben. Nutzen: sofort.*
Umfang: 1 Arbeitseinheit, ~10 Tests.

**Phase 2 — Wissen entgegennehmen.** Wizard-Schritt 3.5, `knowledge-inbox/`,
`SOURCES.md`, `scripts/knowledge.py` mit `init`/`source-add`/`claim-add`/
`verify`/`leak-check`/`index`, `agents/librarian.md` beschränkt auf Quelle 1,
`FORGE_KNOWLEDGE`-Region, Budget-Trennung, Guided-Checkpoint 2.5.
Nach Phase 2 ist der volle Kreislauf für vorab bereitgestelltes Material
geschlossen.
Umfang: 2 Arbeitseinheiten, ~25 Tests.

**Phase 3 — In freigegebenen Quellen suchen.** Allowlist, Bindung, Hash-Pinning,
Abrufprotokoll, Quarantäne. Der Librarian bekommt Quelle 2.
Umfang: 1–2 Arbeitseinheiten, ~15 Tests.

**Phase 4 — Pflegen.** Nutzungsverfolgung, Veralterung, Supersession,
Prune-Vorschläge, Report-Abschnitt „Wissensbestand", Meta-Memory-Trennung,
Beispiel-Lauf.
Umfang: 1 Arbeitseinheit, ~15 Tests.

**Phase 5 — Optional: Aufstieg zum echten Tresor.** Ist der Skill
`wissenstresor` installiert, kann Skill Forge das Wissenspaket dorthin
übergeben und `vault.py query` statt des eigenen Stichwort-Routings nutzen.
Analog zur heutigen optionalen `skill-creator`-Anbindung: eine Erweiterung,
nie eine Voraussetzung. Erst sinnvoll, wenn ein Bestand die Größenordnung
erreicht, in der Stichwort-Routing nicht mehr trägt — grob ab ein paar hundert
Claims.

---

## 11. Risiken

| Risiko | Gegenmaßnahme | Abschnitt |
|---|---|---|
| Der Klassifikator erklärt alles zur Wissenslücke | Asymmetrischer Default gegen `KNOWLEDGE_GAP`, `support_count >= 2`, ein Gap pro Experiment | 7.1 |
| Erfundene Fakten mit Selbstbewusstsein | Kein Claim ohne Quelle, fail closed, Librarian darf leer ausgehen | 7.2, 7.4a |
| Eval-Antworten als „Wissen" eingetragen | train-only, Quelle nie ein Eval, mechanischer 8-Wort-Leak-Check über alle Splits | 7.4b |
| Prompt Injection über eingelesenes Material | Quellen sind Daten, Allowlist, Quarantäne, keine Ausführung, kein offener Web-Zugriff | 7.4c |
| Zugangsdaten im weitergegebenen Artefakt | Secret-Scan vor jedem Schreibvorgang | 7.4d |
| Kontext läuft über, Loop kürzt das neue Wissen wieder weg | Zwei Budgets, Seiten on demand, nur der Index zählt permanent | 7.5 |
| Auto-Lauf blockiert an einer Frage | `DEFERRED` statt Blockade, Frage in den Report, `max_deferred_per_run` | 7.2, 7.3 |
| Serie von `DEFERRED` beendet den Lauf über die Plateau-Regel | `DEFERRED` zählt nicht in Plateau und nicht in Sättigung | 7.3 |
| Wissen wirkt, ist aber nicht messbar | Zwei-Spuren-Modell, eigener Report-Abschnitt, Eval-Empfehlung | 3, 8 |
| Belegtes Wissen wird still überschrieben | Widerspruch ist `conflict`, Supersession statt Ersetzung | 7.4, 7.6 |
| Bestand verrottet unbemerkt | Hash-Nachprüfung, Nutzungsverfolgung, `status: pruefen` | 7.6 |

---

## 12. Was bewusst nicht gebaut wird

- **Keine offene Websuche.** Nicht im Auto-Modus, nicht im Guided-Modus. Nur die
  Allowlist. Ein unbeaufsichtigter Loop, der beliebige Seiten liest und deren
  Inhalt in ein weitergegebenes Artefakt schreibt, ist kein Feature.
- **Keine Embeddings, kein Vektorstore.** Für Bestände dieser Größe ist
  Stichwort-Routing über einen generierten Index ausreichend und hat den
  entscheidenden Vorteil, deterministisch und nachprüfbar zu sein.
- **Kein Wissen aus dem Modellgedächtnis**, auch nicht als markierte
  Zwischenlösung. Eine Markierung, die im Zweifel niemand liest, ist keine
  Sicherung.
- **Keine Änderung an SkillSafe.** Das Konzept wird übernommen, das Repository
  nicht angefasst. Die Formatkompatibilität ist einseitig: Skill Forge erzeugt
  etwas, das ein Tresor einlesen kann, und verlangt dafür nichts.
- **Kein automatisches Löschen von Claims** im Auto-Modus. Nur Vorschläge.

---

## 13. Offene Fragen an den Owner

1. **Wo liegt das Wissen — beim Ziel-Skill oder im Workspace?** Der Plan legt es
   zum Ziel-Skill (`<ziel>/knowledge/`), damit es mit dem Skill weitergegeben
   wird. Alternative: im Workspace, damit das Ziel-Artefakt schlank bleibt und
   Wissen bewusst separat verteilt wird. Das hat Konsequenzen für Rechte und
   Weitergabe.
2. **Darf der Loop die Ziel-SKILL.md um einen Unterbaum erweitern?** Bisher
   ändert er nur Dateien im Scope. `knowledge/` anzulegen ist eine
   Strukturerweiterung des fremden Skills.
3. **Wie viel Wissen ist zu viel?** `knowledge_budget` als 4× `token_budget` ist
   gesetzt, nicht hergeleitet.
4. **Sollen Phase 3 (freigegebene Quellen) und Phase 5 (Tresor-Aufstieg)
   überhaupt gebaut werden**, oder reicht Phase 1+2+4 — also: vorab
   bereitstellen, nachfragen, pflegen?
