---
name: skill-forge
version: 3.0.0
description: >
  Autonome Verbesserung nach dem Autoresearch-Paradigma (Karpathy). Zwei Modi:
  (1) Skill-Modus — optimiert eine SKILL.md durch iterative Mutation und Evaluation.
  (2) Generic-Modus — optimiert beliebige Dateien gegen jede mechanische Metrik
  (Testabdeckung, Bundle-Size, Lighthouse-Score, Docker-Image-Größe, etc.).
  Zwei Ausführungsmodi: Auto (vollautonomer Loop, ideal für Overnight-Runs) und
  Guided (interaktiv, User entscheidet bei jedem Schritt mit). Führt einen
  Experiment-Loop durch: analysieren → Hypothese bilden → mutieren → verifizieren →
  Score messen → keep/revert → wiederholen. Kann über Nacht als Scheduled Task
  laufen und liefert morgens einen Experiment-Report. IMMER verwenden bei: Skill
  autonom verbessern, Skill optimieren ohne manuelles Feedback, Skill optimieren
  mit Feedback, Autoresearch, autonomer Verbesserungsloop, Skill-Evolution,
  overnight optimization, Skill-Experiment, "lass den Skill über Nacht besser
  werden", Skill-Score verbessern, automatische Skill-Iteration, Code-Metrik
  verbessern, Testabdeckung erhöhen, Bundle-Size reduzieren, Performance-Score
  optimieren, beliebige Metrik optimieren, "hilf mir den Skill zu verbessern",
  Skill interaktiv verbessern, geführte Optimierung.
---

# Skill Forge

Iterative Verbesserung nach dem Autoresearch-Paradigma: Ein AI-Agent modifiziert
gezielt Dateien, evaluiert jede Änderung gegen eine mechanische Metrik, behält
Verbesserungen und verwirft Verschlechterungen.

## Ausführungsmodi

| | Auto-Modus | Guided-Modus |
|---|---|---|
| **Ablauf** | Vollautonomer Loop ohne User-Eingriff | User entscheidet an jedem Checkpoint |
| **Ideal für** | Overnight-Runs, Scheduled Tasks | Erstmalige Nutzung, Domänenwissen einbringen |
| **Evals** | Automatisch generiert | User prüft und passt an |
| **Hypothesen** | Automatisch umgesetzt | User sieht Vorschlag, kann ablehnen/anpassen |
| **Mutationen** | Automatisch angewendet | User sieht Diff, bestätigt oder korrigiert |
| **Keep/Revert** | Automatisch nach Schwellenwerten | User entscheidet mit Score als Empfehlung |
| **Wann wählen** | Vertrautes Setup, bewährte Evals | Neuer Skill, unsichere Evals, Lernmodus |

Der Wizard fragt als ersten Schritt: **"Auto oder Guided?"**

Im Guided-Modus gibt es 5 Checkpoints, an denen der User einbezogen wird:

1. **Evals prüfen** — User sieht generierte Evals, kann anpassen/ergänzen/streichen, Anzahl und Gewichtung bestimmen
2. **Hypothese prüfen** — User sieht die Hypothese und kann sie ablehnen, anpassen oder eine eigene Richtung vorgeben
3. **Mutation prüfen** — User sieht das Diff vor Anwendung und bestätigt
4. **Ergebnis bewerten** — User sieht Score + Delta und entscheidet: Keep, Revert oder manuell anpassen
5. **Weitermachen?** — User entscheidet ob eine weitere Runde laufen soll oder der Loop endet

Im Auto-Modus werden alle 5 Checkpoints übersprungen und die Entscheidungen
automatisch nach den konfigurierten Schwellenwerten getroffen.

## Zwei Domänen-Modi

| | Skill-Modus | Generic-Modus |
|---|---|---|
| **Ziel** | SKILL.md verbessern | Beliebige Dateien optimieren |
| **Metrik** | Gate-Score (Assertions, mit Comparator zusätzlich Judge) | Jede mechanische Metrik (Zahl via Shell-Command) |
| **Scope** | Eine SKILL.md + zugehörige Scripts | Dateien via Glob-Pattern |
| **Mutation** | Sprachliche Änderungen (Formulierung, Beispiele, Struktur) | Code-Änderungen (Refactoring, Config, Architektur) |
| **Eval** | Subagent-Runs mit Grading | Shell-Command mit Zahlenextraktion |
| **Anwendung** | Skill-Qualität steigern | Testcoverage, Bundle-Size, Lighthouse, Docker-Image, etc. |

Der Skill erkennt den Modus automatisch: Wenn der User einen Skill nennt, wird
Skill-Modus aktiviert. Wenn der User eine Metrik/einen Shell-Command nennt, wird
Generic-Modus aktiviert. Im Zweifel: fragen.

## Kern-Konzept

Inspiriert von Karpathys autoresearch-Paradigma:

| autoresearch (LLM)        | autoresearch (Skills/Generic)  |
|---------------------------|-------------------------------|
| `train.py` wird mutiert   | `SKILL.md` / Scope-Dateien werden mutiert |
| `prepare.py` ist fix      | Eval-Framework / Verify-Command ist fix |
| `program.md` instruiert   | Dieser Skill instruiert       |
| `val_bpb` ist die Metrik  | Composite Score / mechanische Metrik |
| 5-Min-Zeitbudget          | Token/Zeit-Budget pro Eval    |
| keep/discard              | keep/revert mit Snapshots     |

---

## Schritt 0: Setup-Wizard (einmalig)

Der Setup-Wizard führt schrittweise durch die Konfiguration. Jeder Schritt hat ein
Abnahmekriterium — der Wizard geht erst weiter, wenn die Validierung bestanden ist.

### Wizard-Schritt 1: Ausführungsmodus, Domänenmodus und Ziel erfassen

Frage den User zwei Dinge:

**1. "Auto oder Guided?"**
- **Auto**: "Ich lasse den Loop laufen und schaue mir morgens den Report an"
- **Guided**: "Ich will bei jedem Schritt mitentscheiden"
- Bei Scheduled Tasks: Immer Auto (Guided nicht möglich ohne User)

**2. "Was willst du verbessern?"**

Bestimme daraus den Domänenmodus:
- User nennt einen Skill-Namen → **Skill-Modus**
- User nennt eine Metrik, einen Shell-Command oder Code-Dateien → **Generic-Modus**
- Unklar → Nachfragen

Speichere:
```json
{
  "execution_mode": "auto" | "guided",
  "mode": "skill" | "generic",
  "goal": "Freitext-Beschreibung des Ziels",
  "target": "Skill-Name oder Projekt-Pfad"
}
```

### Wizard-Schritt 2: Scope definieren

**Skill-Modus:**
- Identifiziere die SKILL.md des Target-Skills
- Validierung: Datei existiert und ist lesbar

**Generic-Modus:**
- Frage nach Glob-Pattern für editierbare Dateien (z.B. `src/**/*.ts`)
- Validierung: Glob matcht mindestens eine Datei und höchstens `max_scope_files`
- Schliesse `node_modules`, `.git`, `dist`, `build` und `.next` aus
- Anzeigen: "Gefunden: N Dateien — [Liste der ersten 10]"
- Falls 0 Treffer → Fehlermeldung, neues Pattern verlangen
- Warnung, wenn das Ziel nicht unter Versionskontrolle steht: der Loop läuft
  stundenlang unbeaufsichtigt gegen Live-Dateien

Speichere:
```json
{
  "scope": "SKILL.md-Pfad oder Glob-Pattern",
  "scope_files_count": 42,
  "scope_validated": true
}
```

### Wizard-Schritt 3: Metrik definieren

**Skill-Modus:**
- Prüfe ob `evals/evals.json` existiert im Target-Skill
- Falls nicht: Erstelle Testfälle mit messbaren Assertions. **Mindestens 6**,
  ab **12** gibt es zusätzlich einen unabhängigen test-Split.
- Schema von `evals.json`:

```json
{
  "version": 1,
  "split_seed": 42,
  "evals": [
    {
      "id": "ki-marker-entfernung",
      "prompt": "Die Aufgabe, die der Skill lösen soll",
      "assertions": [
        {"id": "keine_gedankenstriche", "check": "Kein — als Füllwort", "weight": 1.0}
      ],
      "split": "train"
    }
  ]
}
```

- Die `id` ist ein sprechender, unveränderlicher Slug, keine laufende Nummer.
  Der Split hängt an einem Hash über diesen Slug: eine Positionsnummer würde
  beim Löschen eines Evals alle nachfolgenden verschieben, und jedes spätere
  Delta vergliche danach etwas anderes. Ein Slug umzubenennen ist ein
  Re-Baseline-Ereignis.
- Split zuweisen:

```bash
python3 scripts/composite_score.py split-assign <evals.json> --seed 42
```

  Ausgabe: Zählung pro Split, gesetzter Seed, Warnungen. Unter 12 Evals gibt es
  keinen test-Split, und die Ausgabe sagt das. Unter 6 Evals warnt sie, dass
  keine belastbare Messung möglich ist.

- Die drei Splits haben getrennte Rollen und werden nicht vermischt:

| Split | Anteil | Rolle |
|---|---|---|
| `train` | 50% | Failure-Analyse, Transcripts, Hypothesenbildung |
| `val` | 25% | Keep/Revert entscheiden. Sonst nichts. |
| `test` | 25% | Genau zweimal angefasst: Baseline vor Experiment 1 und im Report |

- Metrik = Gate-Score (automatisch)

**🔀 Guided-Checkpoint 1: Evals prüfen (nur Skill-Modus)**

Im Guided-Modus: Zeige dem User die generierten/vorhandenen Evals und frage:
- "Das sind die Testfälle. Passen sie?"
- User kann: Evals anpassen, neue hinzufügen, Gewichtung ändern, Anzahl bestimmen
- User kann auch beschreiben: "Ich will dass besonders X getestet wird"
- Erst nach User-Bestätigung wird der Train/Test-Split durchgeführt

**Generic-Modus:**
- Frage: "Welcher Shell-Command misst deine Metrik?"
- Beispiele anbieten:
  - Testabdeckung: `npx jest --coverage | grep "All files" | awk '{print $10}'`
  - Bundle-Size (KB): `npm run build 2>&1 | grep "First Load JS" | awk '{print $4}'`
  - Lighthouse: `npx lighthouse http://localhost:3000 --output json | jq '.categories.performance.score'`
  - Docker-Image (MB): `docker image inspect myapp:latest --format '{{.Size}}' | awk '{print $1/1048576}'`
  - Python-Lint-Fehler: `flake8 src/ | wc -l`
- Validierung: Subjektive Metriken ("sieht besser aus", "klingt natürlicher") werden abgelehnt.
  Die Metrik muss eine einzelne parsbare Zahl produzieren.
- **Zwei Pflichtfragen, ohne die der Loop nicht startet:**
  1. "Welche Pfade darf der Loop nie ändern?" Das sind Metrik- und
     Test-Konfiguration, nicht die gemessenen Quelldateien. Vorschlagsliste aus
     dem Repo-Root: `.flake8`, `setup.cfg`, `pyproject.toml`, `tox.ini`,
     `jest.config.*`, `package.json`, `tsconfig.json`, `.eslintrc*`,
     `lighthouserc*`, `Dockerfile`, plus alles unter `tests/`, `__tests__/`,
     `spec/`. `protected_paths` und der Scope-Glob dürfen sich nicht
     überschneiden.
  2. "Welcher Command muss nach der Mutation noch grün sein?" Meist die
     Testsuite. Bei langsamen Suiten darf der User ein Subset angeben, aber
     nicht abschalten, sonst ist der Schutz weg.

  Warum das nicht optional ist: die optimale Mutation für `flake8 src/ | wc -l`
  ist, `src/` zu löschen. Für Jest-Coverage: die ungedeckten Tests entfernen
  oder `coverageThreshold` senken. Für Bundle-Size: Features rauswerfen. Alle
  drei verbessern die Zahl und verschlechtern die Software. Der Exit-Code fängt
  nichts davon ab, bei `flake8 src/ | wc -l` ist er ohnehin immer der von `wc`.
- Hinweis: Der Metrik-Parser extrahiert die **letzte Zahl** im Command-Output.
  Falls der Command Fortschrittsmeldungen oder Zeilennummern ausgibt, sollte
  der User den Output so filtern, dass nur die relevante Zahl am Ende steht
  (z.B. mit `| tail -1` oder `| grep "Score"`).


Speichere:
```json
{
  "metric_name": "test_coverage_percent",
  "metric_command": "npx jest --coverage | grep 'All files' | awk '{print $10}'",
  "metric_direction": "higher_is_better" | "lower_is_better"
}
```

### Wizard-Schritt 4: Richtung festlegen

Frage: **"Ist ein höherer oder niedrigerer Wert besser?"**

- Testabdeckung → höher ist besser
- Bundle-Size → niedriger ist besser
- Lint-Fehler → niedriger ist besser
- Performance-Score → höher ist besser

Im Skill-Modus ist die Richtung immer `higher_is_better` (automatisch).

### Wizard-Schritt 5: Dry-Run-Validierung

Dieser Schritt ist ein harter Gate — der Loop startet erst, wenn er bestanden ist.

**Skill-Modus:**

Vor dem Dry-Run: zeige die Auflösungsgrenze an.

```bash
python3 scripts/composite_score.py resolution --assertions <N über alle val-Evals>
```

Bei 9 Assertions sind das 0.222, bei 31 noch 0.065. Das ist die kleinste
Differenz, die überhaupt etwas bedeuten kann, denn der Gate-Score ist exakt die
Assertion-Pass-Rate und springt in Schritten von 1/N. Sag dem User die Zahl
und was sie heißt: "Auflösungsgrenze 0.065. Änderungen unterhalb dieses Werts
sind mit diesem Eval-Set nicht messbar." Liegt sie über 0.15, verlange mehr
Evals, bevor der Loop startet.

1. Wähle ein Eval aus dem Trainings-Set
2. Führe einen einzelnen Eval-Run mit der aktuellen SKILL.md durch
3. Prüfe: Grading produziert valides JSON mit `passed`/`total` Feldern
4. Prüfe: `python3 scripts/composite_score.py score <exp-dir> --side with_mutation --json`
   liefert eine Zahl in `composite_score` (zwischen 0 und 1) und beendet sich mit
   Exit 0. Bei Exit 2 wurden keine Gradings gefunden, dann stimmt der Pfad oder das
   Verzeichnislayout nicht.
5. Speichere Baseline-Score

**Generic-Modus:**
1. Führe den Metrik-Command aus
2. Prüfe: Exit-Code ist 0
3. Prüfe: Output enthält eine parsbare Zahl
4. Speichere Baseline-Wert

**Bei Fehler:**
- Zeige dem User die genaue Fehlermeldung
- Biete Korrekturvorschläge an (falscher Pfad, fehlende Dependency, falsches Parsing)
- Wiederhole den Dry-Run nach Korrektur
- Erst nach erfolgreichem Dry-Run geht es weiter

Speichere:
```json
{
  "dry_run_passed": true,
  "baseline_value": 72.5,
  "dry_run_output": "Vollständiger Output des Commands",
  "dry_run_timestamp": "2026-03-14T21:45:00Z"
}
```

### Wizard-Schritt 6: Konfiguration bestätigen

Zeige dem User die vollständige Konfiguration:

```
═══════════════════════════════════════
  Skill Forge — Konfiguration
═══════════════════════════════════════
  Modus:          Skill / Generic
  Ziel:           [Freitext]
  Scope:          [Pfad / Glob] (N Dateien)
  Metrik:         [Name] via [Command]
  Richtung:       Höher/Niedriger ist besser
  Baseline:       [Wert]
  Max Experimente: 10
  Zeitbudget:     120 min
═══════════════════════════════════════
  [Start] [Bounded: N Iterationen] [Abbrechen]
```

Der User kann Parameter anpassen oder den Loop starten.

### Workspace anlegen

Nach Bestätigung:

```
<target>-skill-forge/
├── config.json            # Wizard-Konfiguration
├── evals.json             # Testfälle (nur Skill-Modus)
├── history.json            # Fortschritts-Tracking (mit Tiered Compaction)
├── history.archive.jsonl   # Volldatensätze der komprimierten Experimente
├── rejected.jsonl          # Nicht-KEEP im Wortlaut, kompaktierungsfest
├── editing-notes.md        # Meta-Memory des Optimierers, alle 5 Experimente
├── checkpoint.json         # Resume-Point für Session-Übergreifendes Fortsetzen
├── experiment-log.tsv      # Flaches Log für schnelles Monitoring
├── coverage-matrix.json    # Experiment-Abdeckung
├── snapshots/
│   ├── pre-exp-001/        # Zustand vor Experiment 1 (Baseline)
│   └── pre-exp-002/        # Zustand vor Experiment 2
├── experiments/
│   └── exp-001/
└── morning-report.md       # Zusammenfassung für den User
```

Snapshot-Verzeichnisse heißen `pre-exp-NNN`, nicht `v0`/`v1`. `pre-exp-007` ist
eindeutig der Zustand VOR Experiment 7. Das Feld `version` in `history.json` zählt
dagegen die behaltenen Versionen (`v0`, `v1`, ...), beides ist nicht dasselbe und
soll sich auch nicht mehr gleich schreiben.

Speichere die Baseline:
```bash
python3 scripts/composite_score.py snapshot \
  --target <scope-pfad-oder-glob> \
  --snapshot-dir <workspace>/snapshots \
  --version pre-exp-001
```
- Schreibe den Baseline-Score in `history.json`
- Initialisiere das TSV-Log:
  `python3 scripts/composite_score.py tsv-init <workspace>/experiment-log.tsv`
- Initialisiere die Coverage-Matrix:
  `python3 scripts/composite_score.py coverage-init <workspace>/coverage-matrix.json`

---

## Arbeitsverzeichnis

Alle `python3 scripts/composite_score.py ...`-Aufrufe in diesem Dokument sind
relativ zum Skill-Verzeichnis geschrieben. Ein Scheduled Task startet mit einem
cwd, den niemand kennt. Setze deshalb einmal zu Beginn des Laufs einen absoluten
Pfad und verwende ihn danach durchgehend:

```bash
FORGE=/absoluter/pfad/zu/skill-forge
python3 "$FORGE/scripts/composite_score.py" --version
```

Für `pytest` gilt dasselbe umgekehrt: die Tests laufen nur aus dem Repo-Root,
weil `conftest.py` dort liegt und das Import-Präfix setzt.

---

## Der Experiment-Loop

### Schritt 0.5: Resume-Check (vor dem ersten Experiment)

Prüfe ob ein Checkpoint existiert:

1. Lies `checkpoint.json` im Workspace (falls vorhanden), oder
   `python3 scripts/composite_score.py checkpoint-info <workspace>`
2. Falls Checkpoint gefunden:
   - **Zuerst `applied_but_undecided` prüfen.** Ist das Feld `true`, ist der letzte Lauf
     zwischen Mutation und Entscheidung abgebrochen. Die Zieldatei liegt dann mutiert auf
     der Platte, aber niemand hat sie gemessen. Rolle vor allem anderen zurück:
     ```bash
     python3 scripts/composite_score.py revert \
       --snapshot-dir <workspace>/snapshots \
       --version <checkpoint.on_disk_version>
     ```
     Ohne diesen Schritt misst das Resume eine mutierte Datei und hält sie für die Baseline.
   - Zeige dem User: "Resume von Checkpoint: Experiment {N}, Score {X}, Coverage {Y}%"
   - Setze `current_baseline` aus `current_baseline_score`, `current_best` aus
     `best_version`/`best_score`
   - Zähle ab `experiment_index` weiter (nicht bei 1 beginnen)
3. Falls kein Checkpoint: Normaler Start bei `pre-exp-001`/Baseline

Nach JEDEM abgeschlossenen Experiment: Speichere einen Checkpoint.

```bash
python3 scripts/composite_score.py checkpoint-save <workspace> \
  --experiment exp-003 \
  --baseline 0.78 \
  --coverage-path <workspace>/coverage-matrix.json \
  --next-category edge_cases \
  --on-disk-version pre-exp-003 \
  --best-version pre-exp-002 \
  --best-score 0.84 \
  --experiment-index 3
```

`--on-disk-version` ist die Snapshot-Version, auf die zurückgerollt werden muss, wenn
der Lauf zwischen Mutation und Entscheidung abbricht. Für Experiment N ist das
`pre-exp-N`, der Snapshot vor genau diesem Experiment.

Nach einem KEEP beschreibt keine Snapshot-Version den Plattenstand: der mutierte Stand
wird erst zu Beginn des nächsten Experiments als `pre-exp-(N+1)` gesichert. Das Feld ist
deshalb nur zusammen mit `applied_but_undecided` handlungsleitend. Ein Resume darf nicht
defensiv darauf zurückrollen, sonst verwirft es den KEEP. Direkt NACH dem Anwenden einer Mutation und VOR der Entscheidung wird
zusätzlich `--applied-but-undecided` gesetzt; nach der Entscheidung wird ohne dieses
Flag neu gespeichert. Das ist der Anker, an dem Punkt 2 hängt.

Verwechslungsgefahr: `pre-exp-NNN` bezeichnet immer den Zustand VOR Experiment NNN.
Eine Version mit einer höheren Nummer als das zuletzt abgeschlossene Experiment
existiert noch nicht, und `revert` würde darauf mit Exit 2 abbrechen.

### Schritt 0.7: History-Compaction (vor Agent-Aufrufen)

Bei mehr als 5 abgeschlossenen Experimenten: Komprimiere die History:

1. Rufe `python3 scripts/composite_score.py compact <history-path> --keep 5` auf
2. Die letzten 5 Experimente behalten vollständige Details
3. Die Volldatensätze wandern vorher nach `<workspace>/history.archive.jsonl`.
   Das Anhängen ist idempotent, mehrfaches Kompaktieren dupliziert nichts.
4. Ältere Einträge werden auf `{id, version, category, mutation_type,
   composite_score, delta, decision, near_miss, timestamp}` reduziert.
   `mutation_type` und `near_miss` bleiben bewusst erhalten: ohne sie sieht der
   Hypothesis-Agent zwar, dass eine Kategorie mehrfach reverted wurde, aber
   nicht mehr, welche Art von Änderung das war.
5. Das verhindert Context-Overflow bei langen Runs (>10 Experimente)

### Schritt 0.8: Dynamic Context Assembly

Vor jedem Agent-Aufruf wird der Agent-Prompt dynamisch angereichert:

1. Lade `templates/agent_context.md` als Template
2. Fülle es mit aktuellen Daten:
   - Aktuelle Runde, Phase (Exploration/Balanced/Exploitation), Trend
   - Letzte 3 Experiment-Ergebnisse (vollständig)
   - Coverage-Matrix als Tabelle
   - Der Block aus `rejected-format <workspace>/rejected.jsonl --limit 10`,
     also die bereits verworfenen Versuche im Wortlaut. Near-Misses sind darin
     als Teilmenge markiert.
3. Hänge den gefüllten Context an den jeweiligen Agent-Prompt an
4. Context-Budget-Regel: Max 30% des Agent-Contexts für History, Coverage,
   Meta-Notizen und den Rejected-Block. 70% für die aktuelle Aufgabe.

**Diese Regel gilt nicht für die Transcripts des aktuellen Experiments.**
Komprimiere das Artefakt, nie die Evidenz. Die naheliegende Sparmassnahme ist,
lange Transcripts vor der Analyse zusammenzufassen; SkillOpt hat die
Längenbegrenzung an dieser Stelle bewusst ausgebaut und den Parameter nur aus
Kompatibilität stehen lassen:

> Truncation is disabled: the optimizer is given the full content so it can see
> exactly what the agent saw/did.

Gekürzte Transcripts erzeugen plausible, aber falsche Ursachenanalysen, und aus
einer falschen Ursache wird eine Regel, die das Gate nicht bewegt und trotzdem
Platz kostet. Wenn der Context knapp wird, kürze die History, nicht die
Transcripts.

Für die kategorisierte History-Sicht nutze:
`scripts/composite_score.py group-history <history-path>`

Dies liefert pro Kategorie: beste Mutation, Erfolgsrate, Sättigungsstatus —
deutlich informativer als eine chronologische Liste.

### Schritt 1: Hypothese bilden

Lies den `agents/hypothesis.md` Agent-Prompt und folge seinen Anweisungen:

1. Analysiere die Eval-Ergebnisse der letzten Iteration, **ausschliesslich aus
   dem train-Split**:
   `python3 scripts/composite_score.py split-assign <evals.json> --seed <split_seed> --dry-run`
   Ohne `--seed` rechnet der Befehl immer mit 42 und zeigt bei jedem anderen
   konfigurierten Seed eine andere Zuordnung als die in evals.json gespeicherte.
   Am einfachsten liest du das Feld `split` direkt aus evals.json.
   zeigt die Zuordnung. Die Ergebnisse aus val und test fliessen NICHT in die
   Hypothesenbildung. Sonst ist der Holdout kein Holdout mehr, und das Delta
   misst, wie gut der Loop die eigenen Testfälle auswendig gelernt hat.
2. Konsultiere die **Coverage-Matrix** (siehe unten) — priorisiere unterversorgte Bereiche
3. Identifiziere die schwächsten Bereiche (welche Assertions/Metriken failen?)
4. Lies die Transcripts der fehlgeschlagenen train-Runs (Skill-Modus) oder den
   Command-Output (Generic-Modus). Transcripts aus val und test bleiben zu.
5. Klassifiziere jedes Failure-Pattern als `SKILL_DEFECT` oder
   `EXECUTION_LAPSE` (agents/hypothesis.md, Abschnitt 2c). Im Zweifel LAPSE.
   LAPSE-Befunde erzeugen keine Mutation, sondern `appendix_notes`.
6. Sieh dir auch die bestandenen train-Evals an. Die `success_patterns` sind die
   Schutzliste, die den Mutator davon abhält, tragende Abschnitte zu prunen.
7. Formuliere DREI Kandidaten, ranke sie nach der Rubrik in
   agents/hypothesis.md Abschnitt 5.5 und wende genau einen an. Drei Kandidaten
   kosten keinen zusätzlichen Agent-Aufruf.
8. Formuliere die gewählte Hypothese konkret und testbar:
   - **Skill-Modus**: "Die Anweisung X ist zu vage → Agent weicht ab → Assertion Y failt"
   - **Generic-Modus**: "Funktion X allokiert unnötig → Speicher steigt → Metrik verschlechtert sich"
6. Priorisiere: Fokus auf die Änderung mit dem höchsten erwarteten Impact

**Wichtig:** Generalisiere! Nicht auf einzelne Testfälle optimieren, sondern auf
die zugrunde liegenden Muster.

**🔀 Guided-Checkpoint 2: Hypothese prüfen**

Im Guided-Modus: Zeige dem User die Hypothese und frage:
- "Soll ich diese Hypothese testen?"
- Optionen: **Ja** / **Anpassen** (User gibt Richtung vor) / **Andere Idee** (User beschreibt eigene Hypothese) / **Überspringen** (nächste Kategorie)
- Falls der User eine eigene Hypothese formuliert, verwende diese statt der generierten.

### Schritt 2: Mutation anwenden

Lies den `agents/mutator.md` Agent-Prompt und folge seinen Anweisungen:

1. Sichere den aktuellen Zustand, bevor irgendetwas geschrieben wird:
   ```bash
   python3 scripts/composite_score.py snapshot \
     --target <scope-pfad-oder-glob> \
     --snapshot-dir <workspace>/snapshots \
     --version pre-exp-<NNN>
   ```
   `<NNN>` ist die Nummer des Experiments, das gleich läuft, dreistellig mit führenden
   Nullen. Der Befehl legt fehlende Verzeichnisse selbst an, löst Globs auf und schreibt
   ein `manifest.json` mit der Dateiliste. Das Manifest ist die Voraussetzung dafür, dass
   `revert` später auch Dateien wieder entfernen kann, die die Mutation neu angelegt hat.
2. Wende die Hypothese als gezielte Änderung an:
   - **Skill-Modus**: Formulierungen, Beispiele, Struktur, Scripts
   - **Generic-Modus**: Code-Refactoring, Config-Änderungen, Architektur
3. Mache **eine fokussierte Änderung** pro Experiment (nicht 5 gleichzeitig)
   - Das ist entscheidend: Nur so weißt du, welche Änderung den Score beeinflusst hat
4. Dokumentiere die Änderung im Experiment-Log
4.5. **Generic-Modus: Ausgangszustand der Invarianten festhalten.** Das
   passiert HIER, vor der Mutation, nicht in Schritt 3. Ein Snapshot nach der
   Mutation vergliche den mutierten Zustand mit sich selbst, und der
   Reward-Hacking-Schutz könnte nie anschlagen.

```bash
python3 scripts/composite_score.py invariants-snapshot \
  --scope "<scope-glob>" \
  --protected <protected_paths...> \
  --out <workspace>/experiments/exp-<NNN>/invariants.json
```

   Löst ein angegebener geschützter Pfad zu keiner Datei auf, bricht der Befehl
   ab. Ein Schutz, der nichts schützt, sieht im Log aus wie einer.

5. **Geschützte Regionen prüfen:**

```bash
python3 scripts/composite_score.py verify-regions \
  <workspace>/snapshots/pre-exp-<NNN>/files/SKILL.md \
  <ziel-SKILL.md>
```

   Exit 1 heisst: eine geschützte Region wurde geändert, gelöscht oder neu
   angelegt. Dann Snapshot zurückspielen, Decision `INVALID`, nächste
   Hypothese. Der Check läuft in Python, nicht als Punkt auf der Sanity-Liste
   des Mutators: ein Agent, der eine Regel nicht befolgt hat, per Prompt prüfen
   zu lassen, ob er sie befolgt hat, ist zirkulär.

6. **Diff erzeugen und auf Wirkung prüfen:**

```bash
python3 scripts/composite_score.py diff \
  --snapshot-dir <workspace>/snapshots \
  --version pre-exp-<NNN> \
  --out <workspace>/experiments/exp-<NNN>/mutation.diff
```

   Liefert `changed`, `lines_added`, `lines_removed`, `files_changed`,
   `files_added`, `files_deleted`. Bei `changed: false` ist die Entscheidung
   `NO_OP`: kein Eval-Run, kein Scoring, keine Coverage-Aktualisierung, weiter
   zur nächsten Hypothese. Ein Experiment ohne Byte-Änderung liefert per
   Konstruktion Delta null und darf nicht als Neutralergebnis in die Statistik
   gehen.

6. Speichere einen Checkpoint mit `--on-disk-version pre-exp-<NNN>` und
   `--applied-but-undecided`, solange die Entscheidung noch aussteht

**🔀 Guided-Checkpoint 3: Mutation prüfen**

Im Guided-Modus: Zeige dem User `mutation.diff` und frage:
- "So sieht die Änderung aus. Behalten und messen?"
- Optionen: **Ja, messen** / **Anpassen** (User korrigiert) / **Verwerfen**
- Der Checkpoint liegt NACH der Anwendung und vor der Messung. Bei "Verwerfen"
  stellt der Loop aus `snapshots/pre-exp-<NNN>/` wieder her, bevor er zur
  nächsten Hypothese geht.

### Schritt 3: Experiment laufen lassen

**Skill-Modus:**

Für jedes Eval im **val-Split**:
1. Spawne einen Subagent mit der mutierten SKILL.md und dem Eval-Prompt
2. Spawne parallel einen Baseline-Subagent mit der besten SKILL.md
3. Grade jedes Ergebnis mit dem Scorer-Agent (`agents/scorer.md`). Einen
   Grader-Agent gibt es nicht; der Scorer schreibt sowohl `grading.json` pro Lauf
   als auch, bei aktiviertem Comparator, `comparison.json` pro Experiment
4. Speichere `grading.json` pro Run, und zwar in genau dieser Struktur:

```
experiments/exp-003/
├── runs/
│   ├── eval-0/
│   │   ├── with_mutation/
│   │   │   ├── grading.json
│   │   │   └── timing.json
│   │   └── baseline/
│   │       ├── grading.json
│   │       └── timing.json
│   └── eval-1/
│       ├── with_mutation/
│       └── baseline/
└── comparison.json          # nur mit use_comparator
```

Eval-Verzeichnisse werden ab `eval-0` nummeriert. Ein `outputs/`-Unterverzeichnis
je Seite ist erlaubt und wird vom Scoring gefunden; `agents/scorer.md` setzt dessen
Inhalt als Judge-Input voraus.

Die Verzeichnisnamen `with_mutation` und `baseline` sind nicht kosmetisch: `score --side`
matcht wörtlich darauf. Heißt der Ordner anders, findet das Scoring nichts und bricht mit
Exit 2 ab.

**Generic-Modus:**

1. Führe den Metrik-Command aus, aber mit dem Invarianten-Nachweis:

```bash
<metrik-command> | python3 scripts/composite_score.py metric - \
  --baseline <wert> --direction <richtung> \
  --invariants-before <workspace>/experiments/exp-<NNN>/invariants.json \
  --invariant-command "<invariant_command>"
```

   Ohne bestandene Prüfung liefert der Befehl keinen Metrikwert, sondern
   `{"decision": "INVALID"}` und Exit 3. Das ist Absicht: sonst könnte der
   Loop den Check überspringen und trotzdem eine Zahl bekommen.

2. Bei INVALID: Snapshot zurückspielen, Decision `INVALID` loggen, Kategorie im
   Coverage-Log als riskant vermerken, kein Score-Eintrag, nächste Hypothese.
3. Prüfe: Exit-Code 0 und Zahl extrahierbar
4. Bei Crash des Commands: Vermerke `"crash": true` in `decision.json` und in der
   History, versuche einmal zu fixen, bei erneutem Crash → Decision `SKIP` und
   nächste Hypothese. `CRASH` ist kein Entscheidungswert: `tsv-append` und
   `coverage-update` akzeptieren nur KEEP, REVERT, NEUTRAL, SKIP, NO_OP und
   INVALID.

### Schritt 4: Score berechnen

**Skill-Modus:**

Beide Seiten werden getrennt bewertet, jede mit ihrem eigenen `--side`:

```bash
python3 scripts/composite_score.py score <workspace>/experiments/exp-003 \
  --side with_mutation --config <workspace>/config.json --json
python3 scripts/composite_score.py score <workspace>/experiments/exp-003 \
  --side baseline --config <workspace>/config.json --json
```

Der erste Aufruf liefert den Kandidaten-Score, der zweite den Baseline-Score. Ohne
`--side` sammelt das Scoring beide Seiten ein und mittelt sie zu einer Zahl, über die
niemand entscheiden kann. Findet der Befehl kein einziges Grading, bricht er mit Exit 2
ab statt stillschweigend 0.0 zu liefern.

Die Ausgabe enthält `total_assertions` und daraus abgeleitet `resolution`. Diese
Zahl geht in Schritt 5 als `--resolution` in die Entscheidung ein.

**Längsvergleich, bevor entschieden wird:**

```bash
python3 scripts/composite_score.py compare <workspace>/experiments/exp-003
```

Vergleicht dieselben Evals unter beiden Versionen und sortiert nach
`regressed`, `persistent_fail`, `improved`, `stable_success`. Regressionen
stehen zuerst, weil ein Aggregatscore sie verschluckt: fünf neue Treffer und
drei neue Fehler ergeben netto plus zwei und sehen wie Fortschritt aus. Der
Block gehört in den Morning Report und in den Context der nächsten Runde.

Gewichtung des Gate-Scores:

```
ohne Comparator:  composite = assertion_pass_rate * 1.00
mit Comparator:   composite = assertion_pass_rate * 0.65 + llm_judge_score * 0.35
```

`--config` überschreibt diese Defaults mit `gate_weights` aus der config.json. Die
Gewichte müssen sich zu 1.0 summieren, sonst bricht der Befehl ab. Ein Eintrag
`efficiency` mit einem Wert ungleich 0 wird ebenfalls abgelehnt: Effizienz gehört
nicht mehr ins Gate, und sie soll auch nicht über die Konfiguration zurückkommen.

Effizienz ist kein Bestandteil des Gates mehr. Sie wird weiterhin berechnet und steht
unter `details.efficiency_score`, entscheidet aber nichts. Grund: zwischen zwei Läufen mit
identischen Assertions schwankte der Efficiency-Anteil um bis zu 0.045, also stärker als
die Keep-Schwelle von 0.02. Ein Gate, dessen Rauschen größer ist als sein Signal, misst
die Laune der Maschine, nicht die Mutation. Der Wert gehört in den Morning Report, nicht
in die Entscheidung.

**Generic-Modus:**

```python
# Direkte Metrik-Auswertung
current_value = extract_metric_value(command_output)
delta = current_value - baseline_value
# Bei lower_is_better: delta wird invertiert
improved_raw = (delta > 0) if direction == "higher_is_better" else (delta < 0)
```

### Schritt 5: Keep oder Revert

Die Entscheidung wird nicht im Kopf gerechnet, sondern vom Script gefällt. Das ist die
einzige Stelle im Projekt, an der aus zwei Zahlen ein KEEP oder REVERT wird:

```bash
python3 scripts/composite_score.py decide \
  --candidate 0.84 \
  --baseline 0.78 \
  --config <workspace>/config.json \
  --resolution <resolution aus Schritt 4>
```

Ausgabe ist JSON mit `decision`, `near_miss`, `delta`, `threshold`,
`improvement_threshold`, `regression_threshold`, `noise_floor`, `direction`, `relative`,
`relative_fallback` und `formula`. Das Feld `formula` ist ein lesbarer String, der die konkrete Rechnung
zeigt; er gehört unverändert in `decision.json`, damit später nachvollziehbar ist, warum
eine Runde so ausgegangen ist.

`relative_fallback` steht auf `true`, wenn `--relative` gesetzt war, die Baseline
aber 0 ist. Dann rechnet `decide` mit dem absoluten Delta weiter, weil ein
relatives Delta auf einer Nullbaseline nicht definiert ist. Wer decision.json
auswertet, muss dieses Feld lesen: das Delta bedeutet dort etwas anderes.

Weitere Argumente: `--direction higher_is_better|lower_is_better`, `--relative` (Delta
relativ zur Baseline, der sinnvolle Modus im Generic-Modus, wo die Metrik in KB oder
Sekunden misst und eine absolute Schwelle von 0.02 nichts bedeutet), `--noise-floor`.
Werte aus `config.json` gewinnen über die Argparse-Defaults.

**Drei Ausgänge, kein vierter:**

| Ausgang | Bedingung | Wirkung |
|---|---|---|
| `KEEP` | `delta > max(improvement_threshold, noise_floor, resolution)` | Mutierte Version wird neue Baseline |
| `REVERT` | `delta < -regression_threshold` | Zurück zum Snapshot |
| `NEUTRAL` | alles dazwischen, inklusive Gleichstand | Zurück zum Snapshot |

Drei weitere Werte kommen nicht aus `decide`, sondern aus dem Ablauf drumherum und
sind in `tsv-append` und `coverage-update` erlaubt:

| Wert | Wann |
|---|---|
| `SKIP` | Agent-Output nicht verwertbar, Command zweimal gecrasht, Experiment nicht zu Ende gebracht |
| `INVALID` | Eine Invariante wurde verletzt, das Ergebnis ist nicht vergleichbar |
| `NO_OP` | Die Mutation hat byteweise nichts geändert. Erzeugt in Schritt 2 aus `diff` mit `changed: false`; kein Eval-Run, kein Scoring |

Alle drei zählen nicht in die Sättigung und nicht in `best_delta`.

Bei `REVERT` und bei `NEUTRAL` wird derselbe Befehl ausgeführt:

```bash
python3 scripts/composite_score.py revert \
  --snapshot-dir <workspace>/snapshots \
  --version pre-exp-<NNN>
```

`revert` stellt aus dem Manifest wieder her und löscht zusätzlich Dateien im Scope, die
nicht im Manifest stehen, also genau die, die die Mutation neu angelegt hat.

Schwellenwerte:
- `improvement_threshold = 0.02` (Verbesserung nötig zum Behalten)
- `regression_threshold = 0.05` (Verschlechterung → sofort revert)
- `near_miss_band = 0.02` (Breite des Bands knapp unterhalb der Keep-Schwelle)
- `noise_floor = 0.0` (Messrauschen; die effektive Keep-Schwelle ist das Maximum aus
  beiden)

**Warum NEUTRAL jetzt zurückrollt.** Die alte Kaskade hatte vier Zweige, und der
NEUTRAL-Zweig war unerreichbar: die NEAR_MISS-Bedingung deckte bereits das gesamte Band
zwischen Revert- und Keep-Schwelle ab, `else` wurde praktisch nie erreicht. Über 4001
gleichverteilte Deltas in [-0.20, +0.20] fiel die alte Regel 1800 mal auf KEEP, 1500 mal
auf REVERT, 700 mal auf NEAR_MISS und genau ein einziges Mal auf NEUTRAL. Die Regel
"NEUTRAL → Keep, bei Gleichstand leichte Präferenz für Neues" ist damit gestrichen, und
zwar aus zwei Gründen: sie feuerte ohnehin nie, und wäre sie erreichbar gewesen, hätte
sie den Skill über zehn Null-Runden ohne jede gemessene Verbesserung vom Ausgangspunkt
weggetragen. Gleichstand ist kein Argument, etwas Neues zu behalten. Keine lateralen
Züge.

**Near-Miss ist ein Flag, kein Ausgang.**

`near_miss` ist ein Boolean auf einer NEUTRAL-Entscheidung. Es ist `true`, wenn
`delta > threshold - near_miss_band`, also wenn die Mutation im Band knapp unter der
Keep-Schwelle liegt. Der Code wird trotzdem zurückgesetzt, aber die Hypothese wird in
`decision.json` als `"near_miss": true` markiert. Der Hypothesis Agent bekommt diese
Information in der nächsten Runde und kann:
- Die gleiche Hypothese mit einem anderen Ansatz erneut versuchen
- Die Hypothese mit einer komplementären Mutation kombinieren
- Die Hypothese verwerfen, wenn bereits 2 Near-Misses in der gleichen Kategorie

**🔀 Guided-Checkpoint 4: Ergebnis bewerten**

Im Guided-Modus: Zeige dem User Score + Delta und die automatische Empfehlung:
- "Score: 0.78 → 0.84 (+0.06). Empfehlung: KEEP. Einverstanden?"
- Optionen: **Keep** / **Revert** (trotz Verbesserung zurück) / **Manuell anpassen** (User ändert die Mutation von Hand)
- Der User kann also die automatische Entscheidung überstimmen — z.B. KEEP obwohl
  der Score leicht gefallen ist, weil er weiß, dass die Änderung langfristig besser ist.

**Nach jeder Entscheidung — zwei Logs aktualisieren:**

1. **history.json** (strukturiert, für programmatische Auswertung):
```json
{
  "id": "exp-003",
  "version": "v3",
  "parent": "v2",
  "hypothesis": "Beispiel für Edge-Case X hinzugefügt",
  "mutation_type": "instruction_edit",
  "composite_score": 0.78,
  "baseline_score": 0.72,
  "delta": 0.06,
  "decision": "KEEP",
  "near_miss": false,
  "category": "edge_cases",
  "details": {
    "assertion_pass_rate": 0.78,
    "llm_judge_score": null,
    "efficiency_score": 0.72
  }
}
```

Ohne Comparator ist `composite_score` identisch mit `assertion_pass_rate`, deshalb stehen
hier zweimal 0.78. `efficiency_score` steht zur Information dabei und geht nicht in den
Score ein. `near_miss` kommt direkt aus der `decide`-Ausgabe und überlebt die
History-Kompaktierung.

2. **experiment-log.tsv** (flach, eine Zeile pro Experiment, für schnelles Monitoring):
```
timestamp	experiment	hypothesis_summary	metric_before	metric_after	delta	decision	category	duration_s
2026-03-14T22:15:00Z	exp-001	Hook-Beispiel hinzugefügt	0.62	0.71	+0.09	KEEP	examples	180
2026-03-14T22:28:00Z	exp-002	Workflow-Schritt für Validation	0.71	0.68	-0.03	NEUTRAL	workflow	195
2026-03-14T22:45:00Z	exp-003	Edge-Case X Beispiel	0.71	0.78	+0.07	KEEP	edge_cases	210
```

Das TSV-Format ermöglicht schnelles Scannen mit `cat`, `grep`, `tail -f` oder `awk` —
besonders nützlich für nächtliche Runs, wo man sofort sehen will ob der Loop produktiv war.

Beide Logs werden über Subcommands geschrieben, nicht von Hand:

```bash
python3 scripts/composite_score.py tsv-append <workspace>/experiment-log.tsv \
  --experiment exp-003 \
  --hypothesis "Validation-Schritt in den Workflow eingefügt" \
  --before 0.72 --after 0.78 \
  --decision KEEP \
  --category workflow \
  --duration 210 \
  --direction higher_is_better

python3 scripts/composite_score.py coverage-update <workspace>/coverage-matrix.json \
  --category workflow \
  --experiment exp-003 \
  --decision KEEP \
  --delta 0.06 \
  --direction higher_is_better
```

`--direction` gehört im Generic-Modus zwingend dazu. Ohne die Angabe schreibt das
TSV bei `lower_is_better` für jede Verbesserung ein negatives Delta, und die
Coverage-Matrix führt die schlimmste Regression als Bestwert.

`--decision` akzeptiert nur die sechs Werte aus der Tabelle oben. Ein Tippfehler
bricht ab, statt still in keiner Spalte zu landen.

3. **Coverage-Matrix aktualisieren** (siehe unten)

3.5. **Artefaktgrösse prüfen:**

```bash
python3 scripts/composite_score.py artifact-stats \
  <ziel-SKILL.md> "<ziel-verzeichnis>/references/*.md" "<ziel-verzeichnis>/scripts/*" \
  --budget <token_budget>
```

   Exit 1 heisst: Budget überschritten. Dann setzt der Orchestrator
   `forced_category: "efficiency"` und `forced_mutation_type: "prune"` für die
   nächste Runde, bis das Budget wieder eingehalten wird.

   Der Scope umfasst bewusst mehr als die SKILL.md. Ein Budget, das nur die
   Hauptdatei zählt, ist über `reference_add` in einer Runde umgangen, und zwar
   durch genau den Mutationstyp, den der Loop unter Budgetdruck naheliegend
   wählt.

4. **Bei jedem Nicht-KEEP: den Versuch wörtlich fortschreiben.**

```bash
python3 scripts/composite_score.py rejected-append \
  <workspace>/rejected.jsonl \
  --from-json <workspace>/experiments/exp-<NNN>/decision.json
```

   Erfasst werden REVERT und NEUTRAL, nicht nur Near-Misses: eine deutliche
   Regression ist mindestens so lehrreich wie ein Beinahe-Treffer. Die Datei
   liegt bewusst neben der History, weil die Kompaktierung sie sonst kürzt.

5. **LAPSE-Notizen anhängen, als LETZTEN Schreibvorgang des Schritts.**

```bash
python3 scripts/composite_score.py appendix-append \
  <ziel-SKILL.md> \
  --from-json <workspace>/experiments/exp-<NNN>/hypothesis.json
```

   Die Reihenfolge ist kein Detail: REVERT und NEUTRAL spielen den Snapshot
   zurück und ersetzen die Datei komplett. Wer die Notiz vorher schreibt,
   verliert sie bei jeder Nicht-KEEP-Runde.

   Der Appendix ist in beiden Armen des nächsten Experiments präsent, Kandidat
   wie Baseline. Die Differenz misst also weiterhin nur die Mutation, solange
   der Append zwischen zwei Experimenten passiert und nicht mittendrin.

### Schritt 6: Wiederholen

Gehe zurück zu Schritt 1 mit der neuen Baseline.

**🔀 Guided-Checkpoint 5: Weitermachen?**

Im Guided-Modus: Zeige dem User den bisherigen Fortschritt (Score-Verlauf, Coverage) und frage:
- "Runde N abgeschlossen. Score: 0.62 → 0.84. Weitermachen?"
- Optionen: **Ja, weiter** / **Noch N Runden** (User gibt Anzahl an) / **Stopp, Report generieren**
- Der User kann den Loop also jederzeit beenden, auch vor max_experiments.

**Abbruchkriterien (Auto-Modus und als Empfehlung im Guided-Modus):**
- `composite_score >= 0.95` (Skill-Modus) oder Zielwert erreicht (Generic-Modus) → Ziel erreicht
- `max_experiments` erreicht (Standard: 10)
- 3 aufeinanderfolgende Nicht-KEEP → Plateau erreicht. Prüfen mit
  `python3 scripts/composite_score.py plateau <workspace>/history.json --window 3`
- Zeitbudget aufgebraucht (für Scheduled Tasks)
- 3 aufeinanderfolgende CRASH → Infrastruktur-Problem, Loop stoppen
- Guided-Modus: User sagt "Stopp"

### Schritt 6.5: Meta-Memory (alle 5 Experimente)

Lies `agents/meta.md` und schreibe `<workspace>/editing-notes.md` neu.

Läuft nur, wenn mindestens drei der bisherigen Experimente eine Entscheidung
KEEP oder REVERT tragen. Reine NEUTRAL-Serien liefern kein Material.

Zwei Reihenfolge-Bedingungen:

- **Vor** der History-Compaction, oder mit Zugriff auf
  `experiments/exp-NNN/mutation.json`. Die Kompaktierung behält `mutation_type`
  zwar in der Kurzform, wirft aber `hypothesis` und die Detailfelder weg; die
  Volldatensätze stehen in `history.archive.jsonl`.
- **Vor** dem Checkpoint-Save, sonst findet ein Resume die Datei ohne passenden
  Stand vor.

Der Inhalt ist optimizer-seitig, nie zielseitig: welche Mutationstypen bei
diesem Skill genommen haben, auf welcher Formulierungsebene Änderungen gewirkt
haben, welche Kategorien Regressionen erzeugt haben. Keine Anweisungen, die im
Ziel-Skill stehen könnten.

Eingehängt wird die Datei in Schritt 0.8 mit der Vorrangregel:

> Bevorzuge diese Notizen, wenn die aktuelle Evidenz mehrdeutig ist. Ignoriere
> sie, wenn die aktuellen Ergebnisse ihnen klar widersprechen.

### Schritt 7: Report generieren

Lies `templates/morning_report.md` und erzeuge einen Abschlussbericht:

1. **Zusammenfassung**: Start-Score → End-Score auf val, Anzahl Experimente, Dauer
2. **Test-Score**: Genau hier wird der test-Split zum zweiten und letzten Mal
   angefasst. Er wurde in keinem Experiment gesehen, deshalb ist er die einzige
   Zahl im Report, die nicht mitoptimiert wurde. Beide Werte ausweisen:
   Baseline vor Experiment 1 und Endversion. Gibt es keinen test-Split (unter 12
   Evals), muss der Report das ausdrücklich hinschreiben statt es wegzulassen.
3. **Längsvergleich**: `compare` auf dem letzten Experiment, Regressionen zuerst
4. **Auflösungsgrenze**: Welche Deltas in diesem Lauf überhaupt messbar waren
5. **Top-Verbesserungen**: Die 3 wirkungsvollsten Mutations
6. **Fehlgeschlagene Hypothesen**: Was nicht funktioniert hat (und warum)
7. **Coverage-Matrix**: Welche Bereiche wie oft getestet, wo Lücken bestehen
8. **Score-Verlauf**: Grafische Darstellung als ASCII-Chart
9. **Empfehlungen**: Was der User als nächstes tun könnte

Speichere den Report als `morning-report.md` im Workspace.

---

## Coverage-Matrix

Die Coverage-Matrix trackt, welche Bereiche des Optimierungsziels bereits wie intensiv
bearbeitet wurden — und lenkt den Hypothesis-Agent aktiv in unterversorgte Gebiete.

### Skill-Modus Kategorien

| Kategorie | Beschreibung | Beispiel-Mutationen |
|---|---|---|
| `formatting` | Output-Formatierung, Struktur, Layout | Markdown-Template, Tabellenformat |
| `content_quality` | Inhaltliche Korrektheit, Vollständigkeit | Faktenprüfung, fehlende Abschnitte |
| `examples` | Beispiele, Demonstrationen, Vorlagen | Beispiel hinzugefügt/verbessert |
| `workflow` | Prozess-Schritte, Reihenfolge, Abhängigkeiten | Schritt eingefügt/umgestellt |
| `edge_cases` | Sonderfälle, Fehlerbehandlung, Randbedingungen | Edge-Case-Anweisung ergänzt |
| `efficiency` | Token-Verbrauch, Laufzeit, Redundanz | Prosa gestrafft, Script optimiert |
| `scripts` | Helper-Scripts, Validierung, Automatisierung | Script hinzugefügt/gefixt |
| `structure` | Skill-Aufbau, Abschnittsreihenfolge | Abschnitte umorganisiert |

### Generic-Modus Kategorien

Werden dynamisch aus dem Scope abgeleitet:
- Pro Verzeichnis/Modul eine Kategorie
- Pro Dateityp eine Kategorie
- Pro funktionalem Bereich eine Kategorie (aus Code-Analyse)

### Matrix-Format

```json
{
  "categories": {
    "formatting": {
      "experiments_total": 3,
      "experiments_kept": 2,
      "experiments_reverted": 1,
      "experiments_neutral": 0,
      "experiments_invalid": 0,
      "last_experiment": "exp-005",
      "best_delta": "+0.0900",
      "saturated": false
    },
    "edge_cases": {
      "experiments_total": 0,
      "experiments_kept": 0,
      "experiments_reverted": 0,
      "experiments_neutral": 0,
      "experiments_invalid": 0,
      "last_experiment": null,
      "best_delta": null,
      "saturated": false
    }
  },
  "coverage_summary": {
    "total_categories": 8,
    "touched_categories": 5,
    "saturated_categories": 1,
    "untouched_categories": ["edge_cases", "scripts", "structure"],
    "coverage_percent": 62.5
  }
}
```

Zum Typ von `best_delta`: In der Coverage-Matrix ist es ein formatierter String
wie `"+0.0900"`, in `history.json` ist `delta` dagegen eine Zahl, und
`group-history` liefert `best_delta` ebenfalls als Zahl. Gelesen wird der String
über `as_float`, weil ein lexikografischer Vergleich `"+0.09" > "+0.10"` für wahr
hält.

### Sättigungsregel

Eine Kategorie gilt als **saturiert**, wenn:
- Mindestens 3 gemessene Experimente durchgeführt wurden UND
- Keines davon den Score um mehr als 0.01 verbessert hat

`INVALID`, `SKIP` und `NO_OP` zählen nicht als gemessen. Sonst gilt eine Kategorie als
abgegrast, obwohl sie nie wirklich getestet wurde. Der Status wird bei jedem Update neu
berechnet, eine Kategorie kann also auch wieder aus der Sättigung herausfallen.

Saturierte Kategorien werden bei der Hypothesenbildung deprioritisiert (nicht
ausgeschlossen — ein besonders vielversprechender Ansatz darf trotzdem versucht werden).

### Steuerungswirkung

Der Hypothesis-Agent bekommt die Coverage-Matrix als Input und wird angewiesen:
1. Unberührte Kategorien bevorzugen (Exploration)
2. Kategorien mit hoher Erfolgsrate erneut probieren (Exploitation)
3. Saturierte Kategorien meiden (Effizienz)

Das Gleichgewicht zwischen Exploration und Exploitation verschiebt sich im Lauf
des Loops: Anfangs breit explorieren, später gezielt in erfolgreichen Bereichen vertiefen.

Alle 5 Experimente: Coverage-Zusammenfassung in den Log schreiben.

---

## Konfiguration

Standardwerte, die der User überschreiben kann:

| Parameter | Default | Beschreibung |
|-----------|---------|--------------|
| `execution_mode` | auto | `auto` (vollautonomer Loop) oder `guided` (interaktiv mit User-Checkpoints) |
| `mode` | auto | `skill`, `generic` oder `auto` (erkennt automatisch) |
| `max_experiments` | 10 | Maximale Anzahl Experimente |
| `improvement_threshold` | 0.02 | Minimum-Delta zum Behalten |
| `regression_threshold` | 0.05 | Maximum-Delta vor Revert |
| `near_miss_band` | 0.02 | Breite des Bands unter der Keep-Schwelle, das `near_miss` setzt |
| `noise_floor` | 0.0 | Gemessenes Rauschen der Metrik; die effektive Keep-Schwelle ist `max(improvement_threshold, noise_floor, resolution)` |
| `gate_weights` | nicht gesetzt | Gate-Gewichtung. **Ohne den Key** gilt automatisch `{assertions: 1.0, judge: 0.0}`, mit `use_comparator` `{assertions: 0.65, judge: 0.35}`. Ein gesetzter Key gewinnt IMMER, auch gegen `use_comparator`. Wer ihn auf `{assertions: 1.0, judge: 0.0}` setzt und den Comparator einschaltet, zahlt für Judge-Läufe und bekommt reine Assertions. |
| `workspace_path` | (absoluter Pfad) | Workspace-Verzeichnis, vom Wizard gesetzt |
| `target_path` | (absoluter Pfad) | Optimierungsziel, vom Wizard gesetzt |
| `time_budget_minutes` | 120 | Zeitbudget (für Scheduled Tasks) |
| `split_ratio` | 0.50/0.25/0.25 | train/val/test der Evals (nur Skill-Modus) |
| `split_seed` | 42 | Seed der Hash-Zuordnung. Ändern verschiebt alle Evals und erzwingt ein Re-Baseline |
| `min_evals` | 6 | Darunter lehnt der Wizard ab |
| `min_evals_for_test` | 12 | Darunter gibt es keinen test-Split |
| `resolution` | (berechnet) | `2 / N_assertions`, geht als Untergrenze in die Keep-Schwelle |
| `use_comparator` | false | Blind-Comparison aktivieren (teurer, nur Skill-Modus) |
| `parallel_evals` | true | Evals parallel laufen lassen (nur Skill-Modus) |
| `target_value` | null | Zielwert für die Metrik (nur Generic-Modus) |
| `max_crashes` | 3 | Max aufeinanderfolgende Crashes vor Abbruch |
| `appendix_max_notes` | 15 | Deckel für LAPSE-Notizen in der geschützten Region |
| `rejected_limit` | 10 | Wie viele verworfene Versuche in den Prompt gehen |
| `min_support_count` | 2 | Mindestzahl der train-Evals, in denen ein Muster auftritt |
| `token_budget` | (berechnet) | `max(2000, ceil(initial * 1.25))`, vom Wizard gesetzt |
| `chars_per_token` | 3 | Divisor der Token-Schätzung, 3 für deutsche Texte |
| `protected_paths` | [] | Pfade, die der Loop nie ändert (Generic-Modus, Pflicht) |
| `invariant_command` | null | Muss nach jeder Mutation mit Exit 0 durchlaufen |
| `min_scope_ratio` | 0.9 | Untergrenze gegen "weniger messen ist keine Verbesserung" |
| `max_scope_files` | 200 | Obergrenze für den Scope-Glob |
| `meta_memory_interval` | 5 | Wie oft `editing-notes.md` neu geschrieben wird |
| `meta_memory_max_bullets` | 8 | Deckel für die Meta-Notizen |

---

## Scheduled Task Integration

Dieser Skill kann als nächtlicher Scheduled Task laufen. Dafür:

1. Der User durchläuft den Setup-Wizard und bestätigt die Konfiguration
2. Claude erstellt einen Scheduled Task mit dem Prompt:

```
Lies den skill-forge Skill und führe den autonomen
Verbesserungsloop durch.

Workspace: <workspace-path>
Config: <workspace-path>/config.json

Prüfe zuerst checkpoint.json. Ist applied_but_undecided gesetzt,
rolle auf on_disk_version zurück, bevor du weitermachst.
Sonst: starte beim letzten Stand in history.json, oder lege bei
einem neuen Workspace den Baseline-Snapshot pre-exp-001 an.
Generiere am Ende einen morning-report.md.
```

3. Am nächsten Morgen findet der User:
   - `morning-report.md` mit allen Ergebnissen
   - `experiment-log.tsv` für schnellen Überblick
   - Die verbesserte Version (falls Verbesserungen gefunden)
   - Vollständige Experiment-Logs für Nachvollziehbarkeit

---

## Geschützte Regionen

Zwei Regionen in der Ziel-SKILL.md sind für den Mutator tabu:

```markdown
<!-- FORGE_KEEP_START -->
Invarianten, die der User vor dem Lauf selbst hineinschreibt.
Der Loop ändert sie unter keinen Umständen.
<!-- FORGE_KEEP_END -->

<!-- FORGE_APPENDIX_START -->
- Kurze Notizen zu Fehlern, bei denen die Regel bereits im Skill stand
- Vom Loop verwaltet, umgeht das Gate, gedeckelt bei 15
<!-- FORGE_APPENDIX_END -->
```

`FORGE_KEEP` gehört dem User. Wer den Loop über Nacht laufen lässt, will
bestimmte Dinge garantiert unverändert wiederfinden.

`FORGE_APPENDIX` gehört dem Loop. Dort landen EXECUTION_LAPSE-Befunde: Fehler,
bei denen die korrekte Regel schon dastand und der Agent sie nur nicht befolgt
hat. Eine Body-Mutation wäre dort falsch, sie würde eine gültige Regel wegen
eines einmaligen Ausrutschers umschreiben. Weil diese Notizen das Gate umgehen,
sind sie kurz, dedupliziert und gedeckelt.

Durchgesetzt wird das mit `verify-regions` nach jeder Mutation, byteweise. Eine
geänderte, gelöschte **oder neu angelegte** Region ist eine Verletzung. Auch das
Anlegen: sonst baut sich der Mutator einen Schutzraum, den das Gate nie sieht.

Der Deckel von 15 Notizen kollidiert mit dem Längen-Richtwert im Sanity-Check
des Mutators. Rund 18 Zeilen gehen dauerhaft vom Budget ab, das ist eingepreist.

---

## Overfitting-Schutz

Das größte Risiko bei autonomer Optimierung ist Overfitting auf die Testfälle.
Gegenmaßnahmen:

1. **Dreiwege-Split**: train (50%) erzeugt das Signal für die Hypothese, val (25%)
   entscheidet Keep/Revert, test (25%) wird genau zweimal angefasst: für die
   Baseline vor Experiment 1 und im Report. Zugewiesen über einen stabilen Hash
   pro Eval-ID, nicht über eine Liste. Unter 12 Evals entfällt der test-Split,
   und der Report sagt das.
2. **Auflösungsgrenze**: Die Keep-Schwelle ist `max(improvement_threshold,
   noise_floor, resolution)`. `resolution` ist `2 / N_assertions`, also die
   Differenz, die zwei kippende Assertions erzeugen. Darunter wird nichts mehr
   behalten, weil darunter nichts mehr gemessen wird.
3. **Generalisierungs-Check**: Der Hypothesis-Agent muss erklären, warum seine
   Änderung über die konkreten Testfälle hinaus generalisiert
4. **Mutation-Diversity via Coverage-Matrix**: Systematisches Tracking welche
   Bereiche wie oft mutiert wurden, mit Sättigungserkennung
5. **Eval-Rotation nur in train**: Nach 5 Experimenten neue Eval-Queries
   generieren lassen und die ältesten train-Evals ersetzen. val und test bleiben
   eingefroren. Wer val trotzdem ändert, muss neu baselinen, sonst vergleichen
   alle späteren Deltas gegen eine andere Messlatte.
6. **Längsvergleich**: `compare` zeigt Regressionen einzeln, statt sie im
   Aggregat gegen Verbesserungen aufzurechnen.
7. **Crash-Erkennung**: 3 aufeinanderfolgende Crashes stoppen den Loop statt endlos
   zu wiederholen

---

## Abhängigkeiten

**Standalone-Betrieb (Standard):** Skill Forge funktioniert eigenständig. Die fünf
mitgelieferten Agents (`orchestrator.md`, `hypothesis.md`, `mutator.md`, `scorer.md`,
`meta.md`)
decken den gesamten Loop ab. Der Orchestrator koordiniert den Agent-Lifecycle, die
Context Assembly und die Checkpoints. Im Skill-Modus übernimmt der Scorer-Agent auch
das Grading der Assertions. Im Generic-Modus wird kein Agent zum Bewerten benötigt, der
Metrik-Command liefert die Zahl direkt.

**Optionale Erweiterung mit `skill-creator`:** Falls der `skill-creator`-Skill
installiert ist, kann Skill Forge dessen spezialisierte Agents nutzen:

- `agents/comparator.md` — Blind A/B-Vergleich (aktiviert mit `use_comparator: true`)
- `agents/analyzer.md` — Tiefere Post-hoc Analyse der Experiment-Ergebnisse

Diese sind optional und nicht erforderlich für den normalen Betrieb.

---

## Validierung

```bash
python3 -m pytest tests/ -q
python3 scripts/composite_score.py --version
```

Die Tests pinnen die Entscheidungslogik, Snapshot und Revert, die Coverage-Matrix und die
History-Kompaktierung fest. Wer an `scripts/composite_score.py` etwas ändert, führt sie
vorher aus.

---

## Referenz-Dateien

| Datei | Zweck |
|-------|-------|
| `agents/orchestrator.md` | Agent-Lifecycle-Koordination, Context Assembly, Checkpoint (v3) |
| `agents/hypothesis.md` | Hypothesenbildung aus Eval-Failures + Coverage-Matrix + Near-Misses |
| `agents/mutator.md` | Mutation mit Begründung (Skill + Generic) |
| `agents/meta.md` | Meta-Memory über Edit-Qualität, alle 5 Experimente |
| `agents/scorer.md` | LLM-as-Judge Bewertung (nur Skill-Modus) |
| `scripts/composite_score.py` | Scoring, Entscheidung (`decide`), Snapshot/Revert, TSV-Logging, History-Compaction, Checkpoint, Grouping |
| `tests/` | Testsuite für Entscheidung, Scoring, Coverage, Snapshot/Revert, History |
| `conftest.py` | pytest-Konfiguration im Repo-Root (macht `scripts/` importierbar) |
| `templates/morning_report.md` | Report-Template mit Coverage-Sektion |
| `templates/agent_context.md` | Dynamic Context Template für Agent-Prompt-Augmentation (v3) |
| `examples/generic-mode-lauf.md` | Ein durchgelaufener Generic-Loop mit ausgelösten Sperren |
| `references/architecture.md` | Detaillierte Architektur-Doku |
