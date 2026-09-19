# Skill Forge: Morning Report

> Generiert: {timestamp}
> Modus: {mode}
> Target: {target_name}
> Dauer: {total_duration}

## Zusammenfassung

| Metrik | Start (v0) | Ende (v{final}) | Delta |
|--------|-----------|-----------------|-------|
| {metric_name} | {start_score} | {end_score} | {delta_score} |
| Experimente | {total_experiments} | Crashes: {crashes} | Zeit: {total_duration} |

**Entscheidungen:** KEEP {keeps} · REVERT {reverts} · NEUTRAL {neutrals} (davon
near_miss: {near_misses}) · INVALID/SKIP/NO_OP {invalids} · DEFERRED {deferred}

NEUTRAL heisst zurückgerollt, wie REVERT. Der Unterschied ist die Begründung: bei
REVERT hat die Mutation messbar geschadet, bei NEUTRAL war nichts messbar.
`near_miss` markiert die NEUTRAL-Fälle knapp unterhalb der Keep-Schwelle, also die
Kandidaten für eine Variation.

`DEFERRED` heisst: der Loop hat eine Wissenslücke erkannt und keine Quelle
gefunden, die sie schliesst. Es gab keine Mutation und keine Messung, sondern
eine Frage. Sie steht weiter unten unter "Offene Wissensfragen".

**Gate-Gewichtung:** {gate_weights}

Der Gate-Score ist `assertion_pass_rate × W_a + llm_judge × W_j`. Ohne Comparator
W_a = 1.00, mit Comparator W_a = 0.65 und W_j = 0.35. Effizienz geht nicht ein,
sie steht unten als eigene Grösse.

## Score-Verlauf

```
Score
1.0 ┤
0.9 ┤
0.8 ┤  {chart_placeholder}
0.7 ┤
0.6 ┤
0.5 ┤
    └──────────────────────
     v0  v1  v2  v3  ...
```

## Top-Verbesserungen

{top_improvements}

## Fehlgeschlagene Hypothesen

{failed_hypotheses}

## Coverage-Matrix

| Kategorie | Experimente | KEEP | REVERT | NEUTRAL | INVALID | Best Delta | Status |
|-----------|------------|------|--------|---------|---------|------------|--------|
{coverage_rows}

**Coverage:** {coverage_percent}% ({touched}/{total} Kategorien berührt, {saturated} saturiert)

**Unberührte Bereiche:** {untouched_categories}

INVALID fasst INVALID, SKIP, NO_OP und DEFERRED zusammen und zählt nicht in die
Sättigung. Eine Kategorie mit drei INVALID-Läufen ist unberührt, nicht
abgegrast. Für `knowledge` gilt das besonders: drei unbeantwortete Fragen
heissen, dass noch nichts versucht wurde, nicht dass nichts zu holen ist.

## Offene Wissensfragen

{knowledge_gaps_block}

**Das ist der Teil des Reports mit dem besten Verhältnis aus Aufwand und
Wirkung.** Jede Frage hier ist ein Fehler, den keine Umformulierung behebt: dem
Skill fehlt eine Tatsache. Der Loop hat sie nicht erfunden, sondern stehen
lassen und belegt, woran er sie gemerkt hat. Beantworten kostet pro Frage
typischerweise unter einer Minute; jede Antwort steht dem nächsten Lauf zur
Verfügung.

Antworten oder verwerfen:

```bash
python3 scripts/knowledge.py gap-resolve {workspace_path}/knowledge-gaps.jsonl \
  gap-003 --status answered --resolved-by "<Quelle oder Person>" --note "<Antwort>"

python3 scripts/knowledge.py gap-resolve {workspace_path}/knowledge-gaps.jsonl \
  gap-004 --status rejected --note "betrifft uns nicht"
```

Eine verworfene Frage wird nie erneut gestellt. Eine beantwortete auch nicht:
taucht ihr Fehlermuster wieder auf, behandelt der nächste Lauf es als
Verweis-Problem, nicht als Wissenslücke.

Stand: {gap_open} offen · {gap_answered} beantwortet · {gap_rejected} verworfen
(`knowledge.py gap-stats {workspace_path}/knowledge-gaps.jsonl`)

## Effizienz

Effizienz entscheidet nichts. Sie steht hier, weil Token- und Laufzeitkosten
interessant sind, nicht weil sie in den Gate-Score einfliessen. Sie tat es bis v2,
und weil sie zwischen zwei Läufen mit identischen Assertions um 0.045 schwankte,
bei einer Keep-Schwelle von 0.02, hat sie dort Entscheidungen produziert, die mit
Qualität nichts zu tun hatten.

| Kategorie | Tokens gesamt | Dauer gesamt | efficiency_score |
|-----------|--------------|--------------|------------------|
{efficiency_rows}

Steht `efficiency_score` auf `keine Timing-Daten`, wurde keine timing.json
gefunden. Das ist ausdrücklich nicht dasselbe wie perfekte Effizienz.

## Längsvergleich (letztes Experiment)

Dieselben Evals unter beiden Versionen, Regressionen zuerst.

| Kategorie | Anzahl |
|---|---|
| Regressionen (richtig zu falsch) | {regressed} |
| Weiterhin falsch | {persistent_fail} |
| Neu gelöst | {improved} |
| Weiterhin richtig | {stable_success} |
| **netto** | **{net}** |

{regression_list}

Ein positives Netto ist kein Freibrief: fünf neue Treffer gegen drei neue
Fehler ergeben netto plus zwei und sehen wie Fortschritt aus.

## Messbarkeit

Auflösungsgrenze: {resolution} bei {total_assertions} Assertions im val-Split.
Änderungen unterhalb dieses Werts waren in diesem Lauf nicht messbar.
Bindende Schwelle in der letzten Entscheidung: {binding_threshold}

## Test-Split

| | Score |
|---|---|
| Baseline vor Experiment 1 | {test_baseline} |
| Endversion | {test_final} |

Dieser Split wurde in keinem Experiment gesehen. Gibt es keinen test-Split
(unter 12 Evals), gehört genau das hier hin statt einer leeren Tabelle.

## Snapshots

Bester gemessener Score: {best_score} (aus Experiment {best_experiment})
Letzter Snapshot: `{on_disk_version}`

Ein Snapshot `pre-exp-007` ist der Zustand VOR Experiment 7.

**Wo der beste Stand liegt:** Endete der Lauf mit einem KEEP, steht der beste Stand
am Zielpfad selbst, denn er wurde noch von keinem Snapshot erfasst. Kam danach
mindestens ein weiteres Experiment, liegt er in `pre-exp-(N+1)`, wobei N das
Experiment mit dem besten Score ist.

Zurückrollen auf einen bestimmten Stand:

```bash
python3 scripts/composite_score.py revert \
  --snapshot-dir {workspace_path}/snapshots --version pre-exp-<NNN>
```

## TSV-Log (letzte 5 Einträge)

```
{tsv_tail}
```

Spalten: timestamp, experiment, hypothesis_summary, metric_before, metric_after,
delta, decision, category, duration_s.

Vollständiges Log: `{workspace_path}/experiment-log.tsv`
Archivierte Volldatensätze: `{workspace_path}/history.archive.jsonl`

## Verbleibende Schwachstellen

{remaining_weaknesses}

## Empfehlungen

{recommendations}

---

*Generiert vom Skill Forge Loop. Experiment-Logs unter: {workspace_path}/experiments/*
