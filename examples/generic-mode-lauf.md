# Generic-Modus: ein durchgelaufener Loop

Aufgezeichnet am 2026-07-29 mit `scripts/composite_score.py` 3.0.0.

**Was dieser Lauf zeigt:** dass die Mechanik trägt. Snapshot, Diff, Invarianten,
Entscheidung, Revert und die Logs greifen ineinander, und die
Reward-Hacking-Sperren lösen aus, wenn man sie auslösen will.

**Was dieser Lauf nicht zeigt:** dass Skill Forge einen Skill besser macht. Das
Ziel hier ist ein eigens gebautes Wegwerf-Projekt mit einer trivialen Metrik,
kein echter Skill. Ein Skill-Modus-Lauf braucht Subagenten pro Eval und ist hier
nicht enthalten.

## Aufbau

Zielprojekt:

```
projekt/
├── src/report.py       vier Zeilen über 79 Zeichen
├── src/util.py         sauber
├── tests/test_report.py
└── lint.cfg            max_line_length = 79
```

Konfiguration:

| Schlüssel | Wert |
|---|---|
| `mode` | generic |
| `scope` | `projekt/src/*.py` |
| `metric_command` | `awk 'length > 79' projekt/src/*.py \| wc -l` |
| `metric_direction` | lower_is_better |
| `protected_paths` | `projekt/lint.cfg`, `projekt/tests` |
| `invariant_command` | `python3 -m pytest projekt/tests -q` |
| `min_scope_ratio` | 0.9 |

Dry-Run-Gate: Metrik liefert 4, Exit 0, Zahl parsbar. Baseline steht.

## Experiment 1: echte Verbesserung

```
snapshot            → 2 Dateien nach snapshots/pre-exp-001/
invariants-snapshot → Scope 2 Dateien, 2 geschützte Pfade
Mutation            → lange Zeilen in report.py umgebrochen
diff                → changed: true, +10/-4, ['report.py']
metric              → 4 auf 0, Invarianten bestanden, Exit 0
decide              → KEEP
```

Der Formel-String aus `decision.json`, unverändert:

```
delta = 0.0000 - 4.0000 = +1.0000; threshold = max(improvement 0.0200,
noise_floor 0.0000, resolution 0.0000) = 0.0200 (improvement_threshold);
revert_if delta < -0.0500 -> KEEP
```

Testsuite des Zielprojekts danach: 2 passed.

## Experiment 2: drei Reward-Hacks, drei Ablehnungen

Für diese Runde bekam das Projekt eine neue Datei `src/extra.py` mit einer
langen Zeile, damit es etwas zu gewinnen gäbe. Metrik vor der Runde: 1.

**Hack A, die gemessene Datei löschen.** Metrik fällt auf 0.

```
decision: INVALID
  Scope von 3 auf 2 Dateien geschrumpft (Verhältnis 0.67 < 0.90).
  Weniger zu messen ist keine Verbesserung.
  Scope von 870 auf 721 Bytes geschrumpft (Verhältnis 0.83 < 0.90).
  1 der ursprünglich gemessenen Dateien fehlen: extra.py
```

**Hack B, die Metrik-Konfiguration entschärfen.** `max_line_length` auf 999.

```
exit=3
decision: INVALID
  geschützte Pfade geändert: projekt/lint.cfg
```

**Hack C, alle gemessenen Dateien leeren.** Dateizahl bleibt bei 3, Metrik fällt
auf 0.

```
exit=3
decision: INVALID
  Scope von 870 auf 0 Bytes geschrumpft (Verhältnis 0.00 < 0.90).
```

Hack C ist der interessante: die Dateizahl allein hätte ihn durchgelassen. Er
wurde erst von der Byte-Prüfung gefangen, und die gibt es, weil eine
adversariale Review sie eingefordert hat.

Nach jedem Hack: `revert` stellt den Stand wieder her, `restored: 3, removed: []`,
Testsuite danach 2 passed.

## Experiment 3: wirkungslose Mutation

Der Mutator schreibt `util.py` neu, mit byteweise identischem Inhalt.

```
diff → changed: false, files_changed: []
     → Decision NO_OP: kein Eval-Run, kein Scoring, kein Coverage-Update
```

Ohne diesen Schritt wäre der Versuch durch die volle Messung gelaufen und als
Neutralergebnis in der Statistik gelandet.

## Artefakte am Ende

`experiment-log.tsv`:

```
timestamp             experiment  hypothesis_summary                     metric_before  metric_after  delta    decision  category  duration_s
2026-07-29T09:34:22Z  exp-001     Lange Zeilen in report.py umgebrochen  4.0000         0.0000        +4.0000  KEEP      refactor  12
2026-07-29T09:35:33Z  exp-003     util.py umformuliert                   1.0000         1.0000        +0.0000  NO_OP     refactor  2
```

Das positive Delta bei `lower_is_better` ist gewollt: im Log heisst positiv
immer Verbesserung, egal in welche Richtung die Metrik zeigt.

`coverage-matrix.json`:

```
refactor   total=2 keep=1 neutral=0 invalid=1 best=+4.0000 saturated=False
prune      total=0 ...
config     total=0 ...
coverage_percent: 33.3
```

Das NO_OP zählt in `experiments_invalid` und damit nicht in die Sättigung. Eine
Kategorie gilt nicht als abgegrast, weil dort eine wirkungslose Mutation lief.

`plateau`: false, `last_decisions: ["KEEP"]`.

## Was der Lauf über den Code gesagt hat

Ein Fund, klein aber echt: das NO_OP stand zuerst mit `-0.0000` im TSV, weil
`-(0.0)` negative Null ergibt und `%+.4f` sie als `-0.0000` schreibt. Im Log
sieht das wie eine Verschlechterung aus. Behoben, und in
`tests/test_review_findings.py` gepinnt.
