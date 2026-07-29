# Skill Forge: Architektur

## Design-Philosophie

Dieses System überträgt das Autoresearch-Paradigma auf zwei Domänen:

**Skill-Modus**: Agent modifiziert `SKILL.md` → Evals laufen → Composite Score messen → keep/revert

**Generic-Modus**: Agent modifiziert Scope-Dateien → Metrik-Command ausführen → Wert messen → keep/revert

Der entscheidende Unterschied zwischen den Modi: Im Skill-Modus sind Mutationen
sprachlich (Formulierungen, Beispiele, Strukturen). Im Generic-Modus sind sie
technisch (Code, Config, Architektur). Das Autoresearch-Prinzip bleibt identisch:
Constraint + mechanische Metrik + autonome Iteration = kumulativer Gewinn.

## Architektur-Übersicht

```
┌──────────────────────────────────────────────────────┐
│                  Setup-Wizard                        │
│  [Modus] → [Scope] → [Metrik] → [Richtung]         │
│                     → [Dry-Run-Gate] → [Bestätigung] │
└────────────────────────┬─────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────┐
│                  Skill Forge Loop                     │
│                                                      │
│  ┌──────────────┐    ┌──────────┐                    │
│  │  Hypothesis   │───▶│ Mutator  │                    │
│  │  Agent        │    │  Agent   │                    │
│  │  + Coverage   │    │          │                    │
│  └──────▲───────┘    └────┬─────┘                    │
│         │                 │                           │
│         │            ┌────▼─────┐                     │
│         │            │  Run     │                     │
│         │            │  Verify  │                     │
│         │            │ (Eval /  │                     │
│         │            │  Command)│                     │
│         │            └────┬─────┘                     │
│         │                 │                           │
│         │            ┌────▼─────┐                     │
│         │            │  Score   │                     │
│         │            │  + Log   │──▶ history.json     │
│         │            │  (JSON   │──▶ experiment-log.tsv│
│         │            │   + TSV) │──▶ coverage-matrix  │
│         │            └────┬─────┘                     │
│         │                 │                           │
│         │            ┌────▼─────┐                     │
│         └────────────│  Keep /  │                     │
│                      │  Revert /│                     │
│                      │  Neutral │                     │
│                      └──────────┘                     │
└──────────────────────────────────────────────────────┘
```

## Datenfluss

### 1. Workspace-Struktur

```
<target>-skill-forge/
├── config.json                # Wizard-Konfiguration (Modus, Scope, Metrik, etc.)
├── evals.json                 # Testfälle, Train + Test (nur Skill-Modus)
├── history.json               # Fortschritts-Tracking (JSON, strukturiert)
├── history.archive.jsonl      # Volldatensätze der komprimierten Experimente
├── experiment-log.tsv         # Flaches Log (TSV, eine Zeile pro Experiment)
├── coverage-matrix.json       # Experiment-Abdeckung pro Kategorie
├── rejected.jsonl             # Nicht-KEEP im Wortlaut, kompaktierungsfest
├── editing-notes.md           # Meta-Memory, alle 5 Experimente
├── checkpoint.json            # Resume-Point (siehe Checkpoint/Resume System)
├── snapshots/
│   ├── pre-exp-001/           # Zustand VOR Experiment 1, also die Baseline
│   │   ├── manifest.json      # Dateiliste + base-Verzeichnis
│   │   └── files/             # SKILL.md / Scope-Dateien, relative Pfade
│   ├── pre-exp-002/           # Zustand VOR Experiment 2
│   │   ├── manifest.json
│   │   └── files/
│   └── ...
├── experiments/
│   ├── exp-001/
│   │   ├── hypothesis.json    # Was getestet wird
│   │   ├── mutation.json      # Was geändert wurde (inkl. Kategorie)
│   │   ├── runs/              # Nur Skill-Modus
│   │   │   ├── eval-0/
│   │   │   │   ├── with_mutation/
│   │   │   │   │   ├── outputs/
│   │   │   │   │   ├── grading.json
│   │   │   │   │   └── timing.json
│   │   │   │   └── baseline/
│   │   │   │       └── ...
│   │   │   └── eval-1/
│   │   │       └── ...
│   │   ├── command_output.txt  # Nur Generic-Modus
│   │   ├── score_with_mutation.json
│   │   ├── score_baseline.json
│   │   └── decision.json      # KEEP / REVERT / NEUTRAL (+ near_miss-Flag)
│   └── exp-002/
│       └── ...
└── morning-report.md
```

Zwei Namen in diesem Baum sind Vertrag, nicht Konvention:

**`with_mutation` und `baseline`** unter `runs/eval-N/`. `composite_score.py score`
filtert mit `--side with_mutation` bzw. `--side baseline` auf genau diese
Verzeichnisnamen. Wer hier umbenennt, bekommt keinen Fehler, sondern einen Score
über die falsche Menge. Ohne `--side` sammelt der Befehl beide Seiten ein und
mittelt Kandidat und Baseline in eine Zahl.

**`snapshots/pre-exp-NNN/`.** `pre-exp-007` ist der Zustand, den `revert`
wiederherstellt, wenn Experiment 7 scheitert. Die alten Namen `v0`, `v1` sind weg,
weil dasselbe Label je nach Datei zwei verschiedene Dinge bezeichnete: in
history.json ist `v1` der Zustand NACH Experiment 1, in der Mutator-Doku war `vN`
der Zustand VOR der Mutation. `pre-exp-NNN` ist eindeutig und kollidiert mit
nichts. Snapshot legt zusätzlich `manifest.json` an; ohne die Dateiliste kann
`revert` nicht wissen, welche Dateien die Mutation neu erzeugt hat, und löscht sie
folglich nicht.

```bash
python3 scripts/composite_score.py snapshot \
  --target <scope> --snapshot-dir <ws>/snapshots --version pre-exp-001

python3 scripts/composite_score.py revert \
  --snapshot-dir <ws>/snapshots --version pre-exp-001
```

### 2. config.json Schema

```json
{
  "execution_mode": "auto",
  "mode": "skill",
  "goal": "LinkedIn-Content-Skill verbessern",
  "target": "linkedin-content",
  "scope": "/path/to/skills/linkedin-content/SKILL.md",
  "scope_files_count": 1,
  "scope_validated": true,
  "metric_name": "composite_score",
  "metric_command": null,
  "metric_direction": "higher_is_better",
  "dry_run_passed": true,
  "baseline_value": 0.62,
  "dry_run_timestamp": "2026-03-14T21:45:00Z",
  "max_experiments": 10,
  "improvement_threshold": 0.02,
  "regression_threshold": 0.05,
  "near_miss_band": 0.02,
  "noise_floor": 0.0,
  "gate_weights": null,
  "workspace_path": "/absolute/path/to/linkedin-content-skill-forge",
  "target_path": "/absolute/path/to/skills/linkedin-content/SKILL.md",
  "time_budget_minutes": 120,
  "split_ratio": [0.50, 0.25, 0.25],
  "split_seed": 42,
  "min_evals": 6,
  "min_evals_for_test": 12,
  "use_comparator": false,
  "parallel_evals": true,
  "target_value": null,
  "max_crashes": 3
}
```

Zu den Schwellen-Keys:

| Key | Bedeutung |
|-----|-----------|
| `improvement_threshold` | Ab diesem Delta gilt eine Mutation als KEEP |
| `regression_threshold` | Unter `-regression_threshold` gilt sie als REVERT |
| `near_miss_band` | Breite des Bands unterhalb der Keep-Schwelle, in dem NEUTRAL das Flag `near_miss` bekommt |
| `noise_floor` | Untergrenze für die Keep-Schwelle: `threshold = max(improvement_threshold, noise_floor, resolution)` |
| `gate_weights` | Gewichte des Gate-Scores. Fehlt der Key, gilt ohne Comparator `{assertions: 1.0, judge: 0.0}` und mit Comparator `{assertions: 0.65, judge: 0.35}`. Ein gesetzter Key gewinnt gegen beide Defaults, auch gegen `use_comparator`. Die Summe muss 1.0 ergeben, ein `efficiency`-Eintrag ungleich 0 wird abgelehnt |

`composite_score.py decide --config <ws>/config.json` liest diese Werte, und die
config.json gewinnt über die Argparse-Defaults. Ohne `--config` läuft der Befehl
mit den eingebauten Defaults, die dann von der Konfiguration abweichen können.

`workspace_path` und `target_path` müssen absolut sein und dürfen nicht mit `~`
beginnen. Ein Scheduled Task startet mit einem cwd, den niemand kennt, und ohne
Shell, die Tilde expandiert. Ein relativer Pfad in der config.json bedeutet
deshalb im Nachtlauf nicht dasselbe Verzeichnis wie im Wizard, sondern gar keins.

### 3. history.json Schema

```json
{
  "skill_name": "linkedin-content",
  "mode": "skill",
  "started_at": "2026-03-14T22:00:00Z",
  "config": { "...": "Verweis auf config.json" },
  "current_best": "v3",
  "baseline_score": 0.62,
  "best_score": 0.81,
  "consecutive_no_improvement": 0,
  "consecutive_crashes": 0,
  "experiments": [
    {
      "id": "exp-001",
      "version": "v1",
      "parent": "v0",
      "hypothesis": "Beispiel für Hook-Formulierung hinzugefügt",
      "mutation_type": "example_add",
      "category": "examples",
      "composite_score": 0.71,
      "baseline_score": 0.62,
      "delta": 0.09,
      "decision": "KEEP",
      "near_miss": false,
      "timestamp": "2026-03-14T22:15:00Z",
      "duration_seconds": 180
    }
  ]
}
```

`near_miss` ist ein Boolean, kein Decision-Wert. Es steht nur auf `true`, wenn
`decision` gleich `NEUTRAL` ist und das Delta im Band knapp unterhalb der
Keep-Schwelle liegt. `compact_history` behält das Feld in der Kurzform, weil der
Hypothesis Agent daran erkennt, welche Ansätze eine zweite Variation verdienen.

**Versionssemantik.** `version` und `parent` sind die logische Versionskette:
`v1` ist der Zustand NACH Experiment 1, `parent: "v0"` verweist auf den Stand,
gegen den gemessen wurde. Diese Zählung hat nichts mit den Snapshot-Verzeichnissen
zu tun. Die heissen `pre-exp-NNN` und bezeichnen den Zustand VOR Experiment N.
Der Snapshot, aus dem ein gescheitertes Experiment 1 zurückgerollt wird, ist also
`snapshots/pre-exp-001/`, und der Eintrag, der dabei entsteht, trägt trotzdem
`version: "v1"`. Getrennte Namensräume, bewusst: solange beide `v0` hiessen,
zeigte dasselbe Label je nach Datei auf zwei verschiedene Zustände.

### 4. Gate-Score (Skill-Modus)

```
composite = assertion_pass_rate × W_a + llm_judge × W_j
```

**Standard-Gewichtung (ohne Comparator):**
- W_a = 1.00 (Assertion Pass Rate)

**Erweiterte Gewichtung (mit Comparator):**
- W_a = 0.65 (Assertion Pass Rate)
- W_j = 0.35 (LLM-as-Judge)

Die Comparator-Gewichte sind aus den alten 0.50/0.30 renormalisiert, nachdem der
Efficiency-Anteil entfallen ist. Das Verhältnis zwischen Assertions und Judge
bleibt damit dasselbe wie vorher.

**Efficiency entscheidet nichts mehr.** Sie wird weiter berechnet und steht unter
`details.efficiency_score`, gehört aber in den Morning Report und nicht ins Gate.
Zwei Läufe mit identischen Assertions lagen um 0.045 auseinander, bei einer
Keep-Schwelle von 0.02: der Effizienzanteil hätte also allein durch Laufzeit- und
Tokenrauschen über Keep und Revert entschieden. Dazu kam ein zweiter Effekt, ein
leeres Experiment-Verzeichnis ergab composite 0.20, weil die Effizienzformel ohne
Messdaten 1.0 lieferte. `calc_efficiency_score` gibt jetzt `None` zurück, wenn
keine timing.json gefunden wurde.

Der Score wird pro Seite berechnet:

```bash
python3 scripts/composite_score.py score <exp-dir> --side with_mutation
python3 scripts/composite_score.py score <exp-dir> --side baseline
```

Findet der Befehl kein einziges Grading, bricht er mit Exit 2 ab, statt 0.0 zu
melden. Ein Score von 0.0 aus einem leeren Verzeichnis ist keine Messung.

### 5. Generic-Modus Scoring

Im Generic-Modus wird der Metrik-Command direkt ausgewertet:

```python
current_value = extract_metric_value(command_output)
delta = current_value - baseline_value

if direction == "higher_is_better":
    improved_raw = delta > 0
elif direction == "lower_is_better":
    improved_raw = -delta > 0
```

Das ist die Metrik-Extraktion, nicht die Entscheidung. Über Keep und Revert
entscheidet auch im Generic-Modus ausschliesslich `decide()` (siehe unten). Weil
die Metrik hier in KB, Sekunden oder Fehlerzahlen misst und eine absolute Schwelle
von 0.02 dort nichts bedeutet, ist `--relative` in diesem Modus der sinnvolle
Aufruf: das Delta wird dann auf die Baseline normalisiert.

### 6. Entscheidung

`decide()` in `scripts/composite_score.py` ist die einzige Stelle im Projekt, an
der aus zwei Zahlen eine Entscheidung wird. Drei Ausgänge, kein vierter:

```
threshold = max(improvement_threshold, noise_floor, resolution)

delta > threshold      → KEEP
delta < -regression    → REVERT
sonst                  → NEUTRAL   (inklusive Gleichstand)

near_miss = NEUTRAL und delta > threshold - near_miss_band
```

```bash
python3 scripts/composite_score.py decide \
  --candidate 0.84 --baseline 0.78 --config <ws>/config.json
```

Die Ausgabe ist JSON mit `decision`, `near_miss`, `delta`, `threshold`,
`improvement_threshold`, `regression_threshold`, `noise_floor`, `direction`,
`relative`, `relative_fallback` und `formula`. `formula` ist die Rechnung als lesbarer String und
gehört in die decision.json des Experiments, damit später nachvollziehbar ist,
mit welchen Schwellen entschieden wurde. `relative_fallback` markiert Läufe, in
denen die relative Rechnung wegen einer Nullbaseline übersprungen wurde; dort ist
das Delta absolut und nicht mit den übrigen vergleichbar.

Weitere Flags: `--direction higher_is_better|lower_is_better`, `--relative`,
`--noise-floor`, `--improvement`, `--regression`, `--near-miss-band`.

**NEUTRAL rollt zurück.** Auch bei Gleichstand. Die frühere Regel, bei Null-Delta
die neue Version zu behalten, klingt harmlos, führt aber dazu, dass ein Loop über
zehn Experimente ohne eine einzige gemessene Verbesserung vom Ausgangspunkt
wegdriftet. Wer die Mutation nicht messen kann, hat keinen Grund, sie zu behalten.

## Setup-Wizard: Validierungs-Gates

Jeder Wizard-Schritt hat ein hartes Abnahmekriterium:

| Schritt | Gate | Fehlerbehandlung |
|---------|------|-----------------|
| Scope | Glob matcht ≥1 Datei | Neues Pattern verlangen |
| Metrik | Kein subjektiver Text | Nur Zahlen akzeptieren |
| Dry-Run | Exit-Code 0 + parsbare Zahl | Korrekturvorschläge anbieten |
| Bestätigung | User-Bestätigung | Konfiguration anpassbar |

Der Dry-Run ist das wichtigste Gate: Er verhindert, dass der Loop startet und
erst nach Stunden feststellt, dass die Eval-Infrastruktur nicht funktioniert.

## Overfitting-Schutzmaßnahmen

### Dreiwege-Split (nur Skill-Modus)

```
Alle Evals
    ├── train (50%) → Failure-Analyse, Transcripts, Hypothesenbildung
    ├── val   (25%) → Entscheidet Keep/Revert. Sonst nichts.
    └── test  (25%) → Genau zweimal: Baseline vor Experiment 1 und Report
```

Zugewiesen wird über einen stabilen Hash pro Eval-ID, nicht über eine Liste:

```python
bucket = int(sha256(f"{seed}:{eval_id}".encode()).hexdigest(), 16) % 100
```

CLI: `python3 scripts/composite_score.py split-assign <evals.json> --seed 42`

Warum ein Hash und keine Liste: eine Positionsnummer verschiebt beim Löschen
eines Evals alle nachfolgenden in einen anderen Split, und jedes spätere Delta
vergleicht danach etwas anderes. Die ID muss deshalb ein sprechender,
unveränderlicher Slug sein; sie umzubenennen ist ein Re-Baseline-Ereignis.

Zwei Sicherungen:

- Bleibt val leer, wird deterministisch ein Eval aus train dorthin gezwungen.
  Ohne den Fallback gated der Loop gegen eine leere Menge und meldet 1.0.
  Der Fallback zieht nie aus test.
- Unter 12 Evals entfällt der test-Split, und der Report weist das aus. Ein
  Zwei-Item-Holdout als unabhängigen Test auszugeben ist irreführender als gar
  keiner. Unter 6 Evals lehnt der Wizard ab.

### Auflösungsgrenze

Der Gate-Score ist nach dem Wegfall der Efficiency exakt die
Assertion-Pass-Rate und damit grob quantisiert: ein einzelner Flip bewegt
`1 / N`. Bei 9 Assertions sind das 0.111, bei 31 noch 0.032.

```python
resolution = min_detectable_delta(total_assertions, flips=2)  # 2 / N
threshold  = max(improvement_threshold, noise_floor, resolution)
```

`decide` gibt in `binding_threshold` aus, welcher der drei Werte gebunden hat,
und nennt ihn im Formel-String. Eine feste Schwelle von 0.02 lag unter der
Auflösung jedes realistischen Eval-Sets und konnte deshalb nie greifen: jeder
einzelne Assertion-Flip löste KEEP aus.

SkillOpt braucht das nicht, weil sein Selection-Split gross genug ist, dass ein
Item-Flip im Promillebereich bleibt. Der Blogpost zieht dieselbe Konsequenz
redaktionell ("treat differences below 1.5 percentage points as noise"). Skill
Forge muss sie mechanisch ziehen.

### Diff und NO_OP

```python
make_diff(snapshot_dir, version, out_path) -> {changed, lines_added,
    lines_removed, files_changed, files_added, files_deleted, binary_files}
```

CLI: `python3 scripts/composite_score.py diff --snapshot-dir <dir> --version pre-exp-003 --out mutation.diff`

Beide Bäume werden gewalkt und die Vereinigung der Pfade gebildet, sonst sähe
der Vergleich neu angelegte Dateien nicht und stempelte ein legitimes
`script_add` als NO_OP ab. `changed: false` erzeugt die Entscheidung `NO_OP`:
kein Eval-Run, kein Scoring, kein Coverage-Update.

### Längsvergleich

```python
compare_runs(experiment_dir) -> {counts, categories, unpaired, net}
```

Vier Kategorien pro Eval-Paar, nach SkillOpts `build_comparison_pairs`:

| Kategorie | Baseline | Kandidat |
|---|---|---|
| `regressed` | bestanden | gescheitert |
| `persistent_fail` | gescheitert | gescheitert |
| `improved` | gescheitert | bestanden |
| `stable_success` | bestanden | bestanden |

Gerendert wird in genau dieser Reihenfolge. Regressionen zuerst ist die
eigentliche Anweisung: ein Aggregatscore verschluckt sie, weil fünf neue
Treffer gegen drei neue Fehler netto plus zwei ergeben und wie Fortschritt
aussehen.

### Coverage-Matrix

Die Coverage-Matrix steuert die Exploration-Exploitation-Balance:

```
Frühphase (1-3):   Exploration  ████████░░  80%
Mittelphase (4-7): Balanced     █████░░░░░  50%
Spätphase (8+):    Exploitation ██░░░░░░░░  20%
```

Sättigungsregel: Eine Kategorie ist saturiert nach ≥3 gemessenen Experimenten
ohne Verbesserung >0.01. Saturierte Kategorien werden deprioritisiert.

Gemessen heisst KEEP, REVERT oder NEUTRAL. INVALID, SKIP und NO_OP zählen nicht
mit, sonst gilt eine Kategorie als abgegrast, obwohl dort nie eine Zahl entstanden
ist. Der Status wird bei jedem Update neu berechnet und nicht nur gesetzt: vorher
rastete `saturated` ein und löste sich auch nach einem späteren Treffer nie
wieder.

### Eval-Rotation

Nach jedem 5. Experiment:
1. Generiere 2-3 neue Eval-Queries
2. Ersetze die ältesten **train**-Evals
3. val und test bleiben eingefroren

Der frühere Widerspruch zwischen SKILL.md ("Test-Split rotieren") und diesem
Abschnitt ist damit aufgelöst: rotiert wird ausschliesslich in train. Ein
rotierender Holdout wäre keiner. Wer val doch ändert, muss neu baselinen, sonst
vergleichen alle späteren Deltas gegen eine andere Messlatte.

### Geschützte Regionen

```
<!-- FORGE_KEEP_START -->      dem User gehörend, der Loop fasst sie nie an
<!-- FORGE_APPENDIX_START -->  dem Loop gehörend, umgeht das Gate, Deckel 15
```

`verify_protected_regions(snapshot, mutated)` vergleicht die Inhalte byteweise
und meldet drei Verletzungsarten: `violated` (geändert), `removed` (gelöscht),
`added` (neu angelegt). Die dritte ist nicht Paranoia: ohne sie könnte der
Mutator sich selbst einen Schutzraum bauen und dort Änderungen ablegen, die das
Gate nie sieht.

CLI: `verify-regions <snapshot-datei> <mutierte-datei>`, Exit 1 bei Verletzung.

Die Durchsetzung liegt bewusst in Python und nicht im Sanity-Check des
Mutators. SkillOpt macht es genauso: `skillopt/optimizer/skill.py` gibt einem
Edit, der in eine geschützte Region zielt, den Status
`skipped_protected_region`, statt den Agenten fragen zu lassen.

### Defect gegen Lapse

Jedes Failure-Pattern wird klassifiziert, bevor eine Ursache gesucht wird:

> Gibt es im aktuellen Skill eine Regel, die diesen Fehler verhindert hätte?

Nein bedeutet `SKILL_DEFECT`, der normale Weg über Mutation und Gate. Ja
bedeutet `EXECUTION_LAPSE`: keine Body-Mutation, sondern eine Zeile in
`appendix_notes`. **Im Zweifel LAPSE.**

Der asymmetrische Default ist der Kern. In Kombination mit der Auflösungsgrenze
wäre der Schaden sonst unsichtbar: der Score-Unterschied eines einzelnen
Subagent-Ausrutschers liegt unter dem, was das Gate messen kann, die korrekte
Regel wäre trotzdem umgeschrieben oder gelöscht.

`append_appendix_notes` dedupliziert über eine Kanonform
(`re.sub(r"\s+", " ", s.lower()).strip().rstrip(" .;:,_-")`) und deckelt bei 15.
Bei Überschreitung wird nichts still verworfen, `dropped_oldest` meldet es.

Reihenfolge: der Append ist der LETZTE Schreibvorgang eines Experiments. REVERT
und NEUTRAL spielen den Snapshot zurück und ersetzen die Datei komplett.

### Erfolgsanalyse als Schutzliste

Der Hypothesis-Agent sieht nicht nur die gescheiterten, sondern auch die
bestandenen train-Evals und liefert `success_patterns`. Zwei Regeln aus
SkillOpts `analyst_success.md`: nur Muster benennen, die noch nicht im Skill
stehen, und bestehende Abschnitte verstärken statt neue anzulegen.

Der Zweck ist die Schutzliste für den Mutator. Skill Forge kennt `prune` und
`structure_change`; ohne benannte funktionierende Muster löscht der Loop genau
die Abschnitte, die die bestandenen Evals tragen. Ein reiner Fehleranalysator
ist ein monotoner Regelanhäufer ohne Vergessensmechanismus.

Bei Konflikt gewinnt die Failure-Ableitung, analog zu SkillOpts
"FAILURE PATCHES TAKE PRIORITY" in `merge_final.md`.

### Verworfene Mutationen

`rejected.jsonl` im Workspace-Root, eine Zeile pro Nicht-KEEP, von der
History-Kompaktierung unberührt. `format_rejected` rendert daraus einen
Prompt-Block mit SkillOpts Kopfzeile:

> Nutze diese Liste, um wirkungslose Änderungen nicht zu wiederholen und
> ungelöste Fehlermuster zu priorisieren.

Erfasst werden REVERT und NEUTRAL, nicht nur Near-Misses. Die Kopfzeile ist die
eigentliche Anweisung: ohne sie ist es eine Liste, mit ihr ein Auftrag.

### Kandidaten-Ranking

Der Hypothesis-Agent erzeugt drei Kandidaten und ranked sie im selben Prompt
gegen vier Kriterien aus SkillOpts `prompts/ranking.md`: Systematic impact,
Complementarity, Generality, Actionability. Angewendet wird genau einer.

Das Ranking steht NACH Near-Miss- und Duplikat-Check. Wer vorher rankt, bewertet
Kandidaten, die er gleich danach verwirft.

Nicht gewählte Kandidaten werden nicht aufgehoben. Sie wurden gegen eine
SKILL.md formuliert, die nach einem KEEP nicht mehr existiert.

**Was bewusst NICHT übernommen wurde:** SkillOpts `edit_budget` von 4. Die Regel
"eine fokussierte Änderung pro Experiment" ist strenger und sichert die
Attribution von Score-Bewegungen. Ein Budget von 4 wäre hier ein Rückschritt.

### Token-Budget

```python
count_tokens(text, chars_per_token=3)          # Divisor 3, nicht 4
artifact_stats(paths, budget) -> {tokens, budget_ok, forced_category, ...}
suggest_token_budget(current) -> max(2000, ceil(current * 1.25))
```

CLI: `artifact-stats <pfade...> --budget N`, Exit 1 bei Überschreitung.

Divisor 3, weil Skill Forges Artefakte deutsch sind und Komposita schlechter
tokenisieren. Mit 4 wäre das Budget rund 30 Prozent zu grosszügig.

Der Scope umfasst SKILL.md plus alle vom Loop erzeugten Dateien unter
`references/` und `scripts/`. Ein Budget, das nur die Hauptdatei zählt, ist über
`reference_add` in einer Runde umgangen, und zwar durch genau den Mutationstyp,
den der Loop unter Budgetdruck naheliegenderweise wählt.

Bei Überschreitung setzt der Orchestrator `forced_category: "efficiency"` und
`forced_mutation_type: "prune"` für die nächste Runde. Der frühere Richtwert
("unter 500 Zeilen?") stand ohne Konsequenz in der Sanity-Liste und hat nie ein
KEEP verhindert.

**Nicht übernommen:** SkillOpts Semantic-Density-Bonus. Die Elf-Wort-Liste
(MUST, ALWAYS, NEVER, ...) ist englisch, die Artefakte hier sind deutsch, die
Heuristik würde nichts messen. Sie stünde ausserdem in Spannung zur Regel in
`agents/mutator.md`, keine ALL-CAPS-Befehle zu schreiben.

### Invarianten im Generic-Modus

```python
snapshot_scope(scope, protected_paths) -> {protected: {pfad: sha256}, file_count, ...}
check_invariants(before, invariant_command, min_scope_ratio=0.9) -> {ok, decision, reasons}
```

CLI: `invariants-snapshot` vor der Mutation, `invariants-check` danach, Exit 3
bei Verletzung. Zusätzlich nimmt `metric` die Parameter `--invariants-before`
und `--invariant-command` entgegen und liefert ohne bestandene Prüfung keinen
Wert, sondern `{"decision": "INVALID"}`.

Drei Invarianten:

1. **Geschützte Pfade unverändert.** Metrik- und Test-Konfiguration, nicht die
   gemessenen Quelldateien.
2. **Der Scope ist nicht wesentlich geschrumpft.** `min_scope_ratio` 0.9.
3. **Der `invariant_command` läuft weiterhin mit Exit 0 durch.**

Der Command läuft nur, wenn die geschützten Pfade unverändert sind. SkillOpt
formuliert denselben Grundsatz in `adapters/superpowers.py`: "Never execute a
test file after detecting that the evaluated agent changed it."

Warum das nötig ist: die optimale Mutation für `flake8 src/ | wc -l` ist, `src/`
zu löschen. Für Jest-Coverage, die ungedeckten Tests zu entfernen. Für
Bundle-Size, Features rauszuwerfen. Der Exit-Code fängt nichts davon ab, bei
`flake8 src/ | wc -l` ist er ohnehin immer der von `wc`.

`INVALID` zählt nicht in die Sättigung und nicht in `best_delta`.

### Meta-Memory

`<workspace>/editing-notes.md`, geschrieben von `agents/meta.md`, alle 5
Experimente und nur wenn mindestens drei davon KEEP oder REVERT tragen.

Der Inhalt ist optimizer-seitig und landet nie in der Ziel-SKILL.md. SkillOpts
`prompts/meta_skill.md` zieht dieselbe Grenze: "Address the FUTURE OPTIMIZER
directly, not the target."

Zwei Pflichten gegen das Anwachsen:

- **Belegpflicht.** Jeder Bullet nennt mindestens eine Experiment-ID. Bullets
  ohne ID werden gestrichen, nicht überarbeitet.
- **Verdikt-Pflicht.** Zu jedem Bullet der Vorfassung: `kept`, `revised` oder
  `removed`. Maximal acht Bullets, die Datei wird komplett neu geschrieben.

Eine Sperre: die Notizen dürfen keine Kategorie ausschliessen. Sie beeinflussen,
wie eine Mutation formuliert wird, nicht ob eine Kategorie noch angefasst wird.
Sonst kollabiert die Exploration und die Coverage-Matrix wird wirkungslos.

Reihenfolge: vor der History-Compaction, weil sie `hypothesis` und die
Detailfelder wegwirft, und vor
dem Checkpoint-Save, damit ein Resume die Datei mit passendem Stand vorfindet.

### Evidenz nie kürzen

Die 30-Prozent-Context-Regel gilt für History, Coverage, Meta-Notizen und den
Rejected-Block. Sie gilt **nicht** für die Transcripts des aktuellen
Experiments.

SkillOpt hat die Längenbegrenzung in `gradient/reflect.py` bewusst ausgebaut und
den Parameter nur aus Kompatibilität stehen lassen:

> Truncation is disabled: the optimizer is given the full content so it can see
> exactly what the agent saw/did.

Gekürzte Transcripts erzeugen plausible, aber falsche Ursachenanalysen, und aus
einer falschen Ursache wird eine Regel, die das Gate nicht bewegt und trotzdem
Platz kostet. Komprimiere das Artefakt, nie die Evidenz.

### Diversity-Tracking

Die Coverage-Matrix ersetzt das einfache Sections-Counting durch
kategorisiertes Tracking mit Erfolgsraten und Sättigungserkennung.

## Crash-Handling (Generic-Modus)

```
Command-Ausführung
    ├── Exit 0 + Zahl → Normal weiter
    ├── Exit 0 + keine Zahl → SKIP (Parsing-Fehler)
    ├── Exit ≠ 0 (1. Mal) → Fix-Versuch → erneut ausführen
    └── Exit ≠ 0 (2. Mal) → SKIP → consecutive_crashes++
        └── consecutive_crashes ≥ max_crashes → Loop stoppen
```

## Integration mit Scheduled Tasks

Der Loop kann als Scheduled Task konfiguriert werden. Der Setup-Wizard
erzeugt die config.json, die der Scheduled Task dann einliest:

```python
# Via Cowork Scheduled Tasks
create_scheduled_task(
    taskId="skill-forge-{target-name}",
    cronExpression="0 22 * * *",  # Jeden Abend um 22:00
    prompt="...",
    description="Skill Forge Loop für {target-name}"
)
```

Der Task:
1. Liest `config.json` für die vollständige Konfiguration
2. Prüft ob `history.json` existiert (Resume vs. Fresh Start)
3. Führt Experimente bis zum Zeitbudget durch
4. Generiert den Morning Report
5. Beendet sich

## Ausführungsmodi: Auto vs. Guided

Der `execution_mode` bestimmt, ob der Loop autonom oder interaktiv abläuft:

```
Auto-Modus:     Wizard → Dry-Run → [Loop ohne Pause] → Report
Guided-Modus:   Wizard → Dry-Run → [Loop mit 5 Checkpoints] → Report
```

### Guided-Modus Checkpoints

```
┌────────────────────────────────────────────────────────┐
│  Guided-Modus: 5 Checkpoints im Loop                  │
│                                                        │
│  CP1: Evals prüfen (einmalig, nach Wizard-Schritt 3)  │
│       → User passt Evals an, bestimmt Anzahl/Gewicht   │
│                                                        │
│  CP2: Hypothese prüfen (jede Runde)                    │
│       → User bestätigt, passt an oder gibt eigene vor   │
│                                                        │
│  CP3: Mutation prüfen (jede Runde)                     │
│       → User sieht Diff, bestätigt oder korrigiert      │
│                                                        │
│  CP4: Ergebnis bewerten (jede Runde)                   │
│       → User sieht Score/Delta, kann Empfehlung         │
│         überstimmen (Keep/Revert/Manuell)               │
│                                                        │
│  CP5: Weitermachen? (jede Runde)                       │
│       → User entscheidet: weiter / N Runden / stopp     │
└────────────────────────────────────────────────────────┘
```

Im Auto-Modus werden alle Checkpoints übersprungen. Die config.json speichert
den Modus als `"execution_mode": "auto"` oder `"guided"`. Scheduled Tasks
verwenden immer `auto` (kein User-Prompt verfügbar).

## v3 Features

### Entscheidung als reine Funktion

`decide(candidate, baseline, ...)` nimmt zwei Zahlen und gibt ein Dict zurück.
Kein Dateisystem, kein Zustand, keine Seiteneffekte. Vorher lag die Kaskade
verstreut in Markdown-Prosa und Shell-Schnipseln, und in genau dieser Kaskade war
der NEUTRAL-Zweig unerreichbar: über 4001 Deltas zwischen -0.20 und +0.20
erreichten ihn ganze 1. Die restlichen Läufe verteilten sich auf KEEP, REVERT und
einen Zwischenzustand, den niemand als Ausgang geplant hatte.

Jetzt gibt es drei Ausgänge, dokumentiert in Abschnitt 6, und `near_miss` ist ein
Flag darauf. Der Subcommand `decide` schreibt die Rechnung als `formula` mit
heraus, damit die decision.json nicht nur das Ergebnis, sondern die Herleitung
enthält.

### Snapshot und Revert

```bash
python3 scripts/composite_score.py snapshot \
  --target <pfad-oder-glob> --snapshot-dir <ws>/snapshots --version pre-exp-001

python3 scripts/composite_score.py revert \
  --snapshot-dir <ws>/snapshots --version pre-exp-001
```

`snapshot` legt fehlende Verzeichnisse an, löst Globs in Python auf und schreibt
`manifest.json` plus `files/<relpfad>`. `revert` stellt aus dem Manifest wieder
her und löscht zusätzlich alle Dateien im Scope, die nicht im Manifest stehen,
also genau die, die die Mutation neu angelegt hat.

Davor gab es überhaupt keinen Revert, nur ein `cp -r <datei> <dir>/v1/` in der
Agent-Doku. Das bricht mit Exit 1 ab, solange `v1` nicht existiert, und legt ohne
Trailing-Slash eine Datei namens `v1` an statt eines Verzeichnisses.

### Testsuite

`conftest.py` im Repo-Root, Tests unter `tests/`:

```bash
python3 -m pytest tests/ -q
```

Die Testsuite verteilt sich auf neun Dateien: `test_decide.py`,
`test_scoring.py`, `test_coverage.py`, `test_snapshot_revert.py`,
`test_history.py`, `test_generic_and_cli.py`, `test_block2.py`,
`test_block3.py`, `test_block4.py` und `test_review_findings.py`. Die letzte
pinnt jeden Defekt, den die adversariale Review über Block 2 bis 4 gefunden
hat, samt der Lücken, die ein Mutationstest aufgedeckt hat.

### Tiered History Compaction

```
History-Einträge:
  ├── Letzte 5: Vollständige Details (hypothesis, mutation, scores, etc.)
  └── Ältere:   Komprimiert auf {id, version, category, mutation_type,
                composite_score, delta, decision, near_miss, timestamp}
```

CLI: `python3 scripts/composite_score.py compact <history-path> --keep 5`

Verhindert Context-Overflow bei langen Runs. Die komprimierten Einträge
reichen für Trend-Analyse und Coverage-Tracking, während die detaillierten
Einträge dem Hypothesis Agent für Root-Cause-Analyse zur Verfügung stehen.

Vor dem Kürzen wandern die Volldatensätze nach `history.archive.jsonl`, eine
Zeile pro Experiment, idempotent über die Experiment-ID. Der Grund ist ein
konkreter Datenverlust: die alte Fassung löschte beim Komprimieren das Feld
`hypothesis`, also genau das Feld, gegen das der Duplikat-Check im Hypothesis
Agent prüft. Ab Experiment 6 sah der Agent, dass eine Kategorie viermal reverted
worden war, aber nicht mehr, was dort versucht wurde. `mutation_type` und
`near_miss` bleiben deshalb jetzt auch in der Kurzform stehen.

### Checkpoint/Resume System

```
checkpoint.json:
  ├── last_completed_experiment
  ├── experiment_index
  ├── current_baseline_score
  ├── best_version / best_score
  ├── on_disk_version         # welcher Snapshot gerade auf der Platte liegt
  ├── applied_but_undecided   # Mutation angewendet, aber nicht entschieden
  ├── coverage_snapshot
  ├── next_planned_category
  └── timestamp
```

CLI: `python3 scripts/composite_score.py checkpoint-save/checkpoint-info <workspace>`

`checkpoint-save` nimmt dafür `--on-disk-version <pre-exp-NNN>`,
`--applied-but-undecided`, `--best-version`, `--best-score` und
`--experiment-index`.

`applied_but_undecided` ist das Feld, an dem Crash-Recovery hängt. Stürzt der Loop
zwischen Mutation und Entscheidung ab, liegt eine unbewertete Änderung auf der
Platte. Ein Resume, das das nicht weiss, misst gegen einen Zustand, den es für die
Baseline hält, und alle folgenden Deltas sind falsch. Steht das Flag, rollt der
Resume zuerst auf `on_disk_version` zurück und beginnt das Experiment neu.

Ermöglicht:
- Unterbrechung und Fortsetzung über Sessions
- Crash-Recovery ohne Datenverlust
- Scheduled Tasks die über mehrere Nächte laufen

### Dynamic Prompt Augmentation

Agent-Prompts werden zur Laufzeit mit aktuellem Kontext angereichert:
- Aktuelle Phase (Exploration/Balanced/Exploitation)
- Letzte 3 Experiment-Ergebnisse
- Coverage-Matrix als Tabelle
- Near-Miss-Hypothesen
- Phase-spezifische Empfehlungen

Template: `templates/agent_context.md`

### Near-Miss als Flag

`NEAR_MISS` ist kein Decision-Zustand. Es war einer, und das war der Fehler: als
vierter Zweig in der Kaskade schluckte er den kompletten Bereich zwischen -0.05
und +0.02 und machte NEUTRAL unerreichbar.

Jetzt ist es ein Boolean auf NEUTRAL:

```
near_miss = (decision == NEUTRAL) und (delta > threshold - near_miss_band)
```

Mit den Defaults (`improvement_threshold` 0.02, `near_miss_band` 0.02) markiert
das Deltas zwischen 0.00 und 0.02, also die Mutationen, die knapp an der
Keep-Schwelle vorbeigeschrammt sind.

Was daraus folgt:
- Der Code wird zurückgesetzt, wie bei jedem NEUTRAL
- Die Hypothese wird als vielversprechend markiert
- Der Hypothesis Agent sieht das Flag in der nächsten Runde und kann variieren
  statt neu anzufangen

Das Flag steht in history.json (`near_miss`) und überlebt die Kompaktierung.

### Orchestrator Agent

Neuer 4. Agent der den Lifecycle der anderen 3 koordiniert:
- Context Assembly vor jedem Agent-Aufruf
- Schema-Validierung der Agent-Outputs
- Meta-Entscheidungen (Retry/Skip/Abort)
- Checkpoint-Management nach jedem Experiment

### Agent I/O Schemas

Jeder Agent hat formale Input/Output Schemas im JSON-Format.
Ermöglicht Schema-Validierung durch den Orchestrator und
bessere Fehlerdiagnose bei malformierten Agent-Outputs.

### Category-Grouped History

History wird dem Hypothesis Agent nicht chronologisch, sondern
nach Kategorien gruppiert übergeben. Pro Kategorie sieht er:
- Anzahl Versuche, Erfolge, Reverts
- Beste Mutation und bestes Delta
- Near-Miss-Kandidaten

CLI: `python3 scripts/composite_score.py group-history <history-path>`

## Limitierungen

- **Subjektive Qualität**: Assertion-basierte Metriken (Skill-Modus) können nicht alle
  Qualitätsaspekte erfassen. Der LLM-as-Judge hilft, ist aber selbst imperfekt.
- **Kosten**: Jedes Experiment braucht mehrere LLM-Aufrufe (Eval-Runs, Grading,
  Hypothese, Mutation). ~10 Experimente ≈ 50-100 API-Calls.
- **Konvergenz**: Bei starken Scores (>0.90) werden Verbesserungen
  schwieriger zu finden. Die Coverage-Matrix hilft, Plateaus zu erkennen.
- **Eval-Qualität**: Die Qualität der Evals bestimmt die Qualität der Optimierung.
  Schlechte Evals → Optimierung auf falsche Ziele.
- **Command-Stabilität**: Im Generic-Modus muss der Metrik-Command deterministisch
  sein. Flaky Commands führen zu falschen KEEP/REVERT-Entscheidungen.
- **Rauschgrenze ungemessen**: `noise_floor` ist als Config-Key vorhanden und geht
  über `threshold = max(improvement_threshold, noise_floor, resolution)` in die Entscheidung
  ein, steht aber auf 0.0 und hat damit derzeit keine Wirkung. Der Wert ist ein
  Platzhalter. Wie stark der Score zwischen zwei identischen Läufen streut, ist
  bisher nicht gemessen worden; das passiert erst mit Block 2. Bis dahin gilt:
  eine Keep-Schwelle von 0.02 ist eine Setzung, keine Ableitung aus Messdaten, und
  bei Evals mit wenigen Assertions kann eine einzelne gekippte Assertion sie
  bereits überschreiten.
