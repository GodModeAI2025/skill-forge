# Scheduled Task Template für Skill Forge

## Task-Prompt (Template)

Ersetze die `{placeholder}` mit den konkreten Werten.

```
Lies den Skill 'skill-forge' und führe den autonomen Verbesserungsloop durch.

## Konfiguration
- Workspace: {workspace_path}
- Config: {workspace_path}/config.json

## Anweisungen
1. Lies die SKILL.md des skill-forge Skills
2. Lies die config.json im Workspace für Modus, Scope, Metrik und alle Parameter
3. Prüfe ob {workspace_path}/checkpoint.json existiert
   - Falls ja: Lies ihn mit `python3 scripts/composite_score.py checkpoint-info {workspace_path}`.
     Ist `applied_but_undecided` gesetzt, rolle ZUERST auf `on_disk_version` zurück:
     `python3 scripts/composite_score.py revert --snapshot-dir {workspace_path}/snapshots --version <on_disk_version>`
     Erst danach weiterlaufen. Sonst misst der Lauf gegen eine bereits mutierte
     Datei, die er für die Baseline hält.
   - Falls nein, aber history.json existiert: Setze beim letzten Stand dort fort
   - Falls keins von beidem: Starte mit Schritt 0, Dry-Run-Validierung wiederholen
4. Führe den Loop aus (Schritt 1-6) bis ein Abbruchkriterium greift
5. Generiere den Morning Report als {workspace_path}/morning-report.md
6. Wo die beste Version liegt: Endete der Lauf mit einem KEEP, am Zielpfad selbst,
   denn dieser Stand wurde von keinem Snapshot mehr erfasst. Andernfalls in
   {workspace_path}/snapshots/pre-exp-<N+1>/files/, wobei N das Experiment mit dem
   besten Score ist. Der Score selbst steht als best_score in checkpoint.json.
```

## Beispiel: Skill-Modus Scheduled Task

```python
# Täglicher Skill Forge Run um 22:00
create_scheduled_task(
    taskId="skill-forge-linkedin-content",
    cronExpression="0 22 * * *",
    description="Skill Forge Loop für linkedin-content Skill",
    prompt="""Lies den Skill 'skill-forge' und führe den autonomen Verbesserungsloop durch.

## Konfiguration
- Workspace: /path/to/linkedin-content-skill-forge
- Config: /path/to/linkedin-content-skill-forge/config.json

## Anweisungen
1. Lies die SKILL.md des skill-forge Skills
2. Lies die config.json für alle Parameter
3. Prüfe ob history.json existiert (Resume vs. Fresh Start)
4. Führe den Loop aus bis ein Abbruchkriterium greift
5. Generiere den Morning Report
6. Speichere die beste SKILL.md"""
)
```

## Beispiel: Generic-Modus Scheduled Task

```python
# Wöchentliche Bundle-Size-Optimierung
create_scheduled_task(
    taskId="skill-forge-bundle-size",
    cronExpression="0 22 * * 0",  # Sonntags um 22:00
    description="Skill Forge Loop für Bundle-Size-Optimierung",
    prompt="""Lies den Skill 'skill-forge' und führe den autonomen Verbesserungsloop durch.

## Konfiguration
- Workspace: /path/to/project-bundle-skill-forge
- Config: /path/to/project-bundle-skill-forge/config.json

## Anweisungen
1. Lies die SKILL.md des skill-forge Skills
2. Lies die config.json (Generic-Modus, Metrik: Bundle-Size)
3. Führe den Loop aus bis Abbruchkriterium greift
4. Generiere den Morning Report"""
)
```

## Einmaliger Run

Für einen einzelnen Over-Night-Run statt einem regelmäßigen Schedule:

```python
create_scheduled_task(
    taskId="skill-forge-once-linkedin",
    fireAt="2026-03-14T22:00:00+01:00",
    description="Einmaliger Skill Forge Run für linkedin-content",
    prompt="..."
)
```
