# Release Notes

## Unreleased: Rauschgrenze, Metrik, Wissen, Optimierer-Gedächtnis und Herkunft

_Versionsnummer vergibt der Owner beim Release; Stand 2026-09-19._

**`noise_floor` war ein Platzhalter.** Der Key ging in die Keep-Schwelle ein,
stand aber immer auf 0.0, und `architecture.md` führte das als offene
Limitierung. Der Dry-Run im Generic-Modus wiederholt den Metrik-Command jetzt
mindestens dreimal auf unverändertem Stand; `noise-floor` macht aus der
Spannweite (bei `--relative` bezogen auf den Median) den Wert für die
config.json, und der Median wird Baseline. Spannweite statt
Standardabweichung, weil drei Werte keine Standardabweichung tragen.

**Die Letzte-Zahl-Regel machte Fehlermeldungen zu Messwerten.** Ein
abgebrochener Benchmark, der mit `Error in line 42` endet, lieferte 42, und in
`cmd | tail -1` geht der Exit-Code von `cmd` verloren. Eine Zeile
`METRIC <name>=<zahl>` hat jetzt Vorrang, und mit `metric --name` zählt nur
sie: fehlt sie, gibt es Exit 1 statt einer Zahl. Ohne Markierung bleibt alles
wie bisher. Einzige Verhaltensänderung für bestehende Commands: steht im
Output bereits eine vollständige Zeile `METRIC <name>=<zahl>`, gilt ab jetzt
deren Wert statt der letzten Zahl.

Anregung für beides: das Projekt autoresearch-with-claude-code
(github.com/rishabhpoddar/autoresearch-with-claude-code), das Benchmarks
`METRIC name=value` drucken, bei kaputter Umgebung laut scheitern und bei
schnellen Workloads den Median mehrerer Läufe melden lässt. Kein Code
übernommen.

12 neue Tests.

**Der Loop kannte fehlendes Wissen nicht als Fehlerursache.** Die
Klassifikation kannte zwei Klassen, `SKILL_DEFECT` und `EXECUTION_LAPSE`, und
beide setzen voraus, dass der Agent die Aufgabe lösen könnte, wenn man ihm nur
klar genug sagt wie. Fehlt eine Tatsache — eine Zitierregel, eine API-Signatur,
eine Frist —, stimmt das nicht, und der Fall landete als `SKILL_DEFECT`: der
Mutator bekam den Auftrag, eine bereits präzise Anweisung zu schärfen. Der
Mutationstyp `reference_add` trug seit v2 die Beschreibung „Agent braucht
Domänenwissen", ohne dass es einen Weg gab, dieses Wissen zu beschaffen — der
Mutator hätte die Referenzdatei aus dem Modellgedächtnis gefüllt. Genau dort
entstehen selbstbewusste Falschaussagen, und das Gate fängt sie nicht, sondern
belohnt sie: eine plausibel klingende Erfindung besteht Assertions und einen
LLM-Judge oft besser als eine sperrige Wahrheit.

Neu ist die dritte Klasse `KNOWLEDGE_GAP` mit vier mechanischen Markern
(Assertion prüft einen Wert statt einer Form; der Agent hat konkret etwas
Falsches behauptet; die Antworten streuen über Runs; der Agent hat gesucht und
nichts gefunden). Der Default ist asymmetrisch gegen sie: der Wissenszweig ist
der teuerste der drei, weil er einen Menschen unterbricht. Statt einer Mutation
erzeugt ein solcher Befund eine Frage in `knowledge-gaps.jsonl` und die
Entscheidung `DEFERRED`.

**`DEFERRED` blockiert den Auto-Modus nicht.** Ein Overnight-Lauf kann niemanden
fragen. Blockierte er, stünde der Loop still; antwortete er selbst, erfände er
Fakten. Stattdessen wird die Frage aufgeschrieben, der Loop arbeitet an
Formulierung und Determinismus weiter, und der Morning Report führt die offenen
Fragen in einem eigenen Abschnitt. Der Lauf liefert damit nicht nur einen
besseren Skill, sondern eine kurze Liste präziser Fragen.

**Plateau-Erkennung filtert `DEFERRED` heraus, statt es zu zählen.** Beide
naheliegenden Alternativen sind falsch: zählte es als Nicht-KEEP, beendete eine
Serie unbeantworteter Fragen den Lauf, obwohl keine einzige Hypothese
gescheitert ist; unterbräche es die Serie, verhinderte eine eingestreute Frage
alle drei Runden jede Plateau-Erkennung. Herausfiltern vermeidet beides, und es
füllt das Fenster auch nicht auf: zwei gemessene Nicht-KEEP plus eine Frage sind
kein Plateau. `SKIP`, `INVALID` und `NO_OP` zählen weiter mit — dort ist etwas
kaputt, und drei davon in Folge sind ein Grund anzuhalten.

Die Belegpflicht erzwingt `scripts/knowledge.py`, nicht der Prompt: eine Frage
mit weniger als zwei `eval_ids` wird mit Exit 1 abgewiesen, und Dedup über die
normalisierte Frage verhindert, dass derselbe Punkt jede Nacht neu gestellt
wird. Eine als `rejected` verworfene Frage bleibt gesperrt; eine bereits
beantwortete, deren Fehlermuster wiederkehrt, ist kein Wissensproblem mehr,
sondern ein fehlender Verweis — also ein `SKILL_DEFECT`.

Das ist Phase 1 aus `PLAN-wissen-v1.md`: erkennen und fragen, ohne jeden
Schreibzugriff auf einen Wissensbestand. Wissen entgegennehmen, evidenzgebunden
ablegen und pflegen sind Phase 2 bis 4 und sind nicht implementiert.

32 neue Tests.

**Wissen aufnehmen statt nur danach fragen.** Der Loop kann eine gemeldete
Wissenslücke jetzt aus bereitgestelltem Material schliessen. Neu sind ein
Wizard-Schritt für Wissensquellen, ein Wissensbestand beim Ziel-Skill, der
Librarian-Agent und fünf Gates vor jedem Claim.

Der Bestand liegt beim Ziel-Skill, nicht im Workspace: Wissen, das der Skill
braucht, gehört zum Skill und wird mit ihm weitergegeben. Format und
ID-Präfixe sind eine Teilmenge des SkillSafe-Wissenstresors (`C-nnnn` Claim,
`S-nnnn` Quelle) und bleiben formatkompatibel — übernommen ist das Konzept,
nicht der Code, und SkillSafe ist keine Abhängigkeit.

**Die zentrale Entscheidung ist eine Trennung.** Ob eine Formulierung besser
ist, entscheidet die Messung; ob eine Tatsache stimmt, entscheidet die Quelle.
Ein Eval-Score ist kein Wahrheitskriterium. Der *Verweis* aus der SKILL.md auf
den Bestand ist deshalb eine gewöhnliche, gate-pflichtige Mutation, der *Inhalt*
des Bestands nicht: dort prüfen Provenienz, Leak, Injection, Secrets und eine
Near-Duplicate-Sperre. Alle fünf laufen in Python und nicht als Punkt auf einer
Prompt-Checkliste — einen Agenten, der eine Regel nicht befolgt hat, per Prompt
prüfen zu lassen, ob er sie befolgt hat, ist zirkulär.

Der wichtigste der fünf ist der Leak-Check. Ohne ihn wäre die naheliegendste
Optimierung, die erwarteten Eval-Antworten als „Wissen" einzutragen: der
val-Score stiege, nichts generalisierte, und der Overfitting-Schutz wäre
unterlaufen. Geprüft wird über Achtwortfenster gegen val **und** test — ein
Claim, der eine Testantwort enthält, ist auch dann Leakage, wenn er zufällig
aus einem Dokument stammt.

Die Near-Duplicate-Sperre heisst bewusst nicht Widerspruchserkennung. Sie fängt
„gleiche Entität, andere Zahl" und nicht den subtilen Fall. Der Ausweg ist
trotzdem richtig, denn die Alternative — stilles Überschreiben — verlöre
belegtes Wissen ohne Spur. Wer ersetzen will, setzt `--supersedes`: der alte
Claim wird `veraltet`, nicht gelöscht.

**Zwei Budgets statt einem.** `INDEX.md` zählt gegen das strenge
`token_budget`, weil es bei jedem Lauf im Kontext liegt; die Seiten zählen
gegen ein eigenes `knowledge_budget`, weil sie nur gelesen werden, wenn der
Index auf sie zeigt. Mit einem einzigen Budget schlüge `artifact-stats` nach
wenigen Claims an und zwänge den Orchestrator in `forced_category: efficiency`
— der Loop finge also an, das gerade erworbene Wissen wieder wegzukürzen.

**Pflege ist eingebaut, Automatik nicht.** `verify` rechnet die Quellen-Hashes
nach und unterscheidet drei Stufen: `errors` (Claim ohne registrierte Quelle,
doppelte ID — der Bestand ist nicht vertrauenswürdig), `stale` (die Quelle hat
sich geändert, die Claims beschreiben einen Stand, den es nicht mehr gibt) und
`warnings` (eine `verweis`-Quelle, deren Pfad auf dieser Maschine fehlt: nicht
nachprüfbar, aber nicht falsch — fail-closed machte hier jeden weitergegebenen
Skill sofort rot). Aktualisiert wird nichts automatisch: was sich inhaltlich
geändert hat, ist keine Rechenaufgabe.

Der Librarian ist ein eigener Agent und keine Erweiterung des Mutators. Der
Mutator wird dafür belohnt, etwas zu schreiben; der Librarian muss bereit sein,
nichts zu liefern. Diese beiden Anreize gehören nicht in denselben Prompt.
Findet er in den bereitgestellten Quellen nichts, ist `resolved: false` das
richtige Ergebnis, und die Frage bleibt offen. Eine offene Websuche gibt es
nicht, in keinem Modus.

**Korrektur am eigenen Plan.** `PLAN-wissen-v1.md` sah die
`FORGE_KNOWLEDGE`-Region zugleich als byteweise geschützt und als
gate-pflichtig vor. Beides zusammen geht nicht: was geschützt ist, kann der
Mutator nicht ändern, und was er nicht ändern kann, kann das Gate nicht
bewerten — die erste Formulierung des Verweises wäre für immer eingefroren. Die
Region steht deshalb nicht in `PROTECTED_REGIONS`; dass es den Verweis
überhaupt gibt, prüft ein Lint in `verify`.

37 neue Tests.

**Was schon im Bestand liegt, war trotzdem eine Wissenslücke.** `gap-append`
prüfte, ob dieselbe *Frage* schon gestellt wurde — nicht, ob die *Antwort*
schon im Bestand liegt. Ein beim Wizard eingelegter Fakt ging nie durch die
Gap-Queue, also griff die Dedup-Prüfung nicht. Die Folge war eine Schleife: der
Hypothesis-Agent meldet die Lücke, der Librarian findet die Antwort im Bestand,
wo sie schon war, `claim-add` weist sie als Near-Duplicate ab. Eine Runde
verbrannt, und die eigentliche Ursache — der Agent hat den Bestand nicht
konsultiert — blieb unerkannt.

Zwei Ebenen beheben das. Der Bestandsindex liegt jetzt im Agent-Kontext, damit
der Hypothesis-Agent sieht, welche Themen gedeckt sind; das ist die
Entscheidung. Und `gap-append --skill` durchsucht den Bestand und bricht mit
Exit 3 ab; das ist die Rückfallebene. Die Schwelle ist bewusst hoch: ein
falsches „gedeckt" heisst, die Lücke wird nie gemeldet und die Tatsache nie
beschafft — ein dauerhafter blinder Fleck. Ein falsches „nicht gedeckt" kostet
eine Runde. Der zweite Fehler ist erholbar, der erste nicht.

**Ein bestandener train-Eval belegt nicht mehr automatisch, dass der Skill gut
ist.** Der Agent liest den Bestand auch in den train-Runs. Hat er dort Claims
gelesen, kam die Tatsache womöglich von dort und nicht aus einer Anweisung —
solche Runs taugen nicht als `success_patterns`, und `success_patterns` sind
die Schutzliste, die den Mutator vom Prunen abhält. Umgekehrt: ein
gescheiterter Eval, dessen Run den passenden Claim gelesen hat, ist keine
Wissenslücke, sondern ein `SKILL_DEFECT` auf den Verweis. Beide Fälle sind ohne
Zuordnung nicht von ihrem Gegenteil zu unterscheiden, deshalb erfasst
`usage-update` nach jedem Experiment aus den Transcripts, welcher Run welche
Claims gelesen hat. Das ist eine Untergrenze, keine Messung: wer eine Seite
liest und nichts zitiert, taucht nicht auf. Nebenprodukt ist `never_used` — die
Grundlage späterer Prune-Vorschläge.

Anlass für beides: WikiSkill (arXiv:2608.27454, Tang et al., Google Research).
Deren Ablation misst, dass Wiki-Zugriff des Agenten während der
Trainings-Rollouts die Skill-Qualität senkt (63,7 % auf 60,9 % im Schnitt, auf
livemath 72,6 % auf 64,8 %), weil die Trajektorien weniger über den Skill
aussagen. Ihr Mittel — Wiki im Training abschalten — passt hier nicht: deren
Wiki enthält Verfahren, die in den Skill kompiliert werden sollen, unser
Bestand enthält Tatsachen, die der Agent zur Laufzeit braucht. Übernommen ist
die Konsequenz, nicht das Mittel.

16 neue Tests.

**Das Gedächtnis des Optimierers war auf acht Bullets gedeckelt.**
`editing-notes.md` wurde alle fünf Experimente komplett neu geschrieben. Der
Deckel hielt den Kontext klein; der Preis war, dass jede Erkenntnis nach
spätestens zwei Runden herausfiel, sobald eine neuere wichtiger schien, und
dass am Ende eines Laufs nichts blieb, worauf der nächste hätte aufbauen
können.

An die Stelle tritt ein unbegrenzter Musterbestand unter
`<workspace>/patterns/`: eine Seite je Muster, die über Experimente hinweg
Evidenz sammelt, statt einer Liste, die sich selbst überschreibt. Bezahlbar
wird das durch die Trennung, die aus WikiSkill (arXiv:2608.27454) übernommen
ist: **nur `INDEX.md` liegt permanent im Kontext, eine Seite wird einzeln
gelesen, wenn ihr Titel zur Frage passt.** Zwanzig Muster kosten damit unter
1200 Token dauerhaft. Ohne diese Trennung wäre ein unbegrenzter Bestand genau
das Kontextproblem, gegen das der Achter-Deckel einmal gebaut wurde. Daraus
folgt eine Anforderung an den Meta-Agenten, die jetzt in `agents/meta.md`
steht: der Titel ist die wichtigste Zeile einer Seite, denn er entscheidet, ob
sie je geöffnet wird.

Der Anlass ist die stärkste Zahl des Papers: persistentes, über Iterationen
verdichtetes Optimierer-Wissen bringt dort +15,0 Punkte im Schnitt über vier
Benchmarks (48,7 % auf 63,7 %), auf einem davon +21,3. Es ist der grösste
Einzeleffekt der Arbeit.

Drei Regeln halten einen unbegrenzten Bestand davon ab, zu Rauschen zu werden.
**Evidenz ist programmatisch, Deutung ist Sache des Agenten**: die
Evidenzzeilen hängt der Orchestrator aus `decision.json` an, nicht der
Meta-Agent — wer seine eigene Belegzahl schreibt, belegt sich selbst. Dieselbe
Trennung wie bei WikiSkills `skill-impact.md`, das deren Harness schreibt und
nicht der Proposer. **Ein Muster mit weniger als zwei gemessenen Belegen heisst
`vorläufig`**, dieselbe Regel wie `min_support_count` bei den Hypothesen; SKIP,
INVALID, NO_OP und DEFERRED zählen nicht als Beleg, weil sie nichts gemessen
haben. Und **Irrtümer bleiben stehen**: ein widerlegtes Muster wird mit dem
widersprechenden Experiment markiert, nicht gelöscht, damit derselbe Irrtum
nicht in drei Runden neu entdeckt wird.

Die abgeleiteten Zahlen — Stützzahl, Bestwert, `vorläufig` — stehen bewusst
nicht auf der Platte, sondern werden bei jedem Lesen neu gerechnet. Das ist die
Lektion aus der Coverage-Matrix, wo `saturated` einrastete und sich eine
Kategorie nach einem späteren Treffer nie mehr erholte. Bewusst **keine**
Trefferquote: ein Muster kann positiv behaupten („Beispiele nehmen hier") oder
negativ („Prosa-Umformulierungen nicht"), und im zweiten Fall belegen
NEUTRAL-Zeilen das Muster, während KEEP-Zeilen ihm widersprächen. Eine einzelne
Quote hiesse für die beiden Fälle Gegenteiliges; ausgewiesen wird die
Verteilung, die Deutung bleibt beim Leser.

Ältere Workspaces mit `editing-notes.md` verlieren nichts: der Meta-Agent liest
die Datei einmal als Ausgangsmaterial — jeder Bullet mit Experiment-ID wird eine
Musterseite — und schreibt sie danach nicht mehr fort.

25 neue Tests.

**Nach der Weitergabe wusste niemand mehr, warum ein Abschnitt existiert.**
`history.json` und `rejected.jsonl` halten das fest, liegen aber im Workspace.
Der optimierte Skill bekommt jetzt eine `PURPOSE.md`: ein Eintrag je behaltener
Änderung, mit Hypothese, Abschnitt, Score-Verlauf — und den verworfenen
Vorversuchen derselben Kategorie, die ihr vorausgingen. Ohne die liest sich die
Datei wie ein Changelog; mit ihnen erkennt ein späterer Leser, dass er gerade
einen bereits gescheiterten Weg wieder einschlägt. Jeder Fehlversuch wird genau
einmal zugeordnet, nämlich der nächsten behaltenen Änderung nach ihm. Die Datei
zählt nicht gegen `token_budget`, weil der Agent sie zur Laufzeit nicht liest.
Vorbild ist WikiSkills `PURPOSE.md` („Previous attempt goal-directed-action was
rejected for being too abstract").

**Der Dreiwege-Split sieht eine Sorte Überanpassung nicht.** Er schützt davor,
die eigenen Testfälle auswendig zu lernen. Er schützt nicht davor, sich an das
eine Modell und den einen Aufbau anzupassen, unter dem der Lauf stattfand —
train, val und test stammen aus derselben Verteilung und laufen unter demselben
Modell. WikiSkill misst, was dabei entstehen kann: Skills, die ein kleineres
Modell für sich entwickelt hatte, senkten ein stärkeres auf derselben Aufgabe
von 50,5 % auf 18,1 %, weil sie niedrigschwellige Umgehungen seiner Schwächen
kodierten. Der Gate-Score sieht diesen Schaden nicht — er misst genau die
Kombination, für die der Notbehelf gebaut wurde.

Zwei Gegenmittel, beide ohne Eingriff ins Gate. `agents/mutator.md` hat einen
neuen Abschnitt 4.2b mit der Prüffrage vor jeder Regel: wäre sie auch für ein
stärkeres Modell oder einen anderen Aufbau richtig, oder umgeht sie eine
Einschränkung des gerade laufenden? Und ein optionales `transfer_evals`-Set aus
einem anderen Kontext wird zweimal gemessen — Baseline und Endversion — und
berichtet. **Es entscheidet nichts**, aus demselben Grund, aus dem der
test-Split nichts entscheidet: was mitoptimiert wird, misst nichts mehr.
Steigendes val bei fallendem Transfer ist die Signatur eines Notbehelfs, und
der Report sagt das.

**Eine Korrektur an der eigenen Analyse.** Die Formulierung „muss den Score über
jede registrierte Repository verbessern", die in einer früheren Sitzungsnotiz
als Vorbild auftauchte, stammt aus einem Nachbau-README und nicht aus dem
Paper. WikiSkill gated auf einem einzigen `Dval`; seine Transferzahlen sind
Analyse, nicht Torwächter. Ein Gate über mehrere Ziele wäre eine eigene
Entwurfsentscheidung mit eigenen Kosten und ist bewusst nicht gebaut.

6 neue Tests. Die Suite steht damit bei 400.

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
