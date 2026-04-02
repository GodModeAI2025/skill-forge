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
