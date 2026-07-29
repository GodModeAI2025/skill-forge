# Was Skill Forge von microsoft/SkillOpt lernen kann

Stand: 2026-07-28. Grundlage: vollständiger Deep-Read von `microsoft/SkillOpt`
(15.254 Sterne, MIT, erstellt 2026-05-08, aktiv) gegen den Ist-Zustand dieses
Repos. Jede Empfehlung wurde gegen beide Quellen faktengeprüft; die
Korrekturen sind eingearbeitet.

## Umsetzungsstand

**Block 1 ist umgesetzt (2026-07-29).** Teil A vollständig, dazu die Testsuite
aus B16 und die Doku-Korrekturen aus B17 Teil A. Die Beschreibungen in Teil A
sind ab hier historisch: sie beschreiben den Zustand vor der Reparatur und
begründen, warum die jeweilige Änderung nötig war.

Zwei Review-Wellen liefen über die Umsetzung. Die erste, über Block 1, fand
unter anderem einen `revert`, der Dateien ausserhalb seines Scopes löschte. Die
zweite, über Block 2 bis 4, brachte 63 Befunde, davon 14 hohe: ein zweites
Markerpaar umging die Regionsprüfung vollständig, eine Notiz mit dem Wortlaut
eines Markers verschob die Regionsgrenze dauerhaft, ein verwaister START-Marker
liess den Append den halben Dateirest löschen, `hash_paths` ignorierte
Verzeichnisse still, die Scope-Invariante prüfte nur die Dateizahl und nie die
Bytes, der `invariant_command` erbte stdin und hätte im Pipeline-Aufruf den
Messwert weggefressen, und die Keep-Grenze entschied bei genau zwei
Assertion-Flips per Float-Rundung.

Alle behoben und in `tests/test_review_findings.py` gepinnt. Ein Mutationstest
über 69 gezielte Codeänderungen fand zusätzlich 15 Stellen, an denen die Suite
grün blieb; die relevanten davon sind jetzt abgedeckt.

| Block | Inhalt | Stand |
|---|---|---|
| 1 | A1 bis A6, B16, B17 Teil A | umgesetzt |
| 2 | B1, B4, B7, B8 | umgesetzt |
| 3 | B2, B3, B5, B6, B9, B14 | umgesetzt |
| 4 | B10, B11, B12, B13 umgesetzt; B17 Teil B braucht einen echten Lauf | teilweise |
| optional | B15 (Harvesting) | offen, Entscheidung ausstehend |

---

## 0. Einordnung

SkillOpt und Skill Forge lösen dasselbe Problem: ein Markdown-Dokument als
trainierbaren Parameter behandeln und nur behalten, was messbar besser ist.
Die Konzepte überschneiden sich weiter, als man erwarten würde.

| Skill Forge | SkillOpt | Bewertung |
|---|---|---|
| Coverage-Matrix mit Sättigung | Exploration über LR-Schedule | eigenständig, gut |
| Near-Miss-Zustand | Rejected-Edit-Buffer im `step_buffer` | gleiche Idee, SkillOpt hat den Wortlaut |
| Tiered History Compaction | `_format_step_buffer` pro Epoche | gleiche Idee |
| Checkpoint/Resume | `runtime_state.json` | gleiche Idee |
| Eine Änderung pro Experiment | `learning_rate: 4` (Edits pro Schritt) | **Skill Forge ist strenger und hat recht** |
| Keep/Revert in Pseudocode | `evaluate_gate()` als reine Funktion mit Tests | **SkillOpt gewinnt deutlich** |

Der wichtigste strukturelle Unterschied: SkillOpts Entscheidungslogik ist Code
mit Tests, Skill Forges Entscheidungslogik ist Prosa in `SKILL.md`. Prosa
lässt sich nicht ausführen und nicht prüfen. Genau dort sitzen die Defekte.

Die Deep-Learning-Analogie aus `docs/guide/dl-analogy.md` ist der Kern von
SkillOpts Design und lohnt sich als Lesestoff komplett:

| Deep Learning | SkillOpt |
|---|---|
| Model weights | Skill-Dokument (Markdown) |
| Forward pass | Rollout |
| Loss function | Task-Evaluator |
| Backpropagation | Reflect |
| Gradients | Edit-Patches |
| Gradient clipping | Edit-Auswahl (`rank_and_select`) |
| Learning rate | max. Edits pro Schritt (Default 4, min 2) |
| LR-Scheduler | cosine / linear / constant / autonomous |
| Momentum | Slow Update am Epochenende |
| Meta-Learning | Meta-Skill (Optimizer-Gedächtnis) |
| Validation set | Selection-Split, entscheidet das Gate |
| Test set | Held-out, wird dreimal angefasst |

---

## Teil A: Defekte, die SkillOpt nur sichtbar macht

Das ist kein Lernen, das ist Reparatur. Ohne diesen Teil ist alles Weitere
Kosmetik, weil der Loop heute Entscheidungen trifft, die nicht bedeuten, was
sie behaupten.

### A1. Der NEUTRAL-Zweig ist unerreichbar

`SKILL.md:399-408` definiert vier Ausgänge. Über 4001 Deltas im Bereich
[-0.20, +0.20] ergibt sich: KEEP 1800, REVERT 1500, NEAR_MISS 700, NEUTRAL 1
(nur bei Delta exakt +0.02). Bedingung 3 wird vollständig vom Scheitern der
Bedingungen 1 und 2 impliziert.

Folge: NEAR_MISS ist der Auffangeimer für das gesamte mittlere Band, und das
Plateau-Abbruchkriterium `SKILL.md:482` nennt nur "3 aufeinanderfolgende
NEUTRAL/REVERT". Ein Auto-Lauf, der im mittleren Band hängt, bricht nie früh
ab und verbrennt sein Zeitbudget.

Zusätzlich widersprechen sich zwei Dateien über die zentrale Entscheidung:

- `README.md:102-108`: `else: NEUTRAL  # Keep (slight preference for new)`
- `SKILL.md:404-408` + `references/architecture.md:354-360`: dasselbe Band
  ergibt NEAR_MISS, und NEAR_MISS bedeutet Revert.

Wer README liest, implementiert Keep. Wer SKILL.md liest, implementiert
Revert. Für dieselbe Zahl.

**Fix, nach dem Vorbild von `skillopt/evaluation/gate.py`:**

```python
def decide(cand: float, base: float, *,
           improvement: float = 0.02,
           regression: float = 0.05,
           near_miss_band: float = 0.02,
           noise_floor: float = 0.0) -> dict:
    delta = cand - base
    threshold = max(improvement, noise_floor)
    if delta > threshold:
        decision = "KEEP"
    elif delta < -regression:
        decision = "REVERT"
    else:
        decision = "NEUTRAL"
    near_miss = decision == "NEUTRAL" and delta > threshold - near_miss_band
    formula = (f"delta = {cand:.4f} - {base:.4f} = {delta:+.4f}; "
               f"keep_if delta > {threshold:.4f} -> {decision}")
    return {"decision": decision, "near_miss": near_miss, "delta": delta,
            "threshold": threshold, "formula": formula}
```

Drei Ausgänge, `near_miss` als Flag statt als vierter Ausgang. SkillOpt macht
das genauso: drei Actions (`accept_new_best`, `accept`, `reject`), strikter
Vergleich `>`, Gleichstand ist Reject. `tests/test_gate.py:152` pinnt das
wörtlich als "no lateral moves".

Die Zeile `SKILL.md:407` ("NEUTRAL → Keep, bei Gleichstand leichte Präferenz
für Neues") muss weg. Ein Loop, der bei Null-Runden die neue Version behält,
driftet über zehn Experimente ohne jede Messung vom Ausgangspunkt weg.

Zusätzlich: `near_miss_threshold` ist der einzige Schwellenwert, der die
Semantik ändert, und steht in keiner Config-Tabelle. Er lebt als Prosa in
`SKILL.md:413`.

Subcommand: `decide --candidate F --baseline F [--config PATH]`, gibt JSON
plus Formel-String aus. SkillOpt-Sleep loggt die Formel in
`consolidate.py:311-320` genau deshalb ins Evidence-Log: damit im Nachhinein
steht, *warum* entschieden wurde, nicht nur *was*.

Plateau-Kriterium auf "3 aufeinanderfolgende Nicht-KEEP" umstellen.

---

### A2. Es gibt keinen Revert

`SKILL.md:403` sagt "REVERT → Zurück zur vorherigen Baseline". Das ist die
vollständige Spezifikation. Kein Script stellt einen Snapshot wieder her,
`composite_score.py` hat elf Subcommands und keiner heisst `revert`,
`agents/orchestrator.md:99` schliesst die Entscheidung explizit aus seinem
Zuständigkeitsbereich aus, ohne zu benennen wer sie ausführt.

Der Snapshot-Befehl selbst ist kaputt:

```bash
cp -r <target_path> <snapshot_dir>/v{N}/     # agents/mutator.md:56
```

Bricht reproduzierbar mit Exit 1 ab, wenn `v{N}` nicht existiert. Ohne
Trailing-Slash entsteht eine Datei namens `v1` statt eines Verzeichnisses.
Die Generic-Variante (`agents/mutator.md:62`) übergibt ein Glob als
`find`-Pfad und splittet ungequotet auf Leerzeichen.

Die dokumentierte Sicherheitsgarantie ist damit unwahr: eine erkannte
Regression wird geloggt und bleibt trotzdem in der Datei stehen.

**Fix:**

```python
def snapshot(target: str, snapshot_dir: str, version: str) -> dict:
    # Path(dst).mkdir(parents=True, exist_ok=True)
    # shutil.copy2 für Dateien, shutil.copytree(..., dirs_exist_ok=True)
    # Glob-Auflösung in Python: glob.glob(pattern, recursive=True)
    # schreibt manifest.json mit der Dateiliste
def revert(snapshot_dir: str, version: str) -> dict:
    # Kein target-Override: er konnte den Scope verbreitern und loeschte im
    # Test Nachbardateien. Das Ziel kommt ausschliesslich aus dem Manifest.
    # löscht im Scope alles, was nicht im Manifest steht
```

Das Manifest ist im Generic-Modus zwingend: legt die Mutation neue Dateien an,
bleiben die nach einem reinen Zurückkopieren liegen, und der Zustand ist weder
v(N) noch v(N+1).

`save_checkpoint` um `on_disk_version`, `applied_but_undecided`,
`best_version`, `best_score`, `experiment_index` erweitern. Ohne
`applied_but_undecided` kann ein Resume nach einem Crash zwischen Mutation und
Entscheidung nicht wissen, ob die Datei schon mutiert ist.
`get_resume_info` indiziert vier Felder direkt und wirft bei einem alten
Checkpoint einen KeyError; auf `.get()` mit Defaults umstellen.

Versionssemantik: `agents/mutator.md:56` sagt vN ist der Zustand *vor*
Experiment N, `references/architecture.md:143-144` sagt `version: v1,
parent: v0`, also vN als *Ergebnis*. Sauberste Auflösung: Snapshots in
`pre-exp-001/` umbenennen. Dann kollidiert nichts mehr.

Kein eigenes `best/`-Verzeichnis nötig. SkillOpt braucht das, weil sein
Slow-Update am Epochenende force-accepted wird und nie gegen val antritt.
Skill Forge hat keinen Force-Accept-Pfad, jede akzeptierte Version wurde
gemessen, `best` ist damit fast immer identisch mit `current`.
`best_version` und `best_score` als Checkpoint-Felder genügen.

---

### A3. Das Scoring mischt Kandidat und Baseline

`score_from_experiment_dir` (`composite_score.py:332`) sammelt per
`exp_path.rglob("grading.json")` **alle** Gradings unterhalb des
Experiment-Verzeichnisses ein, und `rglob("timing.json")` summiert alle
Timings. Die Verzeichnisstruktur laut `references/architecture.md:79-88` ist
aber `runs/eval-0/with_mutation/` **und** `runs/eval-0/baseline/`.

Der berechnete "Composite Score" ist damit der Mittelwert über beide Seiten.
Das ist kein Statistik-Problem, das ist ein Bug: die gemessene Grösse ist
nicht die, die entschieden wird.

```python
def score_from_experiment_dir(experiment_dir, use_comparator=False,
                              side: str | None = None) -> dict:
    # side in {"with_mutation", "baseline"}
    # rglob auf runs/*/<side>/ einschränken
    # bei grading_files_found == 0: harter Fehler, nicht 0.0
```

Der Verzeichnisname ist `with_mutation`, nicht `mutation`. Ein Filter auf
`runs/*/mutation/` findet nichts und liefert still 0.0, weil
`calc_assertion_pass_rate` bei `total_assertions == 0` einfach 0.0
zurückgibt. Der Fehler wäre unsichtbar.

---

### A4. Die Efficiency-Komponente ist ein Rauschverstärker

`calc_composite_score` gewichtet Efficiency mit 20 Prozent. `calc_efficiency_score`
normalisiert gegen die fixen Konstanten `max_tokens = 100000` und
`max_duration = 300.0`.

Gemessen: zwei plausible Läufe mit **identischen Assertions** ergeben Composite
0.8800 (20k Tokens, 60s) gegen 0.8350 (45k Tokens, 120s), gerechnet aus der
v2-Formel `0.8 * assertions + 0.2 * efficiency` bei einer Pass-Rate von 0.90.
Die Spanne ist in `tests/test_scoring.py` gepinnt. Schwankung 0.045
gegen eine Keep-Schwelle von 0.02.

Schlimmer: die Summierung läuft über alle Evals und beide Seiten (siehe A3),
skaliert also mit der Anzahl der Evals, während der Nenner konstant bleibt.
Bei fünf Evals mal zwei Seiten ist die Normalisierung sinnlos.

Und: ein leeres Experiment-Verzeichnis liefert
`{"composite_score": 0.2, "assertion_pass_rate": 0.0, "efficiency_score": 1.0}`,
weil `calc_efficiency_score(0, 0.0)` genau 1.0 ergibt. Ein Lauf, der nichts
protokolliert hat, bekommt perfekte Effizienz.

**Fix:** Efficiency fliegt aus dem Gate-Score und erscheint nur noch im
Report. Neue Gewichtung: ohne Comparator `assertions = 1.0`, mit Comparator
`assertions = 0.65 / judge = 0.35` (renormalisiert aus 0.50/0.30). Fehlende
`timing.json` heisst "keine Daten", nicht "perfekt".

SkillOpt hält seinen Gate-Score bewusst rein bei Task-Genauigkeit
(`hard` / `soft` / `mixed`) und regelt Länge separat.

---

### A5. Der Train/Test-Split ist Dekoration

`eval_split: 0.6/0.4` existiert als Tabellenwert (`SKILL.md:594`) und als
Array in `references/architecture.md:119`. Im ganzen Repo gibt es keine Zeile
Code, die einen Split zuweist. `composite_score.py` kennt das Wort "split"
nicht. Für `evals.json` existiert nirgends eine Feldliste.

Die Kontamination ist explizit:

- `SKILL.md:360` führt ausschliesslich das **Testset** aus.
- `SKILL.md:319-322` speist genau diese Ergebnisse und die Failure-Transcripts
  in die Hypothesenbildung.
- `SKILL.md:640` behauptet: "Die Held-out Evals werden nie für
  Hypothesenbildung genutzt, nur für Score-Berechnung."

Die mitgelieferte Beispielsession macht es vor:
`examples/fachbuch-lektorat-session.md` deklariert Split-Spalten (3 Train,
2 Test) und scored dann trotzdem alle fünf Evals gemeinsam als 27/31.

Dazu ein Widerspruch: `SKILL.md:638` will "den Test-Split rotieren",
`references/architecture.md:230` sagt "Behalte die Test-Evals unverändert".

---

### A6. Weitere gemessene Defekte

| Defekt | Ort | Wirkung |
|---|---|---|
| Sättigung rastet ein | `composite_score.py:302-306` | `saturated = True` ohne Gegenzweig; eine Kategorie erholt sich nie |
| `best_delta` ist richtungsblind | `composite_score.py:298`, `:712` | bei `lower_is_better` gewinnt die schlimmste Regression als Bestwert |
| `compact_history` löscht `hypothesis` | `composite_score.py:421-432` | genau das Feld, das der Duplikat-Check `agents/hypothesis.md:161-170` braucht; in-place, ohne Backup, harter `exp["id"]`-Zugriff. Seit Block 1 behoben |
| `coverage-update` wird nie aufgerufen | Grep über `SKILL.md`, `agents/`, `references/` | die Coverage-Matrix, die die Exploration steuert, wird von keinem dokumentierten Workflow aktualisiert |
| Drei statt vier Agents | `SKILL.md:651` | Orchestrator fehlt in der Aufzählung |
| 500-Zeilen-Regel ohne Konsequenz | `agents/mutator.md:136` | kein KEEP wurde je davon abgehalten; die eigene `SKILL.md` hat 676 Zeilen |
| Keine Tests, keine CI | Repo | 818 Zeilen tragen jede Keep/Revert-Entscheidung |
| Ergebnisse ohne Artefakte | `README.md:264-280` | drei behauptete Ergebnisse, im Repo weder `evals.json` noch `history.json` noch ein Snapshot |

---

## Teil B: Echte Übernahmen aus SkillOpt

### B1. Auflösungsgrenze statt gewürfelter Schwelle

**SkillOpt:** hat im Gate-Pfad selbst keine Statistik. `evaluate_gate`
vergleicht einen einzigen Rollout mit striktem `>`, `compute_score` bildet
`hard = sum(_hard(r) for r in results) / len(results)`. Kein CI, keine
Wiederholung. Das trägt dort, weil `sel_env_num: 0` den ganzen val-Split
verwendet (bei LiveMathematicianBench 124 Items, bei SpreadsheetBench 280).
Kompensiert wird redaktionell: der Blogpost `gating-reflection-safe-updates`
schreibt "The Sleep study is single-seed per cell; treat differences below
1.5 percentage points as noise."

SkillOpt-Sleep zieht für kleine Sets eine andere Konsequenz und setzt
`gate_metric: "mixed"` mit dem Kommentar `mixed best for tiny holdouts`
(`skillopt_sleep/config.py:56`), weil ein binärer Score bei wenigen Items zu
grob ist.

**Skill Forge kann diesen Verzicht gerade nicht übernehmen.** Nach A4 ist der
Score exakt die Assertion-Pass-Rate, ein einzelner Flip bewegt also
`1 / N_assertions`: bei 9 Assertions 0.111, bei 31 noch 0.032. Beides liegt
über 0.02. `IMPROVEMENT_THRESHOLD = 0.02` kann strukturell nie greifen, jeder
einzelne Assertion-Flip in einem einzigen Lauf löst KEEP aus.

**Übernahme:** die Schwelle an das Quantum koppeln.

```python
def min_detectable_delta(total_assertions: int, flips: int = 2) -> float:
    return flips / max(total_assertions, 1)
```

Keep-Bedingung: `delta > max(improvement_threshold, min_detectable_delta(N))`.
Der Wizard zeigt das vor dem Start an: "Auflösung: 0.065 bei 31 Assertions.
Änderungen unterhalb dieses Werts sind nicht messbar."

Wiederholungen (`repeats`, Default 2 bis 3) sind der zweite Baustein, aber
teuer: sie verdreifachen Laufzeit und Kosten pro Experiment, aus zehn
Experimenten pro Nacht werden drei. Das ist der richtige Tausch, aber der
Wizard muss die neue Experimentzahl vorher anzeigen.

**Wichtig:** Das im ersten Entwurf vorgeschlagene Subcommand
`null-run <workspace>` funktioniert nicht. `composite_score.py` liest
ausschliesslich JSON von der Platte, es hat kein `subprocess`, kein
Task-Spawning, keinen Zugriff auf Subagents. Im Skill-Modus fährt die LLM die
Evals per Subagent, nicht Python. Das Null-Experiment gehört als Schritt in
`SKILL.md`, das Aggregieren nach Python.

---

### B2. SKILL_DEFECT gegen EXECUTION_LAPSE

**SkillOpt:** `skillopt/optimizer/skill_aware.py` hängt per
`augment_error_prompt(p)` einen `ERROR_SUFFIX` an den Failure-Analyst-Prompt.
Jedes Failure-Pattern wird klassifiziert. Der Diskriminierungstest steht
wörtlich im Prompt (Zeile 75-77):

> Is there a rule in the current skill that, if followed, prevents this failure?

Ja bedeutet EXECUTION_LAPSE (die Regel stand da, der Agent hat sie ignoriert),
nein bedeutet SKILL_DEFECT (die Regel fehlt). Der Default ist asymmetrisch:
im Zweifel LAPSE.

Routing: DEFECT geht als normaler Edit in `patch.edits` und durchläuft das
Gate. LAPSE erzeugt **keinen** Body-Edit, sondern einen String in
`appendix_notes`, der in eine geschützte Region geschrieben wird.

`skillopt/optimizer/skill.py:27-30` definiert `_PROTECTED_REGIONS`; ein Edit,
der dort hineinzielt, bekommt Status `skipped_protected_region`.

Hinweis zur Ehrlichkeit: das Feature ist bei SkillOpt **opt-in und
standardmässig aus** (`use_skill_aware_reflection: false`). Bei
ausgeschaltetem Toggle bleiben die Prompts byte-identisch zur Baseline.

**Warum Skill Forge es trotzdem braucht:** `agents/hypothesis.md:120-126`
listet sechs Root Causes, und alle sechs unterstellen, dass der Skill schuld
ist. "Die Regel stand da und wurde ignoriert" kommt in keinem der vier
Agent-Prompts vor. In Kombination mit der Auflösungsgrenze aus B1 heisst das:
ein einzelner Subagent-Ausrutscher führt dazu, dass eine korrekte Regel
umformuliert oder gelöscht wird, und das Gate merkt es nicht.

**Übernahme:**

1. Neuer Abschnitt `### 2.5 Defect-vs-Lapse-Klassifikation` in
   `agents/hypothesis.md`, zwischen Failure-Analyse (endet Zeile 115) und
   Root-Cause-Analyse (beginnt Zeile 116). Diskriminierungsfrage wörtlich,
   Default LAPSE, mit dem Satz: "Eine gültige Regel wird nicht wegen eines
   einmaligen Ausrutschers geändert oder gelöscht."
2. Output-Schema an beiden Stellen (Zeile 37-59 und 184-206) um
   `failure_class: "SKILL_DEFECT" | "EXECUTION_LAPSE"` pro Pattern und um
   top-level `appendix_notes: [str]` erweitern.
3. Zwei geschützte Regionen in der Ziel-SKILL.md:
   `<!-- FORGE_KEEP_START/END -->` (User-Invarianten, der Loop fasst sie nie
   an) und `<!-- FORGE_APPENDIX_START/END -->` (LAPSE-Notizen, umgeht das
   Gate).
4. **Durchsetzung deterministisch, nicht per Prompt.** Der ursprüngliche
   Vorschlag wollte den Schutz im Sanity-Check des Mutators prüfen. Das ist
   zirkulär: ein Agent, der eine Regel nicht befolgt hat, prüft per Prompt, ob
   er sie befolgt hat. Stattdessen:

```python
def verify_protected_regions(snapshot_path: str, mutated_path: str) -> dict:
    # extrahiert Inhalte zwischen den Markern in beiden Dateien
    # byteweiser Vergleich -> {ok: bool, violated: [region_names]}
```

   Subcommand `verify-regions`, Exit 1 bei Verletzung, Aufruf verpflichtend in
   `SKILL.md` Schritt 2 nach der Mutation und vor Schritt 3. Bei Exit 1:
   Snapshot zurückspielen, Experiment als INVALID loggen.

5. **Reihenfolge ist der Stolperstein.** `SKILL.md:397-410` setzt bei REVERT
   den Snapshot zurück. Wer die LAPSE-Notiz vor der Gate-Entscheidung
   schreibt, verliert sie bei jedem REVERT und jedem NEAR_MISS. Der Append
   muss der letzte Schreibvorgang des Schritts sein.

6. Deckel bei 15 Notizen, Dedup per Kanonisierung
   (`re.sub(r"\s+", " ", s.lower()).strip().rstrip(" .;:,_-")`). Bei
   Überschreiten nicht still verwerfen, sondern melden.

---

### B3. Erfolge analysieren, nicht nur Fehler

**SkillOpt:** zwei getrennte Analysten mit unterschiedlichen Schemata und
asymmetrischer Autorität.

- `prompts/analyst_error.md` muss ein gezähltes `failure_summary` mit
  `{failure_type, count, description}` liefern, also eine
  Häufigkeitsverteilung über die Trajektorien des Minibatches
  (`gradient.minibatch_size: 8`).
- `prompts/analyst_success.md` liefert nur eine flache
  `success_patterns`-Liste plus zwei Konservatismusregeln: "Only propose
  patches for patterns NOT already covered in the skill" und "Prefer
  reinforcing existing sections over adding new top-level sections".
- `prompts/merge_final.md` kodiert die Asymmetrie: **"FAILURE PATCHES TAKE
  PRIORITY"**.
- `gradient/reflect.py:544-545` splittet Failures und Successes in getrennte
  Batch-Listen; die Analysten sehen nie gemischte Batches.

**Skill Forge:** es gibt keine Erfolgsanalyse. `agents/hypothesis.md:95` heisst
"Failure-Analyse" und hat keine Entsprechung für bestandene Evals.
`agents/scorer.md:31` gibt ein `strengths[]`-Array aus, das kein Konsument im
Repo liest.

**Warum das hier härter wiegt als bei SkillOpt:** Skill Forge mutiert eine
lebende SKILL.md mit Mutationstypen wie `prune` und `structure_change`. Ohne
benannte funktionierende Muster löscht der Mutator genau die Abschnitte, die
die bestandenen Evals tragen. Ein reiner Fehleranalysator ist ein monotoner
Regelanhäufer ohne Vergessensmechanismus.

**Übernahme:**

1. Abschnitt 2 wird `### 2a. Failure-Analyse`, neu dazu
   `### 2b. Success-Analyse` mit den beiden Konservatismusregeln wörtlich.
   Ausgabefeld `success_patterns: [str]`.
2. **Entscheidend, und im Original-Vorschlag fehlend:** die Liste dient primär
   als *Schutzliste* für den Mutator. Wer `prune` oder `structure_change`
   vorschlägt, prüft gegen `success_patterns`, ob der Abschnitt gerade
   bestandene Evals trägt. `agents/mutator.md` bekommt eine Zeile, die
   `success_patterns` als Input liest. Ohne diesen Konsumenten bleibt das Feld
   genau so tot wie `strengths[]` heute.
3. `failure_summary: [{pattern, count, eval_ids, severity}]` ins Output-Schema.
   Pflicht ist `eval_ids`, nicht der Zähler: eine ID-Liste ist beim Lesen der
   `hypothesis.json` nachprüfbar, eine nackte Zahl nicht.
4. Support-Regel: `support_count >= 2` als Normalfall, darunter nur mit
   `single_eval_accepted: true` und Begründung. Bei kleinen Train-Sets
   relativ rechnen: `support_count >= max(2, ceil(0.4 * n_train_evals))`.
   Das ist **keine** SkillOpt-Mechanik (dort gibt es keinen numerischen
   Vergleich auf `support_count`, die Priorisierung läuft sprachlich über
   `ranking.md`), sondern die Formalisierung der bereits vorhandenen, aber
   unverbindlichen Regel `SKILL.md:328`.
5. **Overfitting-Leck:** die Success-Analyse muss explizit auf bestandene
   **Train**-Evals eingeschränkt werden, sonst leckt der Holdout über den
   neuen Block ins Skill. Im Prompt wörtlich verankern.

---

### B4. Dreiwege-Split mit stabiler Hash-Zuordnung

**SkillOpt:** `skillopt/datasets/base.py:151` definiert
`SPLIT_NAMES = ("train", "val", "test")`, Default `split_ratio = "2:1:7"`,
`split_seed = 42`, Allokation über `random.Random(split_seed)` plus
Largest-Remainder. Der Trainer gated ausschliesslich auf val (vier
Aufrufstellen `_build_eval_env(split="valid_seen")`) und fasst test genau
dreimal am Ende an: Baseline S_0, best, final. Der Split wird während eines
Laufs nie rotiert.

SkillOpt-Sleep macht die Zuordnung robuster: `assign_splits` bucketiert über
`int(sha256(str(seed) + t.id).hexdigest(), 16) % 100` gegen kumulative Cuts.
`consolidate.py:57-71` trägt die Regel "never silently use test as train or
val".

**Übernahme:**

1. train und val sind verpflichtend und haben getrennte Rollen.
   Failure-Analyse, Transcript-Lektüre und Hypothesenbildung laufen
   ausschliesslich auf train. Keep/Revert entscheidet ausschliesslich val.
2. test wird nur angelegt, wenn mindestens 12 Evals vorhanden sind. Darunter
   fährt der Loop einen ehrlichen Zweiwege-Split und der Report schreibt hin,
   dass es kein unabhängiges Holdout gibt. Ein Zwei-Item-Test als Holdout
   auszuweisen ist irreführender als gar keins.
3. Zuordnung über stabilen Hash pro Eval-ID:
   `int(sha256(f"{seed}:{eval_id}".encode()).hexdigest(), 16) % 100`.
   Neu generierte Evals aus der Rotation bekommen ihre Zugehörigkeit
   automatisch, ohne dass jemand eine Liste pflegt.
4. **Die IDs müssen sprechende, unveränderliche Slugs sein**, keine
   Positionsnummern. `evals.json` hat heute keine IDs, die Beispielsession
   nummeriert 1-5 in einer Markdown-Tabelle. Ein Hash über eine
   Positionsnummer ist wertlos: beim Löschen eines Evals wechseln alle
   nachfolgenden ihren Split. Umbenennen eines Slugs verschiebt das Eval und
   ist ein Re-Baseline-Ereignis.
5. **Degenerierte Splits sind bei kleinem N der Normalfall.** Bei 12 Evals und
   25/25 ist ein leeres val nicht unwahrscheinlich. Fallback nach
   SkillOpt-Vorbild: wenn val leer bleibt, wird deterministisch ein Eval nach
   val gezwungen. Der Fallback darf nie test nach train oder val ziehen. Ohne
   das gated der Loop irgendwann gegen eine leere Menge und meldet triumphal
   1.0.
6. Rotation nur innerhalb von train. val und test bleiben eingefroren; wer val
   ändert, muss neu baselinen.
7. Schema für `evals.json` überhaupt erst definieren:

```json
{"version": 1, "evals": [
  {"id": "ki-marker-entfernung", "prompt": "...",
   "assertions": [{"id": "...", "check": "...", "weight": 1.0}],
   "split": "train|val|test"}]}
```

---

### B5. Verworfene Änderungen im Wortlaut aufbewahren

**SkillOpt:** `engine/trainer.py` hält einen `step_buffer: list[dict]`, pro
Epoche frisch angelegt (Zeile 1068). Nach jeder Gate-Entscheidung landet
`{step, action, n_total, n_fail, failure_patterns}` darin, bei
`"reject" in action` zusätzlich `score_before`, `score_after` und
`rejected_edits`. `_format_step_buffer` (Zeile 523) rendert einen
Markdown-Block mit der Kopfzeile:

> Below is a summary of previous steps in this epoch. Use it to avoid
> repeating ineffective edits and to prioritise failure patterns that remain
> unsolved.

Injiziert wird der Block an drei Stellen: `adapter.reflect`,
`decide_autonomous_learning_rate`, `rewrite_skill_from_suggestions`.

**Skill Forge:** teilweise vorhanden. NEAR_MISS existiert als Zustand und wird
in `agents/hypothesis.md:149-159` für Variationen genutzt. Aber:

- Der Buffer deckte nur das Band [-0.05, +0.02) ab. Seit Block 1 ist near_miss
  ein Flag auf NEUTRAL im Band knapp unter der Keep-Schwelle.
- `compact_history` löschte `hypothesis` für alles älter als fünf Experimente,
  genau das Feld, das der Duplikat-Check braucht. Ab Experiment 6 sah der
  Agent, dass "workflow" viermal reverted wurde, aber nicht was versucht wurde.
  **Seit Block 1 behoben:** die Volldatensätze gehen idempotent nach
  `history.archive.jsonl`, und `mutation_type` sowie `near_miss` bleiben in der
  Kurzform erhalten. Was weiterhin fehlt, ist der wörtliche Änderungstext.
- Es gibt nie einen **wörtlichen** Änderungstext, nur Prosa-Zusammenfassungen.

Korrektur zur ersten Diagnose: die Daten verschwinden nicht komplett.
`experiment-log.tsv` ist append-only und wird von der Kompaktierung nie
angefasst, `decision.json` pro Experiment überlebt ebenfalls. Der echte Defekt
ist schmaler: sie gelangen nur für Near-Misses in den Prompt und liegen nie im
Wortlaut vor.

**Übernahme:**

1. `rejected.jsonl` im Workspace-Root, kompaktierungsfest, eine Zeile pro
   Nicht-KEEP (REVERT und NEUTRAL eingeschlossen), mit Feld
   `near_miss: true|false`.
2. Den wörtlichen Diff aus den ohnehin vorhandenen Snapshots rekonstruieren:
   `git diff --no-index snapshots/pre-exp-{N-1} snapshots/pre-exp-{N}`. Erste
   drei Hunks, je 200 Zeichen. Das spart jede Prompt-Disziplin im Mutator.
   (Anmerkung: SkillOpts `short_item_summary` kürzt entgegen dem ersten
   Eindruck **nicht**, der Kommentar dort lautet "Truncation disabled: the
   optimizer is given the full item description." Die 200-Zeichen-Grenze ist
   eine eigene Entscheidung, kein SkillOpt-Vorbild.)
3. `format_rejected(path, limit=10) -> str` rendert den Prompt-Block mit
   SkillOpts Kopfzeile, eingehängt als Abschnitt `## Bereits verworfen` in
   `templates/agent_context.md`. `## Near-Miss Hypothesen` bleibt stehen.
4. `compact_history` repariert: Volldatensätze vorher nach
   `history.archive.jsonl`, `exp.get("id")` statt `exp["id"]`.
   **Idempotenz beachten:** `SKILL.md:288` lässt die Kompaktierung ab
   Experiment 6 in jeder Runde laufen; ohne Filter auf `_compacted` wird
   exp-001 bei jedem Durchlauf erneut archiviert.
5. **Kein mehrzeiliger Text als CLI-Argument.** Anker und Ersatz enthalten
   Zeilenumbrüche, Anführungszeichen und Backticks;
   `rejected-append --hypothesis "..."` zerbricht am ersten Codeblock.
   `--from-json <pfad>` oder stdin.

---

### B6. Drei Hypothesen, feste Rubrik, eine Anwendung

**SkillOpt:** trennt zwei Urteile, die es bewusst nicht vermischt.
Aggregation (`gradient/aggregate.py`) fragt "sind das dieselben Edits?".
Clipping (`optimizer/clip.py`, `rank_and_select`) fragt danach "welche sind
die wichtigsten?" gegen vier geordnete Kriterien aus `prompts/ranking.md`:

1. **Systematic impact** ("A rule that fixes 50% of failures beats one that
   fixes a single edge case")
2. **Complementarity** (füllt eine Lücke, dupliziert nicht)
3. **Generality**
4. **Actionability**

Ausgabe ist ein JSON-Objekt mit `reasoning` und `selected_indices`
(0-basiert, in Prioritätsreihenfolge). Bei Fehlschlag greift ein Fallback auf
einfache Truncation.

**Skill Forge:** `agents/hypothesis.md:138` erzeugt genau eine Hypothese.
Kein Kandidatenpool, kein Ranking, keine Kriterien. Die Priorisierung ist der
Satz `SKILL.md:326` "Fokus auf die Änderung mit dem höchsten erwarteten Impact".

Ein Einzelschuss-Prompt greift die erstbeste plausible Ursache. Und
Guided-Checkpoint 2 bietet dem User bisher nur "Andere Idee", wo er selbst
eine erfinden muss statt zwischen dreien zu wählen.

**Übernahme (reine Markdown-Arbeit, null zusätzliche Agent-Aufrufe):**

1. `agents/hypothesis.md` Abschnitt 4: "Formuliere DREI Hypothesen" im
   bestehenden Sechs-Felder-Format je Kandidat.
2. Diversitäts-Nebenbedingung **phasenabhängig**, nicht absolut: in Früh- und
   Mittelphase mindestens zwei Kategorien der Coverage-Matrix, in der
   Spätphase reichen drei verschiedene Root Causes oder drei verschiedene
   Mutation-Typen. Sonst kollidiert die Regel mit der Exploitation-Strategie
   aus Abschnitt 1.
3. Neuer Abschnitt `### 7. Kandidaten ranken` mit den vier Kriterien in
   dieser Reihenfolge, für Skill Forge übersetzt statt wörtlich kopiert:
   Systematic impact = "eine Regel, die in 3/3 Runs failende Assertions
   adressiert, schlägt eine für einen Einzelfall". Complementarity = "füllt
   eine Lücke in der aktuellen SKILL.md und in der Coverage-Matrix".
4. **Reihenfolge im Prompt ist entscheidend:** der Ranking-Abschnitt muss
   NACH dem Duplikat-Check (Abschnitt 5) und dem Near-Miss-Check (4.5)
   stehen. Sonst rankt das Modell Kandidaten, die es gleich danach verwirft.
5. `selected_index` validieren: 0-basiert, Länge 3. `clip.py` filtert die
   Indizes explizit (isinstance, Range, Dedup), weil LLMs hier 1-basiert
   zählen oder out-of-range liefern. Der Orchestrator prüft und fällt bei
   Ungültigkeit auf `candidates[0]` zurück.
6. **Angewendet wird weiterhin genau eine Änderung.** Die Regel
   `SKILL.md:346` ("eine fokussierte Änderung pro Experiment") ist strenger
   als SkillOpts `edit_budget: 4` und sichert die Attribution von
   Score-Bewegungen. Ein Edit-Budget von 4 einzuführen wäre ein Rückschritt.
7. **Kein `deferred.jsonl`.** Nicht gewählte Kandidaten aufzuheben klingt
   sparsam, ist aber falsch: SkillOpt trägt bewusst nichts über den Schritt
   hinweg. Ein aufgehobener Kandidat wurde gegen eine SKILL.md formuliert, die
   nach einem KEEP nicht mehr existiert, und gegen veraltete Eval-Ergebnisse.

---

### B7. Verankerte Edits, Diff, NO_OP-Bucket

**SkillOpt:** vier Operationen mit exakten Substring-Ankern
(`types.py:23`: `EditOp = Literal["append", "insert_after", "replace",
"delete"]`). `optimizer/skill.py` matcht wörtlich, erste Fundstelle,
`count=1`, und verweigert das Raten: ein fehlender Anker liefert
`skipped_replace_target_not_found` beziehungsweise
`skipped_delete_target_not_found`, `insert_after` ohne Anker degradiert zu
`append`. Jeder Edit liefert `{op, target[:200], content_preview[:200],
status}`, jeder Edit ist in try/except gekapselt.

SkillOpt-Sleep (`memory.py:87-151`) führt einen dritten Bucket `unmatched`,
und `cycle.py:186` rendert im Report die Überschrift:

> ## Proposed but changed nothing (never reached the gate)

**Skill Forge:** der gesamte Anwendungsschritt ist ein Satz
(`agents/mutator.md:100`): "Führe die Änderung durch mit dem Edit-Tool.
Dokumentiere jede Änderung." Es entsteht kein Diff, kein Patch-File, kein
strukturiertes Edit-Objekt.

Ein Vorteil gegenüber SkillOpt: das Edit-Tool scheitert bei fehlendem Anker
laut, das Unmatched-Problem ist hier kleiner. Deshalb ist Anker-Bookkeeping in
JSON überflüssig. Was fehlt, ist der Diff.

**Übernahme, auf den Diff-Kern reduziert:**

1. `make_diff(snapshot_path, target_path, out_path) -> dict` auf Basis von
   `difflib.unified_diff`, Rückgabe `{lines_added, lines_removed,
   files_changed, files_added, files_deleted, changed}`.
2. **Neu angelegte Dateien sind der gefährlichste Fall.** `script_add` und
   `reference_add` erzeugen Dateien, die im Snapshot nicht existieren. Ein
   naiver Datei-gegen-Datei-Vergleich stempelt ein legitimes Experiment als
   NO_OP ab. `make_diff` muss beide Bäume walken, die Vereinigung der
   relativen Pfade bilden und fehlende Seiten als leere Liste übergeben.
   Gleiches gilt für Löschungen bei `prune`.
3. Bei `changed: false` Decision `NO_OP` (eigener Wert, nicht SKIP recyceln),
   kein Eval-Run, kein Scoring, keine Coverage-Aktualisierung. Ein Experiment
   ohne Byte-Änderung liefert per Konstruktion Delta null und darf nicht als
   Neutralergebnis zählen.
4. Guided-Checkpoint 3 zeigt `mutation.diff` statt einer Beschreibung. Der
   Checkpoint verspricht heute ein Diff, das nirgends entsteht. Die Semantik
   verschiebt sich dabei von "vor Anwendung" zu "angewendet, noch nicht
   evaluiert"; bei "Verwerfen" stellt der Loop aus dem Snapshot wieder her.
5. `templates/morning_report.md`: Abschnitt "Vorgeschlagen, aber wirkungslos",
   damit ein Lauf mit null Änderungen nicht als ruhige Nacht durchgeht.
6. `sanity_check_passed` ins mutation.json-Beispiel aufnehmen; das
   Output-Schema (`mutator.md:35`) führt es, das Beispiel nicht.

---

### B8. Längsvergleich auf identischen Aufgaben

**SkillOpt:** `optimizer/slow_update.py` `build_comparison_pairs` vergleicht
das boolesche Feld `hard` der alten und der neuen Version **je Task-ID**:

```python
if not prev_ok and curr_ok:      category = "improved"
elif prev_ok and not curr_ok:    category = "regressed"
elif not prev_ok and not curr_ok: category = "persistent_fail"
else:                             category = "stable_success"
```

`format_comparison_text` schreibt zuerst einen Zählkopf und rendert danach in
fester Reihenfolge, Regressionen zuerst:
`("regressed", "Regressions (right→wrong) — HIGHEST PRIORITY", True)`.

**Warum das fehlt:** ein Aggregatscore verschluckt Regressionen. Fünf neue
Treffer und drei neue Fehler ergeben netto plus zwei und sehen wie Fortschritt
aus. Skill Forge fährt bereits eine gepaarte A/B-Anlage (`SKILL.md:360-362`
spawnt pro Eval einen Mutations- und einen Baseline-Subagenten), hat die
Paarung aber nie ausgewertet.

**Übernahme:** in Markdown eine Tabelle mit vier Zeilen im Morning Report und
im Hypothesis-Context. Die Reihenfolge mit Regressionen zuerst ist die
eigentliche Anweisung: sie lenkt die knappe Aufmerksamkeit auf den
Schadensfall statt auf die Erfolgsmeldung.

---

### B9. Die Form einer gelernten Regel

**SkillOpt:** die trainierten Artefakte unter `ckpt/` zeigen ein durchgängiges
Muster. Jede gelernte Regel ist ein konditionaler Imperativ aus drei Teilen:
Auslöseklausel, Handlung, expliziter Negativteil, der den konkret beobachteten
Fehler benennt.

Aus `ckpt/searchqa/gpt5.5_skill.md`:

> For natural geographic features, preserve conventional feature designators
> such as "Lake," "River," "Bay," "Gorge," "Mount," or "Island" when they are
> part of the proper name or match the requested feature type. **Do not
> shorten** "Lake Okeechobee," "Tampa Bay," or "Olduvai Gorge" to an ambiguous
> base name merely to be concise.

Und: "Do not assume the document title itself is the answer."

Regeln nennen konkrete Oberflächen statt Abstraktionen. Die Auslöseklausel
macht eine Regel selbstprüfend. Der Negativteil konserviert den Fehlerfall,
der sie ausgelöst hat. Fehlerbenannte Abschnitte funktionieren mitten in der
Aufgabe als Abrufschlüssel ("stecke ich gerade in dieser Falle?"), was
themenbenannte Abschnitte nicht tun.

**Skill Forge schreibt Regeln, sagt aber nirgends, welche Form eine Regel
haben muss, damit sie greift.** Ohne diese Vorgabe produziert jeder
Optimierungslauf vage Ratschläge, die das Gate nicht bewegen.

**Übernahme:** in `agents/mutator.md` als Formvorschrift:

```
Jede neue Regel besteht aus drei Teilen:
1. Auslöseklausel: "Wenn <konkret beobachtbare Situation> ..."
2. Handlung: was zu tun ist, mit konkreten Oberflächen statt Abstraktionen
3. Negativteil: "Nicht <der konkrete Fehler, der in exp-NNN aufgetreten ist>"
Abschnitte werden nach dem Fehlerfall benannt, nicht nach dem Thema.
```

---

### B10. Komprimiere das Artefakt, nie die Evidenz

**SkillOpt:** `gradient/reflect.py` definiert `_clip_text(value, limit=None)`
mit dem Docstring:

> Truncation is disabled: the optimizer is given the full content so it can
> see exactly what the agent saw/did. `limit` is accepted for backward
> compatibility but ignored.

Der Rumpf ist `return str(value)`. Alle Renderpfade laufen darüber. Dasselbe
in `optimizer/clip.py`: die Beschreibungen des Edit-Pools gehen ungekürzt in
den Ranking-Prompt. Gekürzt wird ausschliesslich, was ins Log geht.

**Die naheliegende Sparmassnahme ist, lange Transcripts vor der Analyse
zusammenzufassen. SkillOpt hat die Längenbegrenzung bewusst ausgebaut.**
Gekürzte Transcripts erzeugen plausible, aber falsche Ursachenanalysen, und
aus einer falschen Ursache wird eine Regel, die das Gate nicht bewegt und
trotzdem Platz kostet.

**Übernahme:** die 30-Prozent-Context-Regel (`SKILL.md:305`) so präzisieren,
dass sie für History und Meta-Kontext gilt, nicht für die Transcripts des
aktuellen Experiments. Die stehen ungekürzt zur Verfügung.

---

### B11. Token-Budget mit Konsequenz

**SkillOpt:** die README nennt "typically 300–2,000 tokens" für das
deploybare `best_skill.md`. Die eigenen Artefakte liegen zwischen 1963 und
13335 Zeichen, sprengen die Zahl also selbst. Mechanischer Gegendruck kommt
aus zwei Richtungen: `delete` ist eine reguläre Edit-Op, und
`use_semantic_density` addiert optional `0.05 × Anteil der Tokens aus einer
Elf-Wort-Liste` (MUST, ALWAYS, NEVER, ONLY, CRITICAL, IMPORTANT, RESOLVE,
PREFER, ENSURE, STRICT, VERIFY).

**Skill Forge:** der einzige Gegendruck ist `agents/mutator.md:136` ("Ist die
SKILL.md noch unter 500 Zeilen?") ohne definierte Konsequenz. Der
Mutationstyp `prune` steht in der Taxonomie, aber nichts erzeugt Anlass, ihn
zu wählen, weil Wachstum nichts kostet.

**Übernahme, nur die Budget-Hälfte:**

1. `count_tokens(text)` und Subcommand `artifact-stats <path> [--budget N]`.
   **Divisor 3, nicht 4:** deutsche Komposita tokenisieren schlechter, mit
   `len(text) // 4` ist das Budget rund 30 Prozent zu grosszügig.
2. **Das Budget zählt SKILL.md plus alle vom Loop erzeugten Dateien unter
   `references/` und `scripts/`.** Sonst ist es über `reference_add`
   (`mutator.md:88`) in einer Runde umgangen, und zwar genau durch den
   Mutationstyp, den der Loop unter Budgetdruck naheliegenderweise wählt.
3. Wizard setzt `token_budget = max(2000, ceil(initial * 1.25))`.
4. `mutator.md` Sanity-Check Punkt 4: die 500-Zeilen-Frage durch
   `artifact-stats` ersetzen. Bei `budget_ok: false` schreibt der
   Orchestrator `forced_category: "efficiency"` und
   `forced_mutation_type: "prune"` in den Context der nächsten Runde.

**Den Dichte-Tiebreaker nicht übernehmen.** Die Elf-Wort-Liste ist englisch,
Skill Forges Artefakte sind deutsch. Die Heuristik würde dort nichts messen.
Nebenbei steht sie in Spannung zu `mutator.md:152` ("Keine MUSTs in ALL
CAPS"); wer sie je einführt, muss diese Zeile mitverhandeln.

---

### B12. Reward-Hacking im Generic-Modus strukturell verhindern

**Skill Forge heute:** `SKILL.md:366-371` akzeptiert jede Verbesserung, die
mit Exit-Code 0 zurückkommt. Die optimale Mutation für
`flake8 src/ | wc -l` ist, `src/` zu löschen. Für Jest-Coverage: die
ungedeckten Tests löschen oder `coverageThreshold` senken. Für Bundle-Size:
Features entfernen.

Verstärkt durch einen zweiten Defekt: bei `flake8 src/ | wc -l` ist der
Exit-Code der Pipeline immer der von `wc`. Die Prüfung "Exit-Code 0" fängt
also selbst dann nichts ab, wenn das Messziel gelöscht wurde.

Ein Grep über `SKILL.md`, `agents/` und `references/` findet null Treffer für
`protected`, `invariant`, `forbidden`, `node_modules`, `git`. Das Wort
Versionskontrolle kommt im gesamten Skill nicht vor, obwohl der Loop
stundenlang unbeaufsichtigt mit `cp`-basierten Snapshots gegen Live-Dateien
läuft.

**SkillOpt-Sleep:** `adapters/superpowers.py:633` vergleicht sha256-Hashes
geschützter Dateien, und `harness_test_passes` wird nur berechnet, wenn
`protected_unchanged` wahr ist. Der Kommentar dort: "Never execute a test file
after detecting that the evaluated agent changed it."

**Übernahme:**

1. `snapshot_scope(scope_glob, protected_paths) -> dict` liefert
   `{"protected": {relpath: sha256}, "scope": {"file_count": n,
   "total_bytes": n}}`.
2. `check_invariants(before, after, invariant_command=None,
   min_scope_ratio=0.9) -> dict`.
3. **Durchsetzung im Pflichtpfad, nicht als optionaler Aufruf.** Der
   `metric`-Subcommand bekommt `--before <json>` und `--invariant-command`;
   ohne bestandene Invarianten gibt er `{"decision": "INVALID"}` statt eines
   Werts. `tsv-append` verweigert eine Zeile mit `decision=KEEP` ohne
   Invarianten-Nachweis. Der Prompt kann den Check dann nicht überspringen,
   weil er sonst keine Zahl bekommt.
4. `protected_paths` richtig definieren: geschützt sind Metrik- und
   Test-Konfiguration, nicht die im `metric_command` genannten Verzeichnisse.
   Wizard-Vorschlagsliste: `.flake8`, `setup.cfg`, `pyproject.toml`,
   `tox.ini`, `jest.config.*`, `package.json`, `tsconfig.json`, `.eslintrc*`,
   `lighthouserc*`, `Dockerfile`, plus alles unter `tests/`, `__tests__/`,
   `spec/`. Harte Regel: `protected_paths` und Scope-Glob dürfen sich nicht
   überschneiden.
5. `max_scope_files: 200`, Ausschluss von `node_modules`, `.git`, `dist`,
   `build`, `.next`. Warnung, wenn das Ziel nicht unter Versionskontrolle
   steht.
6. **INVALID ist nicht kostenlos:** `update_coverage_matrix` kennt nur KEEP,
   REVERT und NEUTRAL. Ein INVALID erhöht nur `experiments_total` und
   verzerrt die Sättigungslogik. Braucht ein Feld `experiments_invalid` plus
   Ausschluss aus der Sättigungszählung, und `best_delta` darf nicht mit
   INVALID-Deltas gefüttert werden.

---

### B13. Meta-Memory über Edit-Qualität

**SkillOpt:** `optimizer/meta_skill.py` erzeugt optimizer-seitiges Gedächtnis,
das **nie ins Skill-Dokument geschrieben wird**. `prompts/meta_skill.md`
grenzt scharf ab:

> Address the FUTURE OPTIMIZER directly, not the target.
> Do not output target-facing task instructions.

Der Trainer lädt die Datei der **vorigen** Epoche und fädelt sie in vier
Stages ein (reflect, merge_patches, rank_and_select,
decide_autonomous_learning_rate). `format_meta_skill_context` trägt die
Vorrangregel:

> Prefer it when the current evidence is ambiguous, but do not force it if the
> current trajectories clearly contradict it.

**Skill Forge:** `group_history_by_category` liefert total, keeps, reverts,
best_delta plus 80 Zeichen Hypothesentext. Das beantwortet, *wo* gesucht
werden soll, nicht *wie* für diesen konkreten Skill eine gute Änderung
aussieht. Nichts bewertet je, ob eine frühere Leitlinie geholfen hat.

Das stärkste Argument liefert die eigene Compaction. Sie reduziert ab dem
sechsten Experiment auf Kernfelder. Seit Block 1 überleben `mutation_type` und
`near_miss`, und die Volldatensätze liegen im Archiv, aber der Hypothesis-Agent
bekommt das Archiv nicht in den Prompt. Eine destillierte Notizdatei rettet
genau das Signal, das sonst nur noch auf der Platte liegt.

**Übernahme:**

1. `editing-notes.md` im Workspace, nie in der Ziel-SKILL.md, maximal acht
   Bullets, alle fünf Experimente komplett neu geschrieben.
2. **Belegpflicht:** jeder Bullet nennt mindestens eine Experiment-ID, aus der
   er stammt. Bullets ohne ID werden gestrichen, nicht überarbeitet.
3. **Verdikt-Pflicht:** pro Bullet der Vorfassung behalten / überarbeiten /
   streichen. Ohne das wachsen solche Notizen nur.
4. Trigger mit Mindest-Evidenz: alle fünf Experimente, aber nur wenn
   mindestens drei eine Entscheidung KEEP oder REVERT tragen. Reine
   NEUTRAL-Serien liefern kein Material.
5. **Sperre:** die Notizen dürfen keine Kategorie ganz ausschliessen. Sie
   beeinflussen, *wie* eine Mutation formuliert wird, nicht *ob* eine
   Kategorie noch angefasst wird. Sonst kollabiert die Exploration und die
   Coverage-Matrix wird wirkungslos.
6. **Reihenfolge:** der Meta-Schritt muss vor der History-Compaction laufen
   oder direkt auf `experiments/exp-NNN/mutation.json` zugreifen, weil
   `mutation_type` sonst schon weg ist. Und er muss vor dem Checkpoint-Save
   stehen, sonst findet ein Resume die Datei ohne passenden Stand.

---

### B14. Schema-Validierung vor der Anwendung

**SkillOpt:** `docs/guide/local-env-smoke.md`, Abschnitt "Validate optimizer
JSON before returning it", listet die Prüfungen einzeln auf.

Für Edit-Payloads: Antwort ist ein JSON-Objekt, `edits` ist eine nicht leere
Liste, jeder Edit ist ein Objekt, jeder Edit hat eine erlaubte Operation, die
für diese Operation geforderten Felder sind vorhanden.

Für Ranking-Payloads: `selected_indices` existiert, Indizes sind Ganzzahlen,
sind eindeutig, liegen im Bereich der Kandidaten, überschreiten das
Edit-Budget nicht.

Danach: "On failure, retry with a compact prompt that includes the schema
error." Und **benannte** Rückfallpfade statt stiller Defaults.

**Warum das fehlt:** genau hier sterben solche Schleifen leise. Ein Modell
liefert leere oder falsch benannte Felder, der Code fällt in einen unbenannten
Default, und der Lauf meldet Erfolg ohne Wirkung. `agents/orchestrator.md:55-60`
hat den Retry-Gedanken, aber keine Prüfliste.

**Übernahme:** die Prüfliste wörtlich in `agents/orchestrator.md`, plus die
Regel, dass jeder Rückfallpfad einen Namen und einen Reasoning-String
bekommt.

---

### B15. Harvesting echter Sessions (optional, mit Redaction)

**SkillOpt-Sleep:** `harvest(transcripts_dir, ...)` läuft mit `os.walk` über
`~/.claude/projects`, überspringt Verzeichnisse namens `subagents` und Dateien
mit Präfix `agent-`, nimmt nur `*.jsonl`, sortiert nach mtime absteigend.
`digest_transcript` liest `type`, `timestamp`, `cwd`, `gitBranch`,
`message{role, content}`. Drei Filter werfen Rauschen weg. Die
Outcome-Inferenz (success / fail / mixed / unknown) sitzt in `mine.py:149-172`.
`llm_miner.py:118` zählt `n_dropped_uncheckable`, also Kandidaten ohne
prüfbares Erfolgskriterium.

**Skill Forge:** erfindet die Evals. `SKILL.md:139-141`: "Falls nicht:
Erstelle 3-5 realistische Testfälle mit messbaren Assertions", geschrieben vom
selben Modell in derselben Session, die anschliessend die Mutationen schreibt.
Der Loop optimiert gegen seine eigene Vorstellung davon, was schwer ist. Ein
Skill, der bei echten Anfragen scheitert, kann trotzdem 100 Prozent erreichen.

**Der teuerste Fallstrick beim Portieren:** SkillOpts `_is_meta_prompt`
verwirft Prompts, die mit `/` beginnen und höchstens drei Wörter haben, sowie
alles mit `<command-message>` oder `<command-name>` in den ersten 200 Zeichen
und alles mit Präfix `# /`. **Genau so sieht in Claude Code eine
Skill-Invocation aus.** Wer die Funktion unverändert übernimmt, filtert präzise
die Sessions weg, für die Skill Forge harvesten will.

Konsequenz: die Skill-Erkennung muss **vor** dem Filter laufen, und der
eigentliche Task-Intent kommt aus dem *nächsten* substanziellen User-Turn,
nicht aus `user_prompts[0]`.

**Übernahme, falls überhaupt:**

1. `scripts/harvest.py` mit `--skill <name>` als positivem Filter: Sessions,
   in denen der Ziel-Skill tatsächlich lief.
2. **Redaction-Pass als Pflichtbestandteil**, nicht als Nachtrag im
   Risiko-Feld: Maskierung für `sk-[A-Za-z0-9]{20,}`, `gh[pousr]_`,
   `AKIA[0-9A-Z]{16}`, `-----BEGIN .* PRIVATE KEY-----`, `Bearer <token>`,
   `password=`, `api_key=`, E-Mail-Adressen. Excerpts auf 400 Zeichen kappen.
3. Review als Wizard-Interaktion, nicht als JSON-Flag. Ein `reviewed: true`
   in einer Datei, die derselbe Agent schreibt, der sie prüft, ist keine
   Kontrolle. Guided-Checkpoint 1 zeigt die Kandidaten mit Outcome-Label und
   redigiertem Excerpt, der User wählt einzeln aus.
4. Opt-in, Default aus.
5. Volumen beachten: `~/.claude/projects` wächst auf mehrere tausend
   jsonl-Dateien, der Grossteil davon Subagent-Transkripte mit `agent-`-Präfix.
   Ohne `limit` und `since_hours` parst der Walk jede Datei komplett.

**Diese Empfehlung ist die einzige mit relevantem Datenschutz-Profil. Ohne
Redaction-Pass nicht ausliefern.**

---

### B16. Testsuite und deterministische Fixtures

**Skill Forge:** null Tests, kein `tests/`, keine CI, keine
pytest-Konfiguration für 818 Zeilen, die jede Keep/Revert-Entscheidung tragen.
Vier Bugs wurden durch blosses Ausführen gefunden (siehe Teil A).

**Was von SkillOpts `MockBackend` nicht übertragbar ist:** dort ist der Loop
selbst Python, der Mock ersetzt nur den Modellaufruf. Skill Forge hat keinen
Python-Treiber; Hypothese, Mutation und Entscheidung stehen als Prosa in
`SKILL.md`, der Eval-Run spawnt Subagents. Ein `mock_eval.py` mit Regeltexten
hätte nichts, in das es sich einklinken könnte.

**Übertragbar ist die Disziplin:**

1. `tests/` plus `conftest.py` im Repo-Root (nicht in `tests/`, sonst löst
   `from scripts.composite_score import ...` nicht auf). Kein
   `tests/__init__.py`. pytest ist auf dem System-Python 3.9.6 vorhanden.
2. Die vier Bugs zuerst als rote Tests pinnen, dann fixen:
   - leeres Verzeichnis liefert None oder wirft, nicht 0.20
   - fehlende `timing.json` heisst "keine Daten", nicht Effizienz 1.0
   - `saturated` wird bei jedem Update neu berechnet
   - `direction` wird bis in `update_coverage_matrix` und `tsv-append`
     durchgereicht
3. `decide` als Funktion (siehe A1) ist Voraussetzung: ohne sie hat
   `tests/test_decide.py` nichts zu importieren.
4. NICHT UMGESETZT, bewusst verworfen. Die Tests bauen ihre Fixtures inline
   (`_experiment` in `tests/test_scoring.py`), ein eigener Subcommand wäre
   Verdopplung. Ursprünglich vorgeschlagen: Subcommand `mock-experiment`, das einen synthetischen
   Experiment-Baum schreibt (`runs/eval-N/with_mutation/` und `/baseline/` mit
   `grading.json` und `timing.json`). Damit sind Scoring, Coverage,
   Kompaktierung und Checkpointing end-to-end testbar, ohne einen einzigen
   API-Call.
5. Python 3.9 beachten: `X | Y` darf zur Laufzeit nicht auftauchen
   (`from __future__ import annotations` deckt nur Annotationen ab).

---

### B17. Gewinner-Artefakte statt Prozentzahlen

**SkillOpt:** legt unter `ckpt/` sechs trainierte Skills ab, je eine
Markdown-Datei pro Benchmark. `ckpt/README.md` erklärt die Eigenheiten offen,
inklusive der geschützten SLOW_UPDATE-Sektion am Ende ("that's expected, not a
formatting issue") und der Konfiguration, unter der sie entstanden sind
(`slow_update_gate_with_selection: true`, während main inzwischen auf `false`
steht, weshalb Nachtrainieren abweichen kann).

Die Eval-Splits liegen als ID-Manifeste bei, wenige KB statt der Daten selbst.

`docs/sleep/RESULTS.md` zeigt eine Sensitivitätstabelle: vier Varianten, die
alle gegen die empfohlene Rezeptur verlieren (−3.1, −2.4, −9.2, −2.4 gegen
+11.9 Baseline), mit dem Satz "Every tested direction away from that baseline
reduced the measured gain".

**Skill Forge:** `README.md:264-280` behauptet drei Ergebnisse. Im Repo liegt
dazu nichts: kein `evals.json`, kein `history.json`, kein
`experiment-log.tsv`, keine `coverage-matrix.json`, kein Snapshot, kein
`grading.json`. Die einzige Spur ist `examples/fachbuch-lektorat-session.md`,
eine handgeschriebene Erzählung mit dem Entscheidungswert "NEUTRAL-KEEP", den
keine Spezifikation kennt. Unter der Kaskade seit Block 1 wäre das Ergebnis
NEUTRAL, also ebenfalls ein Rückrollen; NEAR_MISS ist kein Ausgang mehr,
sondern ein Flag. Die Tabelle mischt zwei Metriken: 0.74 → 0.90 ist ein
Composite, 87 → 100 eine Assertion-Pass-Rate.

**Übernahme, in zwei Teilen:**

**Teil A, sofort (Korrekturen):**
- Kaskade entscheiden (A1), dann `README.md:102-108` auf das Ergebnis ziehen.
- `README.md:203` auf die neun tatsächlichen TSV-Spalten korrigieren.
- `README.md:176-196` um `checkpoint.json` ergänzen, `README.md:155-158` um
  `agents/orchestrator.md` und `templates/agent_context.md`, `README.md:71`
  auf vier Agenten präzisieren.
- Versionsstand auf v3 in `README.md`, `RELEASE_NOTES.md`, `index.html`,
  `index_de.html`, `index_en.html`. Zusätzlich `version: 3.0.0` ins
  SKILL.md-Frontmatter und `__version__` ins Script, damit die Semantik am
  Artefakt hängt statt in Prosa.
- `examples/fachbuch-lektorat-session.md` kopfseitig kennzeichnen: Lauf vor
  v3, Entscheidungsregeln abweichend. Nicht umschreiben.

**Teil B, nach dem ersten echten Lauf:**
- `ckpt/<skill-name>/` mit finaler SKILL.md, vollständiger `history.json`,
  `evals.json` mit Split-Zuordnung. Ohne diese drei Dateien darf ein Skill
  nicht in der Ergebnistabelle stehen.
- `ckpt/README.md` mit Grössenbereich, verwendeter Konfiguration und
  gemessener Auflösungsgrenze.
- Ergebnisse in der Haupt-README nur noch mit Metrikname, Anzahl Evals,
  Anzahl Experimente und Auflösungsgrenze.

---

## Teil C: Was nicht übernommen werden sollte

| SkillOpt-Mechanismus | Warum nicht |
|---|---|
| `edit_budget: 4` | Skill Forges "eine Änderung pro Experiment" ist strenger und sichert die Attribution. Rückschritt. |
| Semantic Density | Elf englische Wörter, deutsche Artefakte. Misst hier nichts. Steht ausserdem gegen `mutator.md:152`. |
| SessionEnd-Hook | Hat bei SkillOpt selbst keinen Konsumenten: `session-end.log` wird geschrieben und von keiner Zeile gelesen. `plugins/cursor/.../SKILL.md:14` sagt explizit "This plugin has no session-end hook", und `tests/test_plugin_sync.py:103` erzwingt die Aussage. Skill Forge erntet keine Sessions, ein Log hätte nicht mal einen theoretischen Leser. |
| `allowed-tools: Bash, Read` | Bei SkillOpt sicher, weil das Python-Paket schreibt und der Agent nur startet. Bei Skill Forge **ist der Agent die Engine**: der Mutator editiert SKILL.md direkt. Ein Command ohne Write, Edit und Task kann ausser `status` nichts ausführen. |
| `print-cron.sh` | Skill Forge hat keinen Runner. `composite_score.py` ist eine Scoring-Bibliothek, kein Loop-Entrypoint. Ein Cron-Eintrag auf ein nicht existierendes Binary ist schlechter als das jetzige Prompt-Template. `references/scheduled_task_template.md` ist die plattformeigene Scheduled-Task-API, kein Pseudo-Python. |
| `deferred.jsonl` | Aufgehobene Kandidaten wurden gegen eine SKILL.md formuliert, die nach einem KEEP nicht mehr existiert. SkillOpt trägt bewusst nichts über den Schritt hinweg. |
| `mock_eval.py` mit Regeltexten | Setzt einen Python-Treiber voraus, den Skill Forge nicht hat. Ersetzt durch Inline-Fixtures in der Testsuite. |
| Selection-Cache über `skill_hash` | Lohnt erst, wenn ein Bewertungslauf teuer genug ist. |

Aus dem Plugin-Komplex bleiben drei Dinge übrig, die sich lohnen:

1. **`workspace_path` in `config.json`**, absolut, nie mit `~`, gesetzt beim
   Anlegen des Workspace. `templates/morning_report.md:54` und `:66`
   interpolieren den Pfad bereits. Ein Scheduled Task startet mit unbekanntem
   cwd. Dazu `target_path` und `created_at`.
2. **Status als harmlose Default-Aktion.** Nicht als Claude-Code-Command,
   sondern als Regel in `SKILL.md`: "Wenn der User skill-forge ohne klare
   Aktion nennt und ein Workspace mit `config.json` existiert, zeige zuerst
   den Status und starte keinen Loop." Das ist die tatsächlich wertvolle Idee
   hinter SkillOpts `(default: status)`.
3. **Cron-Zeit 3:17 statt einer runden Stunde**, damit nicht alle
   Installationen gleichzeitig auf dieselbe API gehen.

---

## Teil D: Reihenfolge

**Block 1, Reparatur (ohne diesen Block ist alles Weitere Kosmetik):**

1. `decide()` als Funktion, NEUTRAL reparieren, README angleichen (A1)
2. `snapshot()` / `revert()` als Code, Checkpoint-Felder (A2)
3. `side`-Parameter im Scoring (A3)
4. Efficiency raus aus dem Gate (A4)
5. `tests/` mit den vier gepinnten Bugs (B16)
6. Doku-Widersprüche (B17 Teil A)

**Block 2, Messqualität:**

7. Auflösungsgrenze aus der Assertion-Zahl (B1)
8. Dreiwege-Split mit Hash-Zuordnung, `evals.json`-Schema (B4)
9. Diff und NO_OP-Bucket (B7)
10. Längsvergleich improved/regressed/persistent_fail/stable_success (B8)

**Block 3, Analysequalität:**

11. DEFECT gegen LAPSE, geschützte Regionen (B2)
12. Erfolgsanalyse als Schutzliste (B3)
13. Rejected-Buffer im Wortlaut (B5)
14. Drei Kandidaten plus Ranking-Rubrik (B6)
15. Regelform mit Auslöseklausel und Negativteil (B9)
16. Schema-Validierung im Orchestrator (B14)

**Block 4, Reifegrad:**

17. Token-Budget mit Konsequenz (B11)
18. Reward-Hacking-Schutz im Generic-Modus (B12)
19. Meta-Memory `editing-notes.md` (B13)
20. Evidenz nie kürzen (B10)
21. `ckpt/` nach dem ersten echten Lauf (B17 Teil B)

**Optional, separat zu entscheiden:**

22. Harvesting mit Redaction (B15)

Block 1 und 2 zusammen liegen deutlich unter tausend Zeilen Python plus
Prompt-Änderungen. Danach trifft der Loop Entscheidungen, die bedeuten, was
sie behaupten.
