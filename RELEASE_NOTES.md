# Release Notes

## v3.4 (2026-07-29): Härtung nach der adversarialen Review

Fünf unabhängige Prüfungen über Block 2 bis 4: Code je Block, Doku gegen Code,
und ein Mutationstest über 69 gezielte Codeänderungen. 63 Befunde, 14 davon
hoch. Die wichtigsten:

**Geschützte Regionen waren umgehbar.** `extract_regions` nahm nur das erste
Vorkommen; ein zweites Markerpaar am Dateiende wurde nie verglichen und von
`strip_regions` zusätzlich aus jeder Längenmessung entfernt. Jetzt zählt die
Prüfung die Marker, und Duplikate wie halb offene Regionen sind eigene
Verletzungsarten.

**Eine Notiz konnte die Region verschieben.** Enthielt ein Text wörtlich einen
Marker, wanderte die Regionsgrenze dauerhaft, und ab da meldete jede Prüfung
eine Verletzung, ohne dass jemand die Ursache sah. Marker im Notiztext werden
jetzt entschärft, und der Schreibvorgang prüft die Markerlage vorher.

**Ein verwaister START-Marker löschte den halben Dateirest**, inklusive der
FORGE_KEEP-Region des Users, und meldete Erfolg. Eine halb vorhandene Region
ist jetzt ein Abbruchgrund, kein Anlass zum Überschreiben.

**Zwei Assertion-Flips entschieden per Float-Rundung.** `resolution = 2/N`
liegt exakt auf dem Quantisierungsraster des Scores; über N = 5 bis 60 fiel der
strikte Vergleich in 33 von 56 Fällen auf NEUTRAL, obwohl der Docstring zwei
Flips als gemessene Änderung führt. Die Grenzen sind jetzt inklusiv mit einem
Epsilon, und `score` gibt die Auflösung ungerundet aus.

**Der Invarianten-Command erbte stdin.** Im dokumentierten Pipeline-Aufruf steht
dort der Metrik-Output; ein Command, der stdin anfasst, hätte ihn weggefressen.
Jetzt `stdin=DEVNULL`, eigene Prozessgruppe, und `metric` liest stdin zuerst.

**Die Scope-Invariante prüfte nur die Dateizahl.** `total_bytes` wurde erhoben
und nie gelesen: alle Dateien zu leeren hielt die Kardinalität konstant und
verbesserte jede Zeilen- oder Fehlerzahl. Jetzt zählen Bytes und die Schnittmenge
der ursprünglich gemessenen Pfade mit.

**`hash_paths` ignorierte Verzeichnisse still.** Die Wizard-Vorschlagsliste
nennt `tests/` als Verzeichnis, und der gesamte Ordner war ungeschützt. Ein
geschützter Pfad, der zu keiner Datei auflöst, bricht jetzt ab.

Dazu: `compare_runs` aggregiert mehrere grading.json je Seite statt sie nach
Sortierreihenfolge zu überschreiben und wertet `total == 0` als "nichts
gemessen" statt als Regression; `make_diff` erzeugt gültige Patches auch ohne
Schluss-Newline und liest mit explizitem UTF-8; `artifact_stats` dedupliziert
und überlebt Binärdateien; ein leerer test-Split wird gemeldet statt als
Holdout ausgewiesen; der val-Fallback zieht nachweislich nur aus train.

**Testsuite von 214 auf 270.** `tests/test_review_findings.py` pinnt jeden
Befund und die Lücken aus dem Mutationstest, darunter die Schwellen-Grenzfälle,
der INVALID-Abzug in der Sättigung, der TSV-Lesepfad und elf bis dahin
ungetestete Subcommands.


## v3.3 (2026-07-29): Block 4, der Loop kann das Gemessene nicht mehr kleiner machen

**Reward-Hacking-Schutz im Generic-Modus.** Bisher akzeptierte der Loop jede
Verbesserung, die mit Exit-Code 0 zurückkam. Die optimale Mutation für
`flake8 src/ | wc -l` ist damit, `src/` zu löschen; bei `flake8 src/ | wc -l`
ist der Exit-Code ohnehin immer der von `wc`. Neu: `invariants-snapshot` vor der
Mutation, `invariants-check` danach, drei Invarianten (geschützte Pfade
unverändert, Scope nicht geschrumpft, `invariant_command` grün). Der
`metric`-Subcommand nimmt den Nachweis entgegen und liefert ohne ihn keinen
Wert, sondern `{"decision": "INVALID"}` und Exit 3. Der Invarianten-Command
läuft nur, wenn die geschützten Pfade unverändert sind.

**Token-Budget mit Konsequenz.** `artifact-stats` misst SKILL.md plus alle vom
Loop erzeugten Dateien unter `references/` und `scripts/`, gegen ein Budget aus
`max(2000, ceil(initial * 1.25))`. Exit 1 bei Überschreitung, danach ist die
nächste Runde auf `efficiency` und `prune` festgelegt. Der Scope umfasst
bewusst mehr als die Hauptdatei: ein Budget, das nur SKILL.md zählt, ist über
`reference_add` in einer Runde umgangen. Divisor 3 statt 4, weil deutsche
Komposita schlechter tokenisieren.

**Meta-Memory.** `agents/meta.md` schreibt alle 5 Experimente
`<workspace>/editing-notes.md` neu: welche Mutationstypen bei diesem Skill
genommen haben, auf welcher Formulierungsebene Änderungen gewirkt haben, welche
Kategorien Regressionen erzeugt haben. Optimizer-seitig, nie im Ziel-Skill.
Belegpflicht (jeder Bullet nennt eine Experiment-ID) und Verdikt-Pflicht (kept,
revised, removed) verhindern, dass die Datei nur wächst. Läuft nur, wenn
mindestens drei Experimente KEEP oder REVERT tragen.

**Evidenz nie kürzen.** Die 30-Prozent-Context-Regel gilt ab jetzt ausdrücklich
für History, Coverage und Meta-Notizen, nicht für die Transcripts des aktuellen
Experiments. Gekürzte Transcripts erzeugen plausible, aber falsche
Ursachenanalysen, und aus einer falschen Ursache wird eine Regel, die das Gate
nicht bewegt und trotzdem Platz kostet.

**Nicht übernommen:** SkillOpts Semantic-Density-Bonus. Die Elf-Wort-Liste ist
englisch, die Artefakte hier sind deutsch.

**Neue Subcommands:** `artifact-stats`, `invariants-snapshot`,
`invariants-check`. `metric` hat zwei neue Flags.


## v3.2 (2026-07-29): Block 3, was das Gate umgeht, ist jetzt geschützt

**Geschützte Regionen.** Zwei Marker-Paare in der Ziel-SKILL.md:
`FORGE_KEEP` gehört dem User und wird vom Loop nie angefasst, `FORGE_APPENDIX`
gehört dem Loop und nimmt Notizen auf, die das Gate umgehen. Durchgesetzt mit
`verify-regions`, byteweise, Exit 1 bei Verletzung. Auch eine neu *angelegte*
Region ist eine Verletzung, sonst baut sich der Mutator einen Schutzraum, den
das Gate nie sieht. Die Prüfung läuft in Python und nicht als Punkt auf der
Sanity-Liste des Mutators: ein Agent, der eine Regel nicht befolgt hat, per
Prompt prüfen zu lassen, ob er sie befolgt hat, ist zirkulär.

**SKILL_DEFECT gegen EXECUTION_LAPSE.** Jedes Failure-Pattern wird vor der
Ursachensuche klassifiziert: gibt es im Skill bereits eine Regel, die den Fehler
verhindert hätte? Ja bedeutet Lapse und erzeugt keine Mutation, sondern eine
Appendix-Notiz. Im Zweifel Lapse. Vorher unterstellten alle sechs Root Causes,
dass der Skill schuld ist; ein einzelner Subagent-Ausrutscher kostete damit eine
korrekte Regel, und das Gate merkte es nicht, weil der Unterschied unter der
Auflösungsgrenze liegt. Neu: `append_appendix_notes` mit Dedup über Kanonform
und Deckel bei 15, Subcommand `appendix-append`.

**Erfolgsanalyse.** Der Hypothesis-Agent sieht jetzt auch die bestandenen
train-Evals und liefert `success_patterns`. Der Zweck ist nicht die
Erfolgsmeldung, sondern die Schutzliste: der Mutator prüft vor `prune` und
`structure_change` dagegen, ob der Abschnitt gerade bestandene Evals trägt.

**Rejected-Buffer.** `rejected.jsonl` hält jede Nicht-KEEP-Entscheidung im
Wortlaut fest, unberührt von der History-Kompaktierung, und `rejected-format`
rendert daraus den Prompt-Block. Vorher gelangten nur Near-Misses in den Prompt,
und nie der konkrete Änderungstext.

**Drei Kandidaten mit Ranking.** Statt einer Hypothese erzeugt der Agent drei
und ranked sie im selben Prompt gegen vier Kriterien. Angewendet wird weiterhin
genau eine Änderung. Das Ranking steht nach Near-Miss- und Duplikat-Check.

**Regelform.** Jede neue Regel besteht aus Auslöseklausel, Handlung und einem
Negativteil, der den beobachteten Fehler benennt. Abschnitte werden nach dem
Fehlerfall benannt, nicht nach dem Thema.

**Schema-Prüfliste im Orchestrator.** Jede Agent-Antwort wird gegen eine
konkrete Feldliste geprüft, bevor irgendetwas angewendet wird. Rückfallpfade
bekommen einen Namen und landen in `decision.json`. Ein stiller Default ist ein
Fehler, der wie ein Ergebnis aussieht.

**Neue Subcommands:** `verify-regions`, `appendix-append`, `rejected-append`,
`rejected-format`.


## v3.1 (2026-07-29): Block 2, die Zahl bedeutet jetzt etwas

**Auflösungsgrenze.** Der Gate-Score ist seit v3 exakt die Assertion-Pass-Rate
und springt damit in Schritten von `1 / N`. Bei 9 Assertions bewegt ein
einzelner Flip 0.111, bei 31 noch 0.032. Die feste Keep-Schwelle von 0.02 lag
darunter und konnte deshalb nie greifen: jeder einzelne Flip löste KEEP aus.
Neu: `min_detectable_delta(N, flips=2)` und `decide(..., resolution=...)`.
Die Schwelle ist jetzt `max(improvement_threshold, noise_floor, resolution)`,
und `binding_threshold` sagt im Ergebnis, welcher der drei gebunden hat.
Subcommand: `resolution --assertions N`.

**Echter Dreiwege-Split.** `eval_split: 0.6/0.4` existierte nur als Zahl in der
Config, keine Zeile Code wies je einen Split zu, und der Loop fütterte die
Ergebnisse des Testsets in die Hypothesenbildung. Neu: `assign_split` über
`sha256(seed:id) % 100`, train 50 / val 25 / test 25, Subcommand
`split-assign`. Die Rollen sind getrennt: train erzeugt Hypothesen, val
entscheidet, test wird genau zweimal angefasst. Unter 12 Evals entfällt der
test-Split und der Report sagt das; unter 6 lehnt der Wizard ab. Bleibt val
leer, wird deterministisch ein Eval aus train dorthin gezwungen, nie aus test.

**Diff und NO_OP.** `make_diff` erzeugt einen Unified Diff gegen den Snapshot
und walkt beide Bäume, damit neu angelegte und gelöschte Dateien sichtbar
werden. Bei `changed: false` ist die Entscheidung `NO_OP`: kein Eval-Run, kein
Scoring, kein Coverage-Update. Vorher lief ein wirkungsloser Versuch durch die
volle Messung und landete als Neutralergebnis in der Statistik. Nebenbei zeigt
Guided-Checkpoint 3 jetzt das Diff, das er seit v2 versprochen hatte.

**Längsvergleich.** `compare_runs` paart dieselben Evals unter beiden Versionen
und sortiert nach `regressed`, `persistent_fail`, `improved`,
`stable_success`, Regressionen zuerst. Ein Aggregatscore verschluckt sie: fünf
neue Treffer gegen drei neue Fehler ergeben netto plus zwei und sehen wie
Fortschritt aus.

**Aufgelöst.** Der markierte Widerspruch über die Rotation des Test-Splits
zwischen SKILL.md und references/architecture.md ist entschieden: rotiert wird
ausschliesslich in train, val und test bleiben eingefroren.

**Neue Subcommands:** `resolution`, `split-assign`, `diff`, `compare`.


## Skill Forge v3.0.0 (2026-07-29)

Dieses Release repariert die Entscheidungsschicht. Der Loop hat vorher Zahlen produziert,
aber die Regel, die aus zwei Zahlen ein Urteil macht, war an mehreren Stellen dupliziert,
teilweise unerreichbar und nirgends getestet. Alles unten steht in
`scripts/composite_score.py`, Version 3.0.0, abfragbar über
`python3 scripts/composite_score.py --version`.

### Entscheidung

**`decide()` als Funktion und `decide` als Subcommand.** Die Entscheidung liegt jetzt an
genau einer Stelle. Vorher stand die Kaskade in Prosa in SKILL.md und musste bei jedem
Experiment vom Modell nachgerechnet werden.

```
python3 scripts/composite_score.py decide \
  --candidate 0.84 --baseline 0.78 --config <workspace>/config.json
```

Ausgabe ist JSON mit `decision`, `near_miss`, `delta`, `threshold`, den drei benutzten
Schwellen, `direction`, `relative`, `relative_fallback` und `formula`. `formula` ist eine lesbare Spur der
Rechnung und gehört in `decision.json`.

**Drei Ausgänge statt vier, der unerreichbare NEUTRAL-Zweig ist repariert.**

```
delta >= max(improvement_threshold, noise_floor, resolution)  →  KEEP
delta < -regression_threshold                     →  REVERT
sonst                                             →  NEUTRAL
```

`near_miss` ist ein boolesches Flag auf NEUTRAL, kein eigener Ausgang: true, wenn
`delta > threshold - near_miss_band`. Vorher war NEAR_MISS ein vierter Zweig in der
Kaskade, der NEUTRAL praktisch verdeckte. Über 4001 Deltas zwischen -0.20 und +0.20 fiel
die alte Reihenfolge 1800 mal auf KEEP, 1500 mal auf REVERT, 700 mal auf NEAR_MISS und
genau einmal auf NEUTRAL.

**NEUTRAL rollt zurück, Gleichstand eingeschlossen.** Die alte Regel lautete "NEUTRAL
heisst behalten, bei Gleichstand leichte Präferenz für das Neue". Ein Loop, der jede
Null-Runde behält, entfernt sich über zehn Experimente vom Ausgangspunkt, ohne dass eine
einzige Messung diese Distanz stützt. Keine seitwärts gerichteten Züge.

**Plateau-Kriterium angepasst.** `is_plateau(decisions, window=3)` prüft jetzt drei
aufeinanderfolgende Nicht-KEEP-Entscheidungen. Die alte Formulierung zählte nur
NEUTRAL/REVERT und liess NEAR_MISS aus, den mit Abstand häufigsten Ausgang der alten
Kaskade. Läufe im mittleren Band brachen deshalb nie ab.

### Snapshot und Revert

**`snapshot` und `revert` sind Subcommands.**

```
python3 scripts/composite_score.py snapshot \
  --target <pfad-oder-glob> --snapshot-dir <workspace>/snapshots --version pre-exp-001

python3 scripts/composite_score.py revert \
  --snapshot-dir <workspace>/snapshots --version pre-exp-001
```

`snapshot` legt fehlende Verzeichnisse an, löst Globs in Python auf und schreibt
`manifest.json` plus `files/<relpfad>`. `revert` stellt aus dem Manifest wieder her und
löscht Dateien im Scope, die nicht im Manifest stehen, also genau das, was die Mutation
neu angelegt hat. Vorher gab es einen Shell-Block mit `cp -r <datei> <dir>/v1/`, der ohne
existierendes Zielverzeichnis mit Exit 1 abbrach und ohne Trailing-Slash eine Datei namens
`v1` anlegte. Einen Revert gab es überhaupt nicht.

**Versionsschema `pre-exp-NNN`.** Snapshot-Verzeichnisse heissen `pre-exp-001`,
`pre-exp-002` und benennen den Zustand *vor* Experiment N. Die alten Namen `v0`, `v1`
kollidierten mit den Feldern `version: "v1"` und `parent: "v0"` in `history.json`, in denen
dieselben Strings etwas anderes bedeuten. Die Baseline vor Experiment 1 ist `pre-exp-001`.

### Scoring

**Efficiency entscheidet nichts mehr.**

- ohne Comparator: `composite = assertion_pass_rate * 1.00`
- mit Comparator: `composite = assertion_pass_rate * 0.65 + llm_judge_score * 0.35`
  (renormalisiert aus 0.50/0.30, nachdem der Efficiency-Anteil entfiel)

Efficiency wird weiter berechnet, steht unter `details.efficiency_score` und gehört in den
Morning Report. Vorher hing 0.20 des Gate-Scores an Tokens und Laufzeit: zwei Läufe mit
identischen Assertions liegen 0.045 auseinander, gerechnet aus der v2-Formel, bei einer
Keep-Schwelle von 0.02.

**`--side` beim Scoring ist Pflicht, wenn das Ergebnis stimmen soll.**

```
python3 scripts/composite_score.py score <exp-dir> --side with_mutation
python3 scripts/composite_score.py score <exp-dir> --side baseline
```

Erlaubt sind exakt `with_mutation` und `baseline`, die Verzeichnisnamen unter
`runs/eval-N/`. Ohne `--side` werden beide Seiten gemischt, was fast immer ein Fehler ist.

**Harter Fehler statt Score 0.20 bei leerem Verzeichnis.** Ohne gefundene Gradings bricht
`score` mit Exit 2 ab. Vorher lieferte ein leeres Experiment-Verzeichnis still 0.20, weil
`calc_efficiency_score(0, 0.0)` genau 1.0 ergibt und der Efficiency-Anteil 0.20 wog. Ein
abgestürzter Lauf sah damit aus wie ein schlechtes, aber gemessenes Ergebnis.

### Coverage-Matrix

**Sättigung rastet nicht mehr ein.** Sie wird bei jedem Update neu berechnet. Vorher wurde
`saturated` nur auf True gesetzt und nie zurückgenommen, eine Kategorie blieb also für den
Rest des Laufs deprioritisiert, auch wenn ein späteres Experiment dort wieder lieferte.
`INVALID`, `SKIP` und `NO_OP` zählen nicht in die Sättigung, ein Mutator-Fehler ist kein
Beleg gegen die Kategorie.

**`best_delta` ist richtungsbewusst.** Bei `lower_is_better` gewann vorher der schlechteste
Wert, weil das rohe Delta maximiert wurde. `coverage-update` hat dafür `--direction`
(Default `higher_is_better`).

**`--decision` wird validiert** gegen `KEEP|REVERT|NEUTRAL|SKIP|NO_OP|INVALID`, und pro
Kategorie kommen die Zählfelder `experiments_neutral` und `experiments_invalid` dazu.

### History und Resume

**`compact` archiviert statt zu löschen.** Die Volldatensätze gehen idempotent nach
`<workspace>/history.archive.jsonl`, bevor gekürzt wird, und die Kurzform behält
`mutation_type` und `near_miss`. Vorher entfernte die Kompaktierung unter anderem das Feld
`hypothesis`, das der Duplikat-Check braucht: nach der ersten Kompaktierung konnte der
Loop dieselbe Hypothese erneut vorschlagen.

**Neue Felder in `checkpoint-save`:** `--on-disk-version <pre-exp-NNN>`,
`--applied-but-undecided`, `--best-version <pre-exp-NNN>`, `--best-score <float>`,
`--experiment-index <int>`. Das entscheidende Feld ist `applied_but_undecided`: stirbt der
Prozess zwischen Mutation und Entscheidung, muss ein Resume zuerst auf `on_disk_version`
zurückrollen. Vorher stand im Checkpoint nichts darüber, welcher Zustand auf der Platte
liegt, ein Resume bewertete also womöglich eine mutierte Datei gegen eine Baseline, zu der
sie nicht mehr passt.

### Konfiguration

Neue Keys in `config.json`, es fällt nichts weg:

```json
"near_miss_band": 0.02,
"noise_floor": 0.0,
"gate_weights": null,
"workspace_path": "<absoluter Pfad>",
"target_path": "<absoluter Pfad>"
```

`near_miss_band` war vorher nirgends konfigurierbar. `noise_floor` ist ein Platzhalter für
die noch zu messende Lauf-zu-Lauf-Streuung und geht als `max(improvement_threshold,
noise_floor)` in die Keep-Schwelle ein. Werte aus `config.json` gewinnen über die
Argparse-Defaults, sonst driften Script-Default und konfigurierter Wert auseinander.

### Testsuite

Neue Testsuite: `conftest.py` im Repo-Root plus `tests/test_decide.py`, `tests/test_scoring.py`,
`tests/test_coverage.py`, `tests/test_snapshot_revert.py`, `tests/test_history.py`:

```
python3 -m pytest tests/ -q
```

Vorher gab es keinen einzigen Test. Der unerreichbare NEUTRAL-Zweig war genau die Art
Fehler, die drei Zeilen Test sofort gezeigt hätten.

### Geänderte Dateien (v3)

| Datei | Änderung |
|-------|---------|
| `scripts/composite_score.py` | `decide()`, `snapshot`/`revert`, `--side`, Gate-Gewichte, Coverage-Fixes, Checkpoint-Felder, Version 3.0.0 |
| `conftest.py`, `tests/` | Neu: pytest-Suite, die jeden oben genannten Fehler pinnt |
| `agents/orchestrator.md` | Neu: Context Assembly, Übergabeprotokoll, Checkpoints |
| `templates/agent_context.md` | Neu: Laufzeit-Kontext für die Agent-Prompts |
| `SKILL.md`, `agents/*`, `references/architecture.md`, `templates/morning_report.md` | Auf die neue Kaskade, `pre-exp-NNN` und die Subcommand-Aufrufe gezogen |
| `README.md` | v3, vier Agenten, neun TSV-Spalten, Einordnung der v2-Zahlen |

---

# Release Notes — Skill Forge v2.0

## Überblick

Dieses Release ist das Ergebnis einer systematischen Eigenoptimierung des Skills.
Aus der praktischen Nutzung und der Analyse wiederkehrender Problemmuster haben sich
fünf funktionale Erweiterungen herauskristallisiert, die den Skill robuster, breiter
einsetzbar und transparenter machen.

## Neue Features

### 1. Dry-Run-Validierungsgate

Der Loop startet nicht mehr blind. Ein neuer Wizard-Schritt 5 prüft vor dem ersten
Experiment, ob die gesamte Infrastruktur funktioniert:

- Im Skill-Modus: Ein Probe-Eval läuft, Grading wird auf valides JSON geprüft, Composite Score muss berechenbar sein
- Im Generic-Modus: Der Metrik-Command wird ausgeführt, Exit-Code und parsbare Zahl werden validiert

Bei Fehler gibt es konkrete Korrekturvorschläge statt eines stummen Abbruchs nach Stunden.

### 2. Interaktiver Setup-Wizard

Das bisherige Setup (Schritt 0) war eine Prosa-Beschreibung. Jetzt gibt es einen
formalisierten 6-Schritt-Wizard mit harten Abnahmekriterien pro Schritt:

1. Modus und Ziel erfassen
2. Scope definieren und validieren (Glob muss matchen)
3. Metrik definieren (subjektive Metriken werden abgelehnt)
4. Richtung festlegen (höher/niedriger ist besser)
5. Dry-Run-Validierung (hartes Gate)
6. Konfiguration bestätigen (mit Anpassungsmöglichkeit)

Die gesamte Konfiguration wird als `config.json` gespeichert und von Scheduled Tasks wiederverwendet.

### 3. Generic-Modus (Domänen-Generalisierung)

Der Skill war bisher auf SKILL.md-Optimierung beschränkt. Der neue Generic-Modus
wendet das gleiche Autoresearch-Prinzip auf beliebige Dateien und mechanische Metriken an:

- Testabdeckung erhöhen (Jest, pytest, etc.)
- Bundle-Size reduzieren
- Lighthouse-Score verbessern
- Docker-Image verkleinern
- Lint-Fehler eliminieren
- Jede andere Metrik, die ein Shell-Command als Zahl liefert

Der Modus wird automatisch erkannt oder kann manuell gesetzt werden.
Agenten-Prompts und Scoring-Logik wurden für beide Modi erweitert.

### 4. Flaches TSV-Log

Neben dem strukturierten `history.json` gibt es jetzt ein `experiment-log.tsv` —
eine Zeile pro Experiment im Tab-separierten Format. Das ermöglicht:

- Schnelles Scannen mit `cat`, `grep`, `tail -f`
- Sofortige Übersicht nach nächtlichen Runs
- Einfache Weiterverarbeitung mit `awk` oder Spreadsheets

Das TSV-Log wird automatisch bei jedem Experiment aktualisiert.
Das Script `composite_score.py` hat neue CLI-Commands für TSV-Initialisierung und -Append.

### 5. Coverage-Matrix

Ein neues Tracking-System, das zeigt welche Bereiche des Optimierungsziels wie
intensiv bearbeitet wurden:

- 8 vordefinierte Kategorien im Skill-Modus (formatting, content_quality, examples, workflow, edge_cases, efficiency, scripts, structure)
- Dynamische Kategorien im Generic-Modus (aus Code-Struktur abgeleitet)
- Sättigungserkennung: Nach 3 erfolglosen Experimenten in einer Kategorie wird sie deprioritisiert
- Exploration-Exploitation-Balance: Anfangs breit, später gezielt

Der Hypothesis-Agent nutzt die Matrix aktiv für die Priorisierung und dokumentiert
seine Entscheidung im `coverage_rationale`-Feld.

### 6. Guided-Modus (interaktive Ausführung)

Neuer `execution_mode`-Parameter mit zwei Optionen:

- **Auto** (Standard): Vollautonomer Loop — perfekt für Overnight-Runs und Scheduled Tasks
- **Guided**: Interaktiver Loop mit 5 Checkpoints, an denen der User mitentscheidet

Im Guided-Modus pausiert der Loop an diesen Stellen:

1. **Evals prüfen** — User sieht und passt generierte Evals an (Anzahl, Gewichtung, Inhalt)
2. **Hypothese prüfen** — User bestätigt, passt an oder gibt eigene Hypothese vor
3. **Mutation prüfen** — User sieht Diff und bestätigt oder korrigiert
4. **Ergebnis bewerten** — User sieht Score/Delta und kann Empfehlung überstimmen
5. **Weitermachen?** — User entscheidet: weiter, N Runden, oder stopp

Der Guided-Modus ist ideal für die erste Nutzung mit einem neuen Skill, wenn
Domänenwissen eingebracht werden soll, oder um Vertrauen in den Loop aufzubauen
bevor man ihn autonom über Nacht laufen lässt.

### Bugfixes und Konsistenz

- Crash-Limit einheitlich auf 3 gesetzt (war inkonsistent 2/3)
- Skill-Name durchgehend auf `skill-forge` korrigiert
- Abhängigkeit zum `skill-creator` als optional deklariert (Standalone-Betrieb funktioniert)
- Einschränkung des Metrik-Parsers (letzte Zahl im Output) dokumentiert

## Geänderte Dateien

| Datei | Änderung |
|-------|---------|
| `SKILL.md` | Komplett überarbeitet: Zwei Modi, Setup-Wizard, TSV-Log, Coverage-Matrix, Crash-Handling |
| `agents/hypothesis.md` | Coverage-Matrix als Input, Generic-Modus Root Causes, Phasen-basierte Exploration |
| `agents/mutator.md` | Generic-Modus Mutationen, Kategorie-Pflicht, Crash-Handling |
| `agents/scorer.md` | Klarstellung: Nur Skill-Modus (Generic nutzt Command direkt) |
| `scripts/composite_score.py` | TSV-Logging, Coverage-Matrix-Verwaltung, Generic-Metrik-Extraktion, CLI-Subcommands |
| `templates/morning_report.md` | Coverage-Sektion, TSV-Tail-Anzeige, Crash/Skip-Statistik |
| `references/architecture.md` | Wizard-Gates, Generic-Modus-Architektur, Crash-Handling-Diagramm |
| `references/scheduled_task_template.md` | Generic-Modus-Beispiel, config.json-basierte Konfiguration |

## Migration

Bestehende Workspaces (`history.json`) sind abwärtskompatibel. Beim ersten Start
mit v2 werden fehlende Felder (`mode`, `category`, `consecutive_crashes`) mit
Standardwerten ergänzt. Die `config.json` wird beim nächsten Wizard-Durchlauf erstellt.

Neue Dateien (`experiment-log.tsv`, `coverage-matrix.json`) werden automatisch
initialisiert, wenn sie noch nicht existieren.
