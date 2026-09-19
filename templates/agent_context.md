# Dynamic Agent Context

> Dieses Template wird zur Laufzeit mit aktuellen Experiment-Daten gefüllt
> und den Agent-Prompts als Kontext-Ergänzung injiziert.

## Aktueller Stand

- **Experiment-Runde**: {current_round} von {max_experiments}
- **Phase**: {phase} (Exploration / Balanced / Exploitation)
- **Aktueller Baseline-Score**: {baseline_score}
- **Bester Score bisher**: {best_score}
- **Trend**: {trend} (steigend / stagnierend / fallend)

## Letzte 3 Experimente

{recent_experiments}

## Coverage-Überblick

| Kategorie | Versuche | Erfolge | Best Delta | Status |
|-----------|----------|---------|------------|--------|
{coverage_rows}

**Unberührt**: {untouched_categories}
**Saturiert**: {saturated_categories}

## Near-Miss Hypothesen

{near_miss_info}

## Empfehlung für diese Runde

{phase_guidance}

## Bereits verworfen

{rejected_block}

Gerendert mit `rejected-format <workspace>/rejected.jsonl --limit 10`. Enthält
alle Nicht-KEEP-Entscheidungen im Wortlaut, Near-Misses als markierte
Teilmenge.

## Wissensbestand

{knowledge_index_block}

Der Inhalt von `<ziel-skill>/knowledge/INDEX.md`. Steht ein Thema hier, liegt
die Tatsache im Bestand: dann fehlt nicht das Wissen, sondern der Weg dorthin,
und das ist ein `SKILL_DEFECT`, keine Wissenslücke.

## Bestandsnutzung im letzten Experiment

{knowledge_usage_block}

Gerendert mit `knowledge.py usage-format <workspace>/knowledge-usage.json`.

## Offene Wissensfragen

{knowledge_gaps_block}

Gerendert mit `knowledge.py gap-format <workspace>/knowledge-gaps.jsonl --limit 10`.
Diese Lücken sind bereits gemeldet. Keine davon erneut stellen. Steht eine Frage
auf `answered` oder `sourced` und das Fehlermuster tritt trotzdem wieder auf,
fehlt nicht das Wissen, sondern der Verweis darauf — das ist ein `SKILL_DEFECT`.

## Bestätigte Muster

{success_patterns}

Aus der Erfolgsanalyse der letzten drei Experimente. Der Mutator prüft `prune`
und `structure_change` dagegen.
