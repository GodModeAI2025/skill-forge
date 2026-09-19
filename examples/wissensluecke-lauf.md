# Wissenslücken: ein durchgelaufener Pfad

Aufgezeichnet am 2026-09-19 mit `scripts/knowledge.py` 2.1.0 und
`scripts/composite_score.py` 3.0.0. Alle Ausgaben in diesem Dokument stammen
aus den gezeigten Aufrufen; nichts ist nachgetippt.

**Was dieser Lauf zeigt:** wie eine fehlende Tatsache erkannt, beschafft,
belegt abgelegt und geprüft wird — und dass die fünf Gates auslösen, wenn man
sie auslösen will. Dazu die zwei Fälle, die sich leicht verwechseln lassen:
eine Lücke, die der Bestand schon deckt, und eine, für die es keine Quelle
gibt.

**Was dieser Lauf nicht zeigt:** dass ein Skill dadurch besser wird. Die
Eval-Runs selbst brauchen einen Subagenten pro Eval und sind hier nicht
enthalten; die Transcripts im Abschnitt zur Nutzungsverfolgung sind
Platzhalter mit genau den Zitaten, die ein echter Run hinterlässt. Die
Score-Zahlen in Experiment 2 sind gesetzt, nicht gemessen — gezeigt wird die
Entscheidung, nicht die Messung.

## Aufbau

Ziel-Skill: ein Lektorats-Skill, der Belege nach den Vorgaben eines Verlags
setzen soll. Er weiß nicht, welche.

```
<ziel-skill>/SKILL.md          "Setze Belege nach den Vorgaben des Verlags."
<workspace>/knowledge-inbox/   leitfaden-verlag-x.md, vom User beigelegt
<workspace>/evals.json         3 train, 2 val
```

## Wizard-Schritt 3.5: Quelle registrieren

```bash
knowledge.py source-add <ziel-SKILL.md> <workspace>/knowledge-inbox/leitfaden-verlag-x.md \
  --title "Autorenleitfaden Verlag X, Fassung 3" --trust T1 --rights volltext --stand 2026-09-01
```

```json
{
  "created": true,
  "source_id": "S-0001",
  "sha256": "97fe6603d7c0b61dde5a0b5f94a9afe6338c24911fa9cb0d712dc312b504bcc9",
  "ablage": "knowledge/sources/S-0001__leitfaden-verlag-x.md",
  "trust": "T1",
  "rights": "volltext"
}
```

`volltext` kopiert die Datei in den Bestand. Ohne die Kopie wäre die Provenienz
nach der Weitergabe des Skills nicht mehr nachprüfbar — der Hash zeigte dann
auf eine Datei, die nur der Autor hat.

## Experiment 1: Lücke erkannt, Antwort beschafft

Der Hypothesis-Agent klassifiziert das Fehlermuster als `KNOWLEDGE_GAP`: die
gescheiterte Assertion prüft einen **Wert**, und der Agent hat in jedem Run
einen anderen erfunden. Zwei der vier Marker aus `agents/hypothesis.md` 2c.

```bash
knowledge.py gap-append <workspace>/knowledge-gaps.jsonl \
  --from-json hypothesis.json --experiment exp-001 --skill <ziel-SKILL.md>
```

```json
{
  "gap_id": "gap-001",
  "question": "Welchen Belegstil verlangt Verlag X im Fliesstext?",
  "why_needed": "3/3 train-Evals failen 'beleg_kurzform'; der Agent erfindet in jedem Run eine andere Form",
  "answer_shape": "Eine Regel: Kurzbeleg oder Vollbeleg, plus die Ausnahmen",
  "eval_ids": ["belege-fliesstext", "belege-fussnote", "belege-tabelle"]
}
```

Der Librarian liest den Leitfaden und schlägt fünf Claims vor. Zwei davon sind
gut; die anderen drei sind die interessanten.

```bash
knowledge.py claim-add <ziel-SKILL.md> --page belegregeln \
  --from-json librarian.json --evals <workspace>/evals.json \
  --domain lektorat --title "Belegregeln Verlag X" --stichwort beleg --stichwort belegstil
```

```
geschrieben: 2
  OK       C-0001 Im Fliesstext steht der Kurzbeleg mit Autor, Jahr und Seite.
  OK       C-0002 Bei Gesetzestexten entfaellt der Kurzbeleg; die Fundstelle …
  ABGEWIESEN leak       belege-val                            | Der Vollbeleg erscheint …
  ABGEWIESEN secret     AWS Access Key                        | Der Zugang zum Autorenportal …
  ABGEWIESEN secret     Zugangsdatum als Wert                 | Der Zugang zum Autorenportal …
  ABGEWIESEN provenienz Quelle S-0002 steht nicht im Register | Fussnoten werden fortlaufend …
```

Drei Gates, drei verschiedene Schäden:

**Der Leak-Check ist der wichtigste.** Der abgewiesene Claim ist wörtlich die
Assertion des val-Evals `belege-val`. Er wäre durch alle anderen Prüfungen
gekommen — er hat eine registrierte Quelle, eine Fundstelle, keine Geheimnisse
—, und er hätte den val-Score gehoben, ohne dass irgendetwas generalisiert.
Genau das ist die naheliegendste Optimierung, wenn niemand hinsieht.

**Das Secret-Gate schlägt zweimal an**, weil zwei Muster greifen (bekanntes
Key-Präfix und Zuweisungsform). Der Bestand wird mit dem Skill weitergegeben;
ein Token darin ist ein Leck, kein Wissen.

**Das Provenienz-Gate** weist eine Aussage ab, deren Quelle nicht im Register
steht. Sie mag stimmen — belegt ist sie nicht.

Danach:

```bash
knowledge.py gap-resolve <workspace>/knowledge-gaps.jsonl gap-001 \
  --status sourced --resolved-by S-0001
knowledge.py verify <ziel-SKILL.md>
```

```
  ok True | claims 2 | errors 0 | stale 0
  WARNUNG kein_verweis — Bestand vorhanden, aber die SKILL.md hat keine FORGE_KNOWLEDGE-Region
```

Die Warnung ist berechtigt: der Bestand existiert, aber nichts zeigt darauf.
Der Agent fände ihn nie.

## Experiment 2: der Verweis ist eine normale Mutation

Spur A ist erledigt — die Claims stehen und sind belegt. Spur B ist eine
gewöhnliche gate-pflichtige Mutation: der Verweis aus der SKILL.md auf den
Bestand.

```markdown
<!-- FORGE_KNOWLEDGE_START -->
Wissensbestand: knowledge/INDEX.md
Für die dort geführten Themen ist der Bestand die alleinige Faktenquelle.
Nicht im Bestand → sag das, ergänze nicht aus eigenem Wissen.
<!-- FORGE_KNOWLEDGE_END -->
```

```
decide: KEEP | delta +0.2400
delta = 0.8600 - 0.6200 = +0.2400; threshold = max(improvement 0.0200,
noise_floor 0.0000, resolution 0.0000) = 0.0200 …
```

`verify` meldet die Warnung danach nicht mehr.

Das ist die Zwei-Spuren-Trennung in einem Bild: **ob die Tatsache stimmt,** hat
die Quelle entschieden; **ob es nützt, den Agenten darauf zu stoßen,** hat das
Gate entschieden.

## Experiment 3: was schon im Bestand liegt, ist keine Lücke

Zwei Runden später meldet der Hypothesis-Agent eine fast gleiche Frage — anders
formuliert, also greift die Dedup-Prüfung über die Frage nicht.

```bash
knowledge.py gap-append … --experiment exp-003 --skill <ziel-SKILL.md>
# exit=3
```

```
covered_by_vault: True | score 0.6 >= 0.6
Treffer: C-0001 | geteilt: belegstil, fliesstext, verlag
```

**Kein Gap, kein Librarian, kein `DEFERRED`.** Die Tatsache liegt da und
erreicht den Agenten nicht — das ist ein `SKILL_DEFECT` auf den Verweis, und
die Runde läuft als normales Experiment weiter.

Ohne diese Prüfung entstünde eine Schleife: Lücke gemeldet, Librarian findet
die Antwort im Bestand, `claim-add` weist sie als Near-Duplicate ab, Runde
verbrannt — und die eigentliche Ursache bliebe unerkannt. Besonders betroffen
sind Fakten, die beim Wizard eingelegt wurden: die sind nie durch die Gap-Queue
gegangen.

## Experiment 4: keine Quelle, also eine Frage

```bash
knowledge.py gap-append … --experiment exp-004 --skill <ziel-SKILL.md>
# gap-002 angelegt; der Librarian findet in den Quellen nichts → resolved: false
```

Kein Snapshot, kein Mutator, kein Eval-Run. Entscheidung `DEFERRED`, Kategorie
`knowledge`, weiter zur nächsten Hypothese.

```
plateau: False | deferred_skipped: 2
```

Auch bei `["KEEP", "DEFERRED", "DEFERRED"]` ist das kein Plateau: `DEFERRED`
wird vor dem Fenster herausgefiltert. Zählte es mit, beendete eine Serie
unbeantworteter Fragen den Lauf, obwohl keine Hypothese gescheitert ist.

Im Morgenreport steht:

```
### gap-002 [open]
Frage: Wie hoch ist die Verguetung pro Druckbogen?
Woran erkannt: 2/2 val-nahe train-Evals nennen erfundene Betraege
Brauchbare Antwort: Ein Betrag in Euro, plus Stichtag
Belegt durch: verguetung-a, verguetung-b | Experiment: exp-004 | Domäne: vertrag
```

Das ist die Zeile, für die der ganze Zweig gebaut ist. Der Lauf hat die Zahl
nicht erfunden, sondern die Frage aufgeschrieben — samt dem, woran er sie
gemerkt hat, und samt der Form einer brauchbaren Antwort.

## Nutzungsverfolgung: was ein Erfolg noch belegt

```bash
knowledge.py usage-update <workspace>/knowledge-usage.json \
  --skill <ziel-SKILL.md> --experiment-dir <workspace>/experiments/exp-002 --experiment exp-002
```

```json
{
  "experiment": "exp-002",
  "runs_with_vault_access": 2,
  "claims_used": {"C-0001": 1},
  "never_used": ["C-0002"]
}
```

Im Agent-Kontext der nächsten Runde:

```
- belege-fliesstext [with_mutation]: Claims C-0001 | Seiten belegregeln
- belege-fussnote [with_mutation]: Claims — | Seiten belegregeln

Nie gelesen: C-0002
```

Die zweite Zeile ist der Fall, um den es geht: Der Run hat die Seite gelesen
und keinen Claim zitiert — er hat also nachgesehen und nichts Passendes
gefunden. Scheitert dieser Eval, ist das kein Beleg für eine Wissenslücke,
sondern dafür, dass der vorhandene Claim nicht trägt.

`never_used` sammelt nebenbei, was Budget belegt, ohne etwas zu tun.

## Quellendrift

Der Verlag legt Fassung 4 vor, die Datei im Bestand ändert sich:

```
verify exit=1
  ok: False
  STALE quelle_geaendert   S-0001 — SHA-256 weicht vom Register ab
  STALE claim_zu_pruefen   C-0001 — Quelle S-0001 hat sich geändert
  STALE claim_zu_pruefen   C-0002 — Quelle S-0001 hat sich geändert
```

Beide abhängigen Claims sind markiert, **keiner ist aktualisiert**. Was sich
inhaltlich geändert hat, ist keine Rechenaufgabe — ob die Regel noch gilt,
entscheidet ein Mensch.

## Budget

```
INDEX.md (permanent): 221 Token gegen token_budget
Seiten (auf Abruf):   173 Token gegen knowledge_budget, Headroom 7827
```

Die Trennung folgt der Ladelogik. Mit einem einzigen Budget schlüge
`artifact-stats` nach wenigen Claims an und zwänge den Orchestrator in
`forced_category: efficiency` — der Loop finge an, das gerade erworbene Wissen
wieder wegzukürzen.

## Artefakt am Ende

```
<ziel-skill>/SKILL.md
<ziel-skill>/knowledge/INDEX.md
<ziel-skill>/knowledge/SOURCES.md
<ziel-skill>/knowledge/pages/belegregeln.md
<ziel-skill>/knowledge/sources/S-0001__leitfaden-verlag-x.md
```

```
| Seite | Stichworte | Claims | Stand | Status |
|---|---|---|---|---|
| [Belegregeln Verlag X](pages/belegregeln.md) | beleg, belegstil | 2 | 2026-09-19 | aktiv |
```

Alles davon reist mit dem Skill mit. Wer ihn bekommt, kann zu jeder Aussage die
Quelle, die Fundstelle und den Stand nachschlagen — und `verify` sagt ihm, ob
sie noch stimmt.

## Was der Lauf über den Code gesagt hat

- Der Leak-Check hat den einen Claim abgewiesen, der den Score gehoben und
  nichts generalisiert hätte. Ohne ihn wäre das die naheliegendste Optimierung.
- Das Secret-Gate schlägt mehrfach an, wenn mehrere Muster greifen. Das ist
  lauter als nötig, aber in der richtigen Richtung laut.
- Der Bestands-Check greift bei einer umformulierten Frage (Deckungsgrad 0.6,
  genau auf der Schwelle). Der Grenzfall ist knapp — das ist Absicht: ein
  falsches „gedeckt" liesse eine echte Lücke für immer verschwinden, ein
  falsches „nicht gedeckt" kostet eine Runde.
- `verify` bleibt bei `ok: true`, solange nur der Verweis fehlt, und wird erst
  bei Drift rot. Die Abstufung zwischen Warnung und Fehler trägt.
