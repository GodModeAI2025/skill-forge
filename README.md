# Skill Forge v3

Autonomous improvement of AI skills and generic codebases through iterative experimentation. An AI agent modifies instructions or code, evaluates each change against objective metrics, keeps improvements, and reverts regressions. Runs fully autonomous or in guided mode where the user decides at every step.

## What it does

Skill Forge runs an experiment loop in two modes:

**Skill Mode**: optimizes a Claude Cowork Skill's SKILL.md against eval assertions:

```
Analyze → Hypothesize → Mutate SKILL.md → Evaluate → Score → Keep/Revert → Repeat
```

**Generic Mode**: optimizes any file against any shell command that returns a number:

```
Analyze → Hypothesize → Mutate target file → Run metric command → Score → Keep/Revert → Repeat
```

You point it at a skill or codebase, it finds weaknesses, fixes them, and delivers an improved version with a full experiment log. Run it overnight, wake up to a better skill.

## What v3 changed

v2 described a loop. v3 makes the loop's decisions mean something. The changes
fall into four groups.

### The decision is code, not prose

- **One decision function.** `decide()` and the `decide` subcommand are the only
  place where two scores turn into a verdict. Three outcomes, no fourth. In v2
  the cascade lived as pseudocode in SKILL.md, and its NEUTRAL branch was
  unreachable: over 4001 deltas it fired exactly once.
- **NEUTRAL reverts.** A tie rolls the mutation back. A loop that keeps the new
  version on a zero round drifts away from its baseline without a single
  measurement to justify it.
- **`near_miss` is a flag on NEUTRAL**, not a separate outcome. It marks the
  band just below the keep threshold, so the next round can vary the same
  hypothesis instead of dropping it.
- **Snapshot and revert exist.** With a manifest, absolute paths and scope
  cleanup. v2 documented a revert that no line of code performed, and its
  snapshot command aborted with exit 1 whenever the target directory was
  missing.

### The number means what it claims

- **Resolution floor.** The keep threshold is
  `max(improvement_threshold, noise_floor, resolution)` with
  `resolution = 2 / N_assertions`. A fixed 0.02 sits below the resolution of any
  realistic eval set, so in v2 a single assertion flip always triggered a KEEP.
- **Efficiency out of the gate.** Assertions carry it alone, or 0.65/0.35 with
  the comparator. Efficiency is still measured and reported; it just stopped
  deciding. Two constructed runs with identical assertions came out 0.045 apart
  on token and duration noise alone, against a keep threshold of 0.02.
- **Measured noise floor.** In generic mode the dry run repeats the metric
  command on the unchanged state and `noise-floor` turns the spread into the
  `noise_floor` config value. Until then the key sat at 0.0, and a metric that
  wobbles 3 % between identical runs produced random KEEPs against a 2 %
  threshold.
- **Marked metrics.** A line `METRIC <name>=<number>` beats the last-number
  rule, and `metric --name` accepts nothing else. Otherwise `Error in line 42`
  from a crashed benchmark becomes the score 42.
- **`--side` in scoring.** Candidate and baseline are scored separately. v2
  collected both with one `rglob` and averaged them into a single number.
- **Real three-way split.** train (50%) feeds hypotheses, val (25%) decides
  keep/revert, test (25%) is touched exactly twice. Assigned by a stable hash
  per eval id, so deleting one eval does not shuffle the rest. In v2 the split
  was a config value that no code ever applied.
- **Longitudinal comparison.** `compare` pairs the same evals across both
  versions and lists regressions first. An aggregate nets five new hits against
  three new failures into a plus two and calls it progress.
- **NO_OP.** `diff` produces a unified diff against the snapshot; a mutation
  that moved no bytes never reaches scoring.

### The loop cannot cheat

- **Reward-hacking guard.** `invariants-snapshot` and `invariants-check` pin the
  metric config, the test files, the file count and the byte size of the scope.
  Without a passing check `metric` returns `INVALID` instead of a number. The
  optimal mutation for `flake8 src/ | wc -l` is to delete `src/`.
- **Protected regions.** `FORGE_KEEP` belongs to the user and the loop never
  touches it. `FORGE_APPENDIX` holds notes that bypass the gate. Enforced
  byte-wise by `verify-regions` in Python, not as a prompt-level self-check: an
  agent that ignored a rule is a poor judge of whether it ignored the rule.
- **Token budget with teeth.** `artifact-stats` counts SKILL.md plus everything
  the loop wrote under `references/` and `scripts/`. A budget that counts only
  the main file is dodged in one round via `reference_add`.

### The agents see more

- **Defect vs lapse.** Every failure pattern is classified before a cause is
  sought: was there already a rule that would have prevented this? If yes, that
  produces an appendix note, not a mutation. When in doubt, lapse. Otherwise a
  single subagent slip costs a correct rule, and the gate cannot see it because
  the difference sits below the resolution floor.
- **Success analysis as a protection list.** `success_patterns` stop `prune` and
  `structure_change` from deleting the sections that carry the passing evals.
- **Rejected buffer.** `rejected.jsonl` keeps every non-KEEP verbatim, untouched
  by history compaction, and renders into the next prompt.
- **Three candidates, one applied.** The hypothesis agent produces three and
  ranks them against four criteria in the same prompt. Still exactly one change
  per experiment; that rule is stricter than SkillOpt's edit budget of four and
  it stays.
- **Meta memory.** A pattern store records what kind of edit works *for this
  skill*. Optimizer-facing, never written into the target. Uncapped, with the
  index in the context and pages read on demand; evidence is appended
  programmatically from `decision.json`, and a refuted pattern is marked with
  the experiment that refuted it rather than deleted.
- **Evidence is never truncated.** The context budget applies to history and
  notes, not to the transcripts of the current experiment.

### And it is tested

406 tests under `tests/` (`python3 -m pytest tests/ -q`), including `test_review_findings.py`, which pins every
defect two adversarial review rounds found in this code. A mutation test over 69
targeted code changes drove the remaining blind spots out.

`examples/generic-mode-lauf.md` documents a full generic-mode run in which three
deliberate reward hacks were each rejected.

## Carried over from v2

- Two-mode architecture: Skill Mode (SKILL.md + evals) and Generic Mode (any
  file + shell metric)
- 6-step setup wizard with a hard gate per step
- Mandatory dry-run before the loop starts
- Flat TSV log next to the JSON history
- Coverage matrix with saturation detection
- Exploration early, exploitation late
- Consecutive crash limit with a SKIP path
- Guided mode with five checkpoints

## How it works

```
  Setup Wizard ── 6 steps, each with a hard gate
       │
       ▼
  Dry-Run Gate ── exit 0 + parseable number + resolution shown
       │ PASS
       ▼
┌──► Hypothesis ── train split only
│     │            classify lapse / knowledge gap / defect, three candidates,
│     │            rank, pick one
│     ▼
│    knowledge gap? ── yes ──► gap-append, ask the human ──────────────► DEFERRED
│     │ no
│     ▼
│    snapshot ─────────── state before experiment N
│    invariants-snapshot ─ protected paths, file count, byte size
│     │
│     ▼
│    Mutator ── one focused change
│     │
│     ▼
│    verify-regions ── FORGE_KEEP / FORGE_APPENDIX untouched?  ── no ──► INVALID
│    diff ──────────── changed anything?  ── no ──────────────────────► NO_OP
│     │ yes
│     ▼
│    Run ── val split, candidate and baseline side by side
│     │     (generic mode: metric command + invariants-check)
│     ▼
│    score --side ── gate score per side, reports the resolution
│    compare ─────── same evals both versions, regressions first
│     │
│     ▼
│    decide ── delta ≥ max(improvement, noise_floor, resolution) → KEEP
│     │        delta ≤ −regression                               → REVERT
│     │        otherwise                                         → NEUTRAL
│     ▼
│    REVERT / NEUTRAL ──► revert to snapshot
│    every non-KEEP ────► rejected.jsonl (verbatim)
│    lapse notes ───────► FORGE_APPENDIX (last write of the step)
│     │
│     ▼
│    tsv-append · coverage-update · artifact-stats · checkpoint-save
│     │
└─────┘  every 5 experiments: patterns/
         stop on: target reached · max_experiments · 3 consecutive non-KEEP
                  · time budget · 3 consecutive crashes

  Report ── val progression, test split (touched here for the second and last
            time), longitudinal comparison, resolution, coverage
```

## Command reference

`scripts/composite_score.py` has 26 subcommands. Everything the loop decides
goes through one of them.

| Subcommand | Purpose |
|---|---|
| `score <dir> --side` | Gate score for one side, reports `total_assertions` and `resolution` |
| `decide` | The only place a delta becomes a verdict. Emits the formula it used |
| `plateau` | Three consecutive non-KEEP decisions |
| `resolution --assertions N` | Smallest measurable difference for this eval set |
| `split-assign` | Assigns train/val/test by a stable hash per eval id |
| `snapshot` / `revert` | State before experiment N, with manifest and scope cleanup |
| `diff` | Unified diff against the snapshot; `changed: false` means NO_OP |
| `compare` | Pairs the same evals across both versions, regressions first |
| `verify-regions` | Byte-wise check of the protected regions, exit 1 on violation |
| `appendix-append` | Adds lapse notes to the protected appendix, deduplicated and capped |
| `rejected-append` / `rejected-format` | Verbatim record of every non-KEEP, rendered into the next prompt |
| `artifact-stats` | Token budget across SKILL.md, `references/` and `scripts/` |
| `invariants-snapshot` / `invariants-check` | Reward-hacking guard for generic mode |
| `metric` | Extracts the number (`METRIC <name>=<n>` first, `--name` for marker only), refuses one when the invariants broke |
| `noise-floor` | Spread of repeated runs on the unchanged state, relative with `--relative` |
| `tsv-init` / `tsv-append` | Flat log, direction-aware |
| `coverage-init` / `coverage-update` | Coverage matrix with saturation |
| `compact` / `agent-history` / `group-history` | History views for the agents |
| `purpose-append` | Why a kept change looks like this, into the target's `PURPOSE.md`, with the rejected predecessors |
| `checkpoint-save` / `checkpoint-info` | Resume across sessions and crashes |

`scripts/knowledge.py` holds the knowledge-gap queue. Separate script, separate
test file: `composite_score.py` turns two numbers into a verdict, this one keeps
a list of open questions, and the two fail in different ways.

| Subcommand | Purpose |
|---|---|
| `gap-append` | Records a knowledge gap if it is new. Rejects a question backed by fewer than two train evals |
| `gap-resolve` | Appends a new state (answered, sourced, rejected, conflict). Never overwrites |
| `gap-list` / `gap-stats` | Current state per gap, counts per status |
| `gap-format` | The block rendered into the agent prompt and the morning report |
| `init` | Creates the knowledge tree next to the target SKILL.md |
| `source-add` | Registers a source with SHA-256, trust level and rights |
| `claim-add` | Writes claims after all five gates. Exit 2 if none got through |
| `verify` | Structure, provenance, source drift. Exit 1 on errors or stale sources |
| `index` | Regenerates `INDEX.md` deterministically |
| `stats --budget` | Vault size, index counted separately from the pages |
| `leak-check --evals` | Scans the whole vault against the val and test splits |
| `search` | Does the vault already answer this question? Exit 0 = yes |
| `usage-update` | Records from the transcripts which run read which claims |
| `usage-format` | The usage block rendered into the hypothesis agent's context |
| `prune-suggest` | Claims never read across many experiments. Suggests; writes nothing |

`scripts/patterns.py` holds the optimizer's own memory — what kind of edit works
*for this skill*. Separate from `knowledge.py` on purpose: that one holds the
target skill's knowledge, and coupling the two would be exactly the mixing
`agents/meta.md` warns against.

| Subcommand | Purpose |
|---|---|
| `add` | New pattern page, or several from the meta agent's output |
| `evidence` | Appends one experiment's outcome. Called by the orchestrator, not the agent |
| `update` | Refines a pattern, or marks it `widerlegt` with the contradicting experiment |
| `index` / `format` | Regenerates `INDEX.md`; renders it into the prompt |
| `show` | One page verbatim — the on-demand read |
| `stats` | Counts, including what the index costs in tokens |

### The six agents

| Agent | Role | Input | Output |
|-------|------|-------|--------|
| **Hypothesis** | "Scientist", analyzes failures, checks coverage matrix | Grading results, SKILL.md, history, coverage | Testable hypothesis with mutation proposal |
| **Mutator** | "Surgeon", applies one focused change | Hypothesis, target file | Modified file + documentation |
| **Scorer** | "Judge", evaluates output quality (Skill Mode) | Eval prompt, output | Normalized quality score (0-1) |
| **Meta** | "Archivist", distils what kind of edit works for this skill; runs every 5 experiments | pattern index, history, rejected buffer, kept mutations | New and refined pattern pages under `patterns/` |
| **Librarian** | "Librarian", sources the answer to a knowledge gap from supplied material — or reports that it found none | Knowledge gap, inbox, source register, existing claims | Sourced claims with passages, or `resolved: false` |
| **Orchestrator** | "Conductor", assembles the context for the others, decides the phase, handles handover and checkpoints | history, coverage matrix, checkpoint.json, near-miss hypotheses | Filled agent context, validated agent outputs, loop meta-decisions |

### Setup Wizard (6 Steps)

| Step | Gate | Fail action |
|------|------|------------|
| 1. Execution mode + target | Auto/Guided selected, target identified | Abort |
| 2. Define scope | Glob matches ≥1 file (Generic) or SKILL.md found (Skill) | Retry pattern |
| 3. Define metric | ≥6 evals with a three-way split (Skill) or valid shell command (Generic) | Create evals / reject subjective metric |
| 3.5. Knowledge sources | Material registered with trust level and rights, or explicitly none | Continue without the knowledge branch |
| 4. Set direction | higher\_is\_better or lower\_is\_better confirmed | Abort |
| 5. Dry-run validation | Exit code 0, output contains parseable number | Suggest fix, retry |
| 6. Confirm config | User reviews and approves full configuration | Adjust parameters |

### Gate Score (Skill Mode)

```
composite = assertion_pass_rate × 1.00
```

With optional LLM-as-Judge (blind comparison):

```
composite = assertion_pass_rate × 0.65 + llm_judge × 0.35
```

Efficiency no longer gates anything. It is still computed and lands under
`details.efficiency_score`, and it belongs in the morning report, but it does not move
the number the decision reads. Two constructed runs with identical assertions (20k tokens / 60s against 45k / 120s)
come out 0.045 apart under the old weighting, purely on token and duration noise,
against a keep threshold of 0.02. That is arithmetic from the v2 formula, not a
measured spread: how far the score actually varies between two identical runs has
never been measured here. A signal that large drowns the thing the loop is supposed to measure. The second
reason: an empty experiment directory scored 0.20, because `calc_efficiency_score(0, 0.0)`
is exactly 1.0. Missing data now raises an error instead of producing a score.

Score one side at a time. Without `--side` both sides are mixed, which is almost always
wrong:

```
python3 scripts/composite_score.py score <exp-dir> --side with_mutation
python3 scripts/composite_score.py score <exp-dir> --side baseline
```

### Keep/Revert Decision

Three outcomes, no fourth:

```
delta = candidate - baseline          # negated for lower_is_better
threshold = max(improvement_threshold, noise_floor, resolution)

delta >  threshold    →  KEEP      # clear improvement, mutation stays
delta < -regression   →  REVERT    # regression, roll back
otherwise             →  NEUTRAL   # roll back as well
```

`DEFERRED` is not a fourth outcome of `decide()`. Like `SKIP`, `INVALID` and `NO_OP`
it comes from the surrounding flow: the hypothesis agent found a missing *fact*
rather than a missing instruction, so there was no mutation and nothing to measure.
The loop writes the question to `knowledge-gaps.jsonl` and moves on — see
[Knowledge gaps](#knowledge-gaps).

`near_miss` is a boolean flag on NEUTRAL, not a separate outcome. It is true when
`delta > threshold - near_miss_band` (default band 0.02), the range just below the keep
threshold where a variation of the same hypothesis is worth trying.

NEUTRAL rolls the mutation back, ties included. Keeping a change that measured nothing
sounds harmless, but over ten experiments a loop that keeps every null round drifts away
from its starting point without a single measurement backing the distance. No lateral
moves.

The decision lives in exactly one function, `decide()`, exposed as a subcommand:

```
python3 scripts/composite_score.py decide \
  --candidate 0.84 --baseline 0.78 --config <workspace>/config.json
```

It prints JSON with `decision`, `near_miss`, `delta`, `threshold`, the three thresholds
it used, `direction`, `relative`, `relative_fallback`, and `formula`. `relative_fallback`
is true when `--relative` was set but the baseline is 0, in which case `decide` falls back
to the absolute delta. The `formula` string is a readable trace
of the arithmetic and belongs in `decision.json`. Options: `--direction
higher_is_better|lower_is_better`, `--relative` (delta normalized against the baseline,
the sane mode for Generic Mode metrics measured in KB or seconds), `--noise-floor`.
Values from `config.json` win over argparse defaults.

## Quick start

### 1. Install as Cowork Skill

Copy the `skill-forge/` directory into your Claude Cowork skills folder:

```bash
mkdir -p ~/.skills/skills
cp -r skill-forge/ ~/.skills/skills/skill-forge/
```

`mkdir -p` first: `cp` fails with exit 1 if the parent does not exist yet, which
is the normal case on a fresh install.

Then check that the machinery works, without spending a single API call:

```bash
python3 -m pytest tests/ -q
```

### 2. Use it (Skill Mode, Auto)

Tell Claude:

> "Use skill-forge to improve my linkedin-content skill"

### 3. Use it (Guided Mode)

Tell Claude:

> "Use skill-forge in guided mode to improve my humanizer skill, I want to decide at each step"

### 4. Use it (Generic Mode)

Tell Claude:

> "Use skill-forge to optimize train.py, metric command: python train.py --eval, direction: lower_is_better"

### 5. Run overnight (Scheduled Task)

```
Use the skill-forge skill to run the autonomous improvement
loop on the "linkedin-content" skill.

Workspace: ~/linkedin-content-skill-forge
Max experiments: 10
Time budget: 120 minutes
```

## Repository structure

```
skill-forge/
├── SKILL.md                          # Main skill instructions (v3)
├── RELEASE_NOTES.md                  # Changelog (v3 + v2)
├── PLAN-wissen-v1.md                 # Plan for knowledge gaps (phase 1 shipped)
├── agents/
│   ├── hypothesis.md                 # Failure analysis → hypothesis
│   ├── meta.md                   # Optimizer-side memory, every 5 experiments
│   ├── mutator.md                    # Hypothesis → file mutation
│   ├── scorer.md                     # LLM-as-Judge quality scoring
│   ├── orchestrator.md               # Context assembly, handover, checkpoints
│   └── librarian.md                  # Sourcing from supplied material; may come back empty
├── scripts/
│   ├── __init__.py
│   ├── composite_score.py            # Score, decide, snapshot/revert, TSV, coverage
│   ├── knowledge.py                  # Gap queue and knowledge vault: sources, claims, gates, verify
│   └── patterns.py                   # Optimizer-side pattern store: pages, evidence, index
├── templates/
│   ├── morning_report.md             # Report template with coverage matrix
│   └── agent_context.md              # Runtime context injected into agent prompts
├── references/
│   ├── architecture.md               # Detailed architecture docs
│   └── scheduled_task_template.md    # Cron job setup (both modes)
├── examples/
│   ├── generic-mode-lauf.md          # A real end-to-end generic run, with the guards firing
│   ├── wissensluecke-lauf.md         # A real end-to-end knowledge run: gap, sourcing, five gates, drift
│   └── fachbuch-lektorat-session.md  # Real experiment log
├── conftest.py                       # Puts the repo root on sys.path for pytest
├── tests/
│   ├── test_decide.py                # Decision cascade, thresholds
│   ├── test_scoring.py               # Gate score, --side, empty dirs
│   ├── test_coverage.py              # Coverage matrix, saturation
│   ├── test_snapshot_revert.py       # Snapshot manifest, revert scope
│   ├── test_history.py               # Compaction, archive, checkpoints
│   ├── test_generic_and_cli.py       # Generic mode, every CLI exit code
│   ├── test_block2.py                # Resolution, splits, diff, comparison
│   ├── test_block3.py                # Protected regions, appendix, rejected
│   ├── test_block4.py                # Token budget, invariants
│   ├── test_review_findings.py       # Every defect the adversarial review found
│   ├── test_knowledge.py             # Gap queue, evidence rule, dedupe, DEFERRED
│   ├── test_knowledge_base.py        # The five gates, source register, verify, budgets
│   └── test_patterns.py              # Pattern store: evidence, support, index economics
├── LICENSE                           # MIT
└── README.md
```

## Workspace structure (generated per run)

```
<target>-skill-forge/
├── config.json              # Mode, thresholds, paths, session tag
├── evals.json               # Test cases with train/test split (Skill Mode)
├── experiment-log.tsv       # Flat TSV log
├── coverage-matrix.json     # Category coverage tracking
├── checkpoint.json          # Resume point (on-disk version, applied_but_undecided)
├── rejected.jsonl           # Every non-KEEP verbatim, survives compaction
├── knowledge-gaps.jsonl     # Missing facts as questions, append-only
├── knowledge-inbox/         # Material supplied by the user
├── knowledge-usage.json     # Which run read which claims
├── patterns/                # Optimizer-side memory, uncapped
│   ├── INDEX.md             #   small, permanently in the agent context
│   └── P-NNNN__slug.md      #   one page per pattern, read on demand
├── snapshots/
│   ├── pre-exp-001/         # State before exp-001, the baseline
│   │   ├── manifest.json
│   │   └── files/...
│   ├── pre-exp-002/         # State before exp-002
│   └── ...
├── experiments/
│   ├── exp-001/
│   │   ├── hypothesis.json
│   │   ├── mutation.json
│   │   ├── comparison.json  # Judge rubric (only with use_comparator)
│   │   ├── score_with_mutation.json
│   │   ├── score_baseline.json
│   │   ├── decision.json    # decide() output, including the formula string
│   │   └── runs/
│   │       └── eval-0/
│   │           ├── with_mutation/{grading.json,timing.json,outputs/}
│   │           └── baseline/{grading.json,timing.json,outputs/}
│   └── ...
├── history.json             # Score progression (compacted)
├── history.archive.jsonl    # Full records, written before compaction
└── morning-report.md        # Human-readable summary
```

Snapshot directories are named `pre-exp-NNN`: the state *before* experiment N. That name
is unambiguous next to the `version: "v1", parent: "v0"` fields inside history.json, which
the old `v0`/`v1` directory names collided with. Snapshot and revert are subcommands, not
shell blocks:

```
python3 scripts/composite_score.py snapshot \
  --target <path-or-glob> --snapshot-dir <workspace>/snapshots --version pre-exp-001

python3 scripts/composite_score.py revert \
  --snapshot-dir <workspace>/snapshots --version pre-exp-001
```

`snapshot` creates missing directories, resolves globs in Python, and writes a manifest
plus a copy of every file. `revert` restores from that manifest and deletes files inside
the scope that the manifest does not list, which is exactly the set the mutation created.

## Key features

### TSV Experiment Log

Every experiment is logged as a single tab-separated line for quick `tail -f` monitoring.
Nine columns:

```
timestamp  experiment  hypothesis_summary  metric_before  metric_after  delta  decision  category  duration_s
```

### Coverage Matrix

Tracks which categories of improvements have been tried, with saturation detection:

```
| Category       | Experiments | KEEP | REVERT | Best Delta | Saturated |
|----------------|-------------|------|--------|------------|-----------|
| workflow        | 3           | 2    | 1      | +0.16      | no        |
| edge_cases      | 1           | 0    | 0      | ±0.00      | no        |
| formatting      | 0           | -    | -      | -          | untouched |
```

### Exploration-Exploitation Strategy

| Phase | Rounds | Strategy |
|-------|--------|----------|
| Early | 1-3 | Explore: prioritize untouched categories |
| Mid | 4-7 | Mixed: balance coverage with promising areas |
| Late | 8+ | Exploit: focus on categories with best deltas |

## Overfitting protection

| Mechanism | How it works |
|-----------|-------------|
| **Three-way split** | train (50%) feeds hypotheses, val (25%) decides, test (25%) is touched twice. Stable hash per eval id |
| **Resolution floor** | The keep threshold is at least `2 / N_assertions`. Below that nothing is kept, because below that nothing is measured |
| **Generalization check** | The hypothesis agent must explain why the change generalizes, and a pattern needs `support_count >= 2` |
| **Mutation diversity** | Coverage matrix tracks which categories were tried, with saturation detection |
| **Eval rotation in train only** | Fresh queries replace the oldest train evals after 5 experiments. val and test stay frozen; changing val forces a re-baseline |
| **Longitudinal comparison** | `compare` lists regressions individually instead of netting them against improvements |
| **Transfer set** | An optional second eval set from a different context shows what val and test cannot: adaptation to the one model and setup. Measured and reported, never gated |
| **Success protection list** | `success_patterns` stop `prune` from removing the sections that carry the passing evals |
| **No invented facts** | A missing fact is reported as a question, never filled in from model memory. A plausible-sounding invention passes assertions better than a clumsy truth, so the gate would reward it |

## Knowledge gaps

Not every failure is a wording failure. If the skill does not know a publisher's
citation rule or an internal API's actual signature, no rephrasing fixes it: a
**fact** is missing, not a behaviour.

The loop detects those cases and does not invent the answer. It asks.

The hypothesis agent classifies each failure pattern in a three-step cascade —
was the rule already there and ignored (`EXECUTION_LAPSE`), would a perfect
instruction have been enough or is a fact required (`KNOWLEDGE_GAP`), otherwise
`SKILL_DEFECT`. Four mechanical markers separate fact from form: the failing
assertion checks a value rather than a shape, the agent asserted something
concrete that was wrong, the answers vary across runs, the agent searched and
found nothing. In genuine doubt it is never a knowledge gap — that branch is the
expensive one, it interrupts a human and creates maintenance.

A knowledge gap produces no mutation. It produces a question with four fields,
recorded in `knowledge-gaps.jsonl`, and the experiment ends as `DEFERRED`:

```
gap-003 [open]
Question:    Which citation style does publisher X require in running text?
Evidence:    3/4 train evals with in-text citations fail 'beleg_kurzform'
Useful answer: One rule, short or full citation, plus the exceptions
Backed by:   belege-fliesstext, belege-fussnote, belege-tabelle
```

`answer_shape` is not decoration. It is the difference between a question a human
answers in thirty seconds and one they dismiss.

**The auto mode does not block on it.** An overnight run cannot ask anyone.
Blocking would stall the loop; answering itself would invent facts. `DEFERRED` is
the third way: the question is asked and written down, and the loop keeps working
on wording and determinism. So the run delivers a better skill *and* a short list
of precise questions that take five minutes to answer in the morning.

Rules the script enforces, not the prompt: at least two train evals must show the
pattern (`eval_ids`, not a counter); one gap per experiment; a cap per run
(`max_deferred_per_run`, default 3) after which `knowledge` is deprioritized; no
question twice, and a rejected one stays blocked. A question already `answered`
whose failure pattern returns is not a knowledge gap — the knowledge is not
reaching the agent, which is a `SKILL_DEFECT`.

`DEFERRED` is filtered out of the plateau window rather than counted as a
non-KEEP. Counting it would end a run over unanswered questions although no
hypothesis failed; letting it break the streak would make one question every
three rounds suppress plateau detection entirely.

### The optimizer's own memory

Until v3 this was a file of eight bullets, rewritten from scratch every five
experiments. The cap kept the context small; the price was that every insight
fell out after two rounds at the latest, and at the end of a run nothing
remained for the next one to build on.

WikiSkill's ablation measures that difference: persistent optimizer-side
knowledge, refined across iterations, is worth **+15.0 points** on average
across four benchmarks (48.7% → 63.7%) — the single largest effect in their
paper.

The store is now uncapped. What makes that affordable is one separation:

> Only `patterns/INDEX.md` sits in the context. A page is read individually,
> with `patterns.py show`, when its title matches the question.

Twenty patterns cost under 1200 tokens permanently. That puts a demand on the
meta agent: **the title is the most important line of a page**, because it
decides whether the page is ever opened.

Two rules keep an uncapped store from turning into noise. **Evidence is
programmatic, interpretation is the agent's** — the orchestrator appends the
outcome from `decision.json`, since an agent that writes its own support count
is citing itself. And **mistakes stay readable**: a pattern contradicted by a
later experiment is marked `widerlegt` with the experiment that did it, not
deleted, so the same wrong turn is not rediscovered three rounds later.

### Why the skill looks like this

The optimized skill gets a `PURPOSE.md` beside its `SKILL.md`: one entry per
kept change, with the rejected attempts in the same category that preceded it.

```markdown
## exp-005 — examples — example_add — 2026-09-19

**Hypothese:** Example for edge case X added
**Score:** 0.7200 → 0.7900 (+0.0700)

Vorher verworfen in derselben Kategorie:
- exp-002 instruction_edit NEUTRAL (-0.0050) — rule reworded
- exp-004 instruction_edit NEUTRAL (+0.0100) — rule tightened
```

The same information lives in `history.json` and `rejected.jsonl` — but those
stay in the workspace. Once the skill is handed over, nobody can see why a
section exists or which more obvious version already failed. Each rejected
attempt is attributed exactly once, to the next kept change after it. The file
does not count against `token_budget`: the agent never reads it at runtime.

### What val and test cannot see

The three-way split protects against memorizing the test cases. It does not
protect against adapting to the one model and the one setup the run happened
under — train, val and test come from the same distribution and run under the
same model.

WikiSkill measures what that can produce: skills a smaller model had evolved
for itself dropped a stronger model on the same task from 50.5% to **18.1%**.
The cause was low-level workarounds for the smaller model's weaknesses that
held the stronger one back. The gate cannot see that damage — it measures
exactly the combination the workaround was built for.

Two countermeasures, neither touching the gate. The mutator must answer, before
every new rule: *would this rule still be right for a stronger model or a
different setup, or does it work around a limitation of the current one?* And
an optional `transfer_evals` set from a different context is scored twice —
baseline and final — and reported. **It decides nothing**, for the same reason
the test split decides nothing: what gets optimized against stops measuring
anything. val rising while transfer falls is the signature of a workaround, and
the report says so.

To be clear about the source: WikiSkill gates on a single `Dval`, not across
targets. Its transfer numbers are analysis, not a gatekeeper. Gating across
several targets would be its own design decision with its own cost (every round
measures n times) and is deliberately not built here.

### Two tracks

Knowledge does not fit the gate the rest of the loop runs on, for a fundamental
reason:

> Whether a wording is better is decided by measurement. Whether a fact is true
> is decided by its source. An eval score is not a truth criterion.

A properly sourced statement that happens to move nothing in the current eval
set is still true and belongs in the vault. An invented one that raises the
score does not. So the two are separated:

| | Track A — content | Track B — pointer |
|---|---|---|
| **What** | The claims in the vault | The rule in SKILL.md pointing at the vault |
| **Gatekeeper** | Provenance, leak, injection, secrets, near-duplicate | The normal gate: `decide`, KEEP/REVERT on val |
| **Decided by** | `knowledge.py`, and a human when in doubt | The composite score |

Track B is an ordinary mutation. It answers the measurable question — *does
pointing the agent at the vault help?* Track A answers the one a score cannot —
*is what it says true?*

### The vault

It lives with the **target skill**, not in the workspace: knowledge the skill
needs belongs to the skill and travels with it. In the workspace it would stay
behind with the optimizer, and the skill you hand over would know nothing again.

```
<target-skill>/
├── SKILL.md              ← + FORGE_KNOWLEDGE region (the pointer, ~4 lines)
└── knowledge/
    ├── INDEX.md          ← routing map. Small, permanently in context
    ├── SOURCES.md        ← register: id, title, date, SHA-256, trust, rights
    ├── sources/          ← copies of sources cleared for full text
    └── pages/<slug>.md   ← claims, read only on demand
```

Format and id prefixes are a subset of the SkillSafe knowledge vault (`C-nnnn`
claim, `S-nnnn` source) and stay compatible with it: a vault produced here can
later be ingested into a real one without rewriting. The concept is adopted, not
the code — SkillSafe is not a dependency.

### Five gates before every claim

All in `scripts/knowledge.py`, none as a bullet on a prompt checklist — for the
same reason `verify-regions` runs in Python: asking an agent that broke a rule
whether it kept the rule is circular.

| Gate | Checks | Why |
|---|---|---|
| **Provenance** | Registered source **and** a passage | A source without a passage is not a citation in a 300-page document, it is an assertion |
| **Leak** | 8-word windows against val and test evals | Otherwise the loop writes the expected answers in as "knowledge", val rises, and nothing generalizes |
| **Injection** | Imperatives aimed at the system | Sources are data, never instructions |
| **Secrets** | Credentials as a **value**, not as a word | The vault ships with the skill. The word "password" is fine, a token is not |
| **Near-duplicate** | Nearly the same statement, different content | Stops silently overwriting sourced knowledge |

The last one comes with an honest caveat: it is **not** semantic contradiction
detection and could not be. It catches "same entity, different number" and not
the subtle case. The exit is still right, because the alternative — a silent
overwrite — loses sourced knowledge without a trace. To really replace a claim,
pass `--supersedes C-nnnn`: the old one becomes `veraltet`, not deleted.

### Pruning suggests, it does not delete

`prune-suggest` lists claims never read across `knowledge_stale_experiments`
(default 20) experiments. The loop deletes nothing in auto mode, and the
command writes nothing.

The asymmetry: a claim wrongly kept costs a few tokens in a generously sized
budget. A claim wrongly deleted costs its source, its passage and the work of
acquiring it — and it is missing precisely when the rare case arrives that it
was taken in for. That is what a vault is maintained for.

Non-use is also a weak signal. It can mean the claim is superfluous. It can
equally mean the evals do not cover its topic, or the index does not surface
it — and deleting fixes neither. The report names all three readings so the
decision is an informed one.

### Maintenance

`knowledge.py verify` checks structure, provenance and source drift, with three
levels that are the actual content of the command: **errors** (a claim without a
registered source, a duplicate id — the vault is untrustworthy), **stale** (the
source is reachable and changed, so the claims describe a state that no longer
exists — nothing is updated automatically, because what changed in substance is
not an arithmetic problem), and **warnings** (a `verweis` source whose path is
missing on this machine — not verifiable, but not wrong; failing closed here
would turn every handed-over skill red on arrival).

### Two budgets

`INDEX.md` counts against the strict `token_budget` because it sits in context
on every run; the pages count against a separate `knowledge_budget` because they
are read only when the index points at them. With a single budget,
`artifact-stats` would trip after a handful of claims and force the orchestrator
into `forced_category: efficiency` — the loop would start pruning away the
knowledge it had just acquired.

### What is already in the vault is not a gap

A fact supplied at wizard time never went through the gap queue, so deduping by
question does not catch it. Without a further guard this loops: the hypothesis
agent reports a gap, the librarian finds the answer in the vault where it
already was, `claim-add` rejects it as a near-duplicate — a round burned, and
the real cause stays hidden.

Two layers prevent it. The vault **index sits in the agent context**, so the
hypothesis agent can see which topics are covered — that is the actual
decision. And `gap-append --skill` searches the vault and exits 3 when the
question is covered — the mechanical backstop.

The threshold is deliberately high, and the asymmetry is the design. A false
"covered" means the gap is never reported and the missing fact never acquired —
a permanent blind spot. A false "not covered" costs one round. The second error
is recoverable, the first is not.

### What a passing eval still proves

The agent reads the vault **in the train runs too**, which changes what the
results establish, in both directions. A *passing* train eval whose run read
claims does not show the skill is good — the fact may have come from the vault,
and such runs must not become `success_patterns`, the protection list that
stops the mutator from pruning. A *failing* eval whose run read the relevant
claim is not a knowledge gap — the knowledge was there and did not carry.

Neither case is distinguishable from its opposite without attribution, so
`usage-update` scans the transcripts for claim ids and page slugs after each
experiment. It is a lower bound, not a measurement: an agent that reads a page
and quotes nothing does not show up. For the two rules above that is enough.

WikiSkill ([arXiv:2608.27454](https://arxiv.org/abs/2608.27454)) measures that
giving the agent wiki access during training rollouts *lowers* final skill
quality, because the trajectories say less about the skill. But their wiki holds
*procedures* meant to be compiled into the skill; our vault holds *facts* the
agent needs at runtime and cannot derive — switching it off would make the train
runs unrealistic. So we adopt the consequence rather than the remedy: the
results have to know whether the vault helped.

Phases 1 and 2 are shipped, plus source drift, supersession and usage tracking
from phase 4. Still open: searching approved external sources, prune proposals,
and the upgrade path to a real SkillSafe vault — see `PLAN-wissen-v1.md`.

## Crash recovery

If an eval run crashes (timeout, script error, API failure):

1. Read the stack trace and classify the error
2. Script bug in target skill → score as 0 (mutation broke it)
3. Infrastructure error → retry once, then skip
4. Eval bug → exclude from scoring, log the issue
5. After 3 consecutive crashes → pause and report
6. Continue with next eval, one crash doesn't kill the run

If the process dies between mutation and decision, `checkpoint.json` carries
`applied_but_undecided: true` and the snapshot version that is currently on disk. A resume
reverts to `on_disk_version` first and reruns the experiment, instead of scoring a mutated
file against a baseline it no longer matches.

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `execution_mode` | auto | `auto` (fully autonomous) or `guided` (interactive with 5 checkpoints) |
| `mode` | auto | `skill`, `generic`, or `auto` (auto-detect) |
| `max_experiments` | 10 | Maximum experiment count |
| `improvement_threshold` | 0.02 | Minimum delta to keep |
| `regression_threshold` | 0.05 | Maximum delta before revert |
| `near_miss_band` | 0.02 | Band below the keep threshold that flags a NEUTRAL as `near_miss` |
| `noise_floor` | 0.0 | Measured run-to-run noise. The effective keep threshold is `max(improvement_threshold, noise_floor, resolution)` |
| `gate_weights` | unset | Gate score weights. **Leave it unset** to get 1.0/0.0, or 0.65/0.35 with `use_comparator`. A key that is present always wins, including over `use_comparator`: setting it to `{assertions: 1.0, judge: 0.0}` and enabling the comparator pays for judge runs and scores pure assertions |
| `workspace_path` | — | Absolute path to the workspace |
| `target_path` | — | Absolute path to the optimization target |
| `time_budget_minutes` | 120 | Time budget (for scheduled tasks) |
| `split_ratio` | 0.50/0.25/0.25 | train/val/test ratio (Skill Mode) |
| `split_seed` | 42 | Seed of the hash assignment. Changing it moves every eval and forces a re-baseline |
| `transfer_evals` | null | Optional second eval set from a different context. Measured twice and reported, never gated |
| `min_evals` | 6 | Below this the wizard refuses to start |
| `min_evals_for_test` | 12 | Below this there is no test split |
| `resolution` | (computed) | `2 / N_assertions`, a lower bound on the keep threshold |
| `use_comparator` | false | Enable blind A/B comparison |
| `metric_command` | — | Shell command returning a number (Generic Mode) |
| `metric_direction` | higher_is_better | `higher_is_better` or `lower_is_better` |
| `max_crashes` | 3 | Max consecutive crashes before pause |
| `min_support_count` | 2 | Train evals a failure pattern must appear in before it becomes a hypothesis |
| `appendix_max_notes` | 15 | Cap on the lapse notes in the protected region |
| `rejected_limit` | 10 | How many rejected attempts go into the next prompt |
| `token_budget` | (computed) | `max(2000, ceil(initial * 1.25))`, set by the wizard |
| `chars_per_token` | 3 | Divisor of the token estimate. 3 for German text |
| `protected_paths` | [] | Paths the loop must never change (generic mode, mandatory) |
| `invariant_command` | null | Must still exit 0 after every mutation |
| `min_scope_ratio` | 0.9 | Floor against "measuring less is not an improvement" |
| `max_scope_files` | 200 | Upper bound on the scope glob |
| `meta_memory_interval` | 5 | How often the meta agent runs |
| `pattern_min_support` | 2 | Measured evidence rows before a pattern stops being `vorläufig` |
| `max_knowledge_gaps_per_experiment` | 1 | How many knowledge gaps one round may report |
| `max_deferred_per_run` | 3 | How often a run may answer with a question instead of a mutation before `knowledge` is deprioritized |
| `gap_limit` | 10 | How many open questions go into the agent prompt |
| `knowledge_enabled` | true | Knowledge branch active; `false` disables `KNOWLEDGE_GAP` classification |
| `knowledge_inbox` | `<workspace>/knowledge-inbox` | Raw material supplied by the user |
| `knowledge_budget` | `4 × token_budget` | Cap on `knowledge/pages/`, separate from the strict budget |
| `vault_coverage_threshold` | 0.6 | Coverage at which `gap-append` rejects a question the vault already answers |
| `knowledge_stale_experiments` | 20 | Experiments without a read before a claim becomes a prune suggestion |

## Tests

```
python3 -m pytest tests/ -q
```

406 tests across thirteen files. They cover the decision cascade and its threshold edge cases,
gate scoring and `--side`, the three-way split, diff and comparison, protected regions and
the appendix, the rejected buffer, the token budget, the invariant checks, generic mode,
and every CLI exit code, plus the knowledge-gap queue, the `DEFERRED` path, and the five gates guarding the vault.

`test_review_findings.py` is the interesting one: it pins every defect the two adversarial
review rounds found in this code, plus the blind spots a mutation test over 69 targeted
code changes exposed. Among them a `revert` that deleted files outside its scope, a second
marker pair that bypassed region verification entirely, and a keep threshold that decided
two assertion flips by IEEE-754 rounding.

`pytest.ini` anchors the rootdir and `conftest.py` puts the repo root on `sys.path`, so the
suite runs from any working directory.

## Earlier runs (v2 rules, not reproducible from this repo)

Three skills were run through the v2 loop. Read the numbers as anecdotes, not as
measurements:

**humanizer** (text humanization): 3 experiments, composite score 0.74 → 0.90. Key fix:
personality as a dedicated workflow step with concrete criteria. A held-out test on an
unseen LinkedIn post confirmed the change generalized.

**fachbuch-lektorat** (German technical book editing): 3 experiments, assertion pass rate
87% → 100%. Key fix: a worked example for mixed wir/ich handling.

**was-bisher-geschah** (AI news briefing): 1 experiment, assertion pass rate 93% → 100%.
Key fix: LinkedIn character limit plus an explicit action prompt per news item.

Caveats, all of them mine:

1. **No artifacts.** This repository contains no `evals.json`, no `history.json`, no
   `experiment-log.tsv`, no `coverage-matrix.json`, and no snapshot for any of these runs.
   The only thing on file is the prose log in
   [`examples/fachbuch-lektorat-session.md`](examples/fachbuch-lektorat-session.md), and
   prose is not a measurement. Nobody, including me, can rerun these and check the numbers.
2. **Mixed metrics.** 0.74 → 0.90 is a composite score under the old weighting, which
   included efficiency at 0.20. 87% → 100% and 93% → 100% are raw assertion pass rates.
   Listing them together implies a comparability that is not there.
3. **Obsolete rules.** All three ran under the v2 decision cascade, in which the NEUTRAL
   branch was unreachable, and under the old gate weights that gave efficiency 0.20. The
   fachbuch log even records two "NEUTRAL-KEEP" verdicts, a label no version of the spec
   ever defined. Under the v3 cascade those two experiments roll back, so a rerun would
   not land on the same path.

From v3 on, results only go in this README with the `history.json` and `evals.json` of the
run attached, so that anyone can check the number against the log that produced it.

## License

MIT License, see [LICENSE](LICENSE).

## Acknowledgments

Inspired by [Andrej Karpathy's autoresearch](https://github.com/karpathy/autoresearch), an autonomous ML experiment loop where an AI agent modifies `train.py`, trains for 5 minutes, and keeps or discards changes based on validation loss. Skill Forge adapts this paradigm from LLM training code to natural-language skill instructions and generic codebases.

Copyright (c) 2026 Mark Zimmermann
