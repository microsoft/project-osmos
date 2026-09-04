# Operational intake questionnaire

Runtime reference for the `project-osmos` skill's operational-intake step.

The intake classifies the task, extracts explicit requirements, asks only for unresolved decisions, validates the resulting plan, then renders the verbatim `## User outcome` followed by a self-contained `## Execution plan` before any API call.

## Task types

Classify every task into exactly one type before asking questions.

| Task type | What it looks like | Example phrasing |
|---|---|---|
| **Exploration** | Read-only profiling, counting, sampling, summarising. | "Profile this table", "show me top 10 customers", "what's in this folder" |
| **Transformative ingest** | Read source(s), parse/transform, write to a target. | "Read invoice files, parse, write to the Invoice table" |
| **Additive** | Insert specific known rows into an existing target. | "Add these 5 rows", "load this CSV into the table as new rows" |
| **Mutative** | UPDATE / DELETE on existing rows in a target. | "Mark all 2024 invoices as paid", "delete rows where status=cancelled" |
| **Schema migration** | DDL on a target — add/drop column, change type, rename. | "Add a `region` column to the Invoice table" |
| **Unclear** | Description doesn't fit any of the above with confidence. | Vague verbs without enough detail. |

### Classification rules

- The CLI must announce the inferred task type before asking any
  question, in a single line:
  > `I'm treating this as a transformative ingest. Reply "continue" to use that classification or "change" to pick a different task type.`
- Advance only on explicit `continue`. On `change`, show the six task types and
  wait for a selection. Repeat the classification prompt for any other reply;
  never interpret a question, blank reply, or unrelated text as approval.
- When in doubt, classify as **Unclear** and run the full questionnaire; the intake exists to prevent correctness loss from over-pruning questions.
- **Red-flag verbs that force `Unclear`** when the affected resource, operation,
  or intended result is missing: `update`, `delete`, `fix`, `clean up`,
  `migrate`, `sync`, `merge`, `correct`. A specific instruction such as
  "delete rows where status=cancelled from Claims" remains **Mutative**.

## Derive requirements before applying defaults

The recommendations card is not a static projection of the task type. Before
rendering it, extract all explicit decisions from the user's outcome and any
resolved Fabric context:

- named resources, each resource's role, and whether it is a source,
  intermediate target, or final target;
- whether each write target is missing, existing-empty, existing-nonempty, or
  unknown when that state can be discovered read-only;
- explicit rerun language such as `rerun`, `run again`, `idempotent`,
  `counts unchanged`, `append`, `incremental`, `replace`, or `overwrite`;
- named keys, partitions, source globs, date ranges, or other scope boundaries;
- requested review, approval, validation, or manual-promotion gates;
- requested task display name, artifact format, artifact name, and destination
  path; keep the task display name distinct from the artifact name;
- destructive-write limits such as expected affected rows or a maximum
  mutation count.

Resolve every recommendation in this order:

1. **Explicit user requirement.** Preserve it verbatim and mark the row
   `(from your request)`.
2. **Discovered resource fact.** Use read-only metadata such as target
   existence to remove impossible choices.
3. **Task-type fallback.** Use the matrix only when the outcome and resource
   facts do not decide the setting.

Never let a task-type fallback override an explicit user requirement. If two
explicit requirements conflict, leave the setting unresolved and handle it in
the pre-dispatch reconciliation step.

## Intake flow: recommendations card first

After classification, compute each relevant recommendation using the derivation
order above, render one CLI **summary card**, and show one four-choice action
menu instead of asking questions one by one.

### Step 1 — render the recommendation card

Render the card inside a **fenced code block** (triple backticks, no language tag) so CLI markdown renderers keep plain monospace alignment and avoid bogus syntax coloring.

Use a **vertical, line-oriented layout**: each row has an answer line and a `Why:` line, and rows may include short follow-up guidance blocks such as the Question 1 warning. Never use a wide 4-column ASCII table that wraps badly below ~120 columns.

```
Based on your task description and explicit requirements (<task type>), I recommend these settings.

 1. Permission boundary
    → <answer — multi-line if more than one resource>
    Why: <one-line plain-English justification>
    ⚠️ Model-only guidance, not a hard Fabric/OneLake system constraint.
    The agent will follow this permission boundary during the run.
    If a resource must not be mutated, enforce that with Fabric/OneLake permissions.

 2. Safety pattern
    → <one sub-line per write target | skipped>
    Why: <…>

 3. Promote step
    → <one sub-line per applicable write target | skipped>
    Why: <…>

 4. Re-run semantics
    → <one sub-line per write target | skipped>
    Why: <…>

 5. Schema evolution
    → <one sub-line per write target | skipped>
    Why: <…>

 6. Artifact format
    → <answer>
    Why: <…>

 7. Artifact destination
    → <destination keyword and extracted path, when supplied>
    Why: <…>

 8. Reasoning effort
    → <explicit user choice, otherwise medium>
    Why: Medium is the standard balanced default; change it only when the user explicitly chooses another level.

```

**Rules for the card:**

- Use the derivation order above. The matrix supplies fallbacks only. Render
  skipped/`n/a` rows as `→ skipped` rather than omitting them so all 8 rows
  remain visible.
- The "Why:" line is required: one fresh plain-English sentence for the user's task, not the question's "What this means" subtitle.
- For Question 7 (artifact destination), extract and render a path already
  supplied by the user. After `accept` or `change 7 …`, check the resolved Q7:
  - If Q7 ∈ {`workspace folder`, `both`} and no path was supplied: emit one
    standalone prompt asking only for the path (*"What folder in the workspace
    should the notebook be saved to? (e.g. `/notebooks/` or
    `ETL/notebooks/`)"*) and wait before starting the run.
  - If Q7 ∈ {`lakehouse Files`, `let the agent decide`}: no path prompt — start immediately.
  Never emit the folder-path question with the `accept / change / explain / walk through` reply list; the user cannot answer both at once.
- Questions 1–5 may be multi-line under `→` when more than one resource or
  write target exists. Give every sub-line a stable suffix (`1a`, `1b`, `2a`,
  `2b`, ...) and accept scoped changes such as `change 2a`; bare `change 2`
  re-runs every Question 2 sub-line.
- Always include the three-line warning block directly under Question 1's
  `Why:` line, including when re-rendering the card after `change <N>` or
  `explain <N>`. The warning block starts with:
  `⚠️ Model-only guidance, not a hard Fabric/OneLake system constraint.`
- **Never use ANSI escape sequences** inside the card (`\033[…m`); raw `\033` characters leak through on some clients.
- Immediately after the card, use `ask_user` with exactly these four visible
  choices:
  1. **Accept recommendations**
  2. **Change a setting**
  3. **Explain a setting**
  4. **Walk through every question**
- Do not enumerate `change 1` through `change 8` or `explain 1` through
  `explain 8` in the action menu. That produces an overwhelming 18-item list.
- If the user selects **Change a setting** or **Explain a setting**, issue one
  second `ask_user` prompt listing only the eight numbered setting names. If a
  row has per-target sub-lines, select the row first, then ask which target.
- Freeform commands such as `change 4`, `change 2a`, `explain 4`, `accept`, and
  `walk through` remain supported when the user types them directly instead of
  using the menu.

### Step 2 — handle the reply

| User action | Skill behavior |
|---|---|
| **Accept recommendations** or typed `accept` | Resolve required dependent values, run pre-dispatch reconciliation, then compose the user outcome followed by the `## Execution plan`. Start only when no value or conflict remains unresolved. |
| **Change a setting** or typed `change <N>` / `change <N><suffix>` | Ask for the setting number only if it was not typed, then re-ask the question or scoped sub-line. Re-show the summary card with the changed row marked `(changed)`, followed by the same four-choice action menu. |
| **Explain a setting** or typed `explain <N>` | Ask for the setting number only if it was not typed, then render that option table. Let the user select an option or cancel. Re-show the card and four-choice action menu. |
| **Walk through every question** or typed `walk through` | Abandon the card and use the one-question-at-a-time flow. |
| anything else | Treat as a soft no-match: repeat the card and the four-choice action menu. Never auto-start. |

**Accept recommendations** or typed `accept` is the user's final authorization
to create and start exactly one Osmos task after reconciliation succeeds. Do
not display another confirmation such as **Accept and create the task** /
**Do not create the task**, and do not ask the user to accept the compiled
handoff again. The recommendation card is the review-and-consent surface.

### Step 2b — resolve dependent values and reconcile before dispatch

After `accept`, collect only values required by the resolved choices:

- For `append with dedup key` or `reconcile idempotently`, collect one or more
  stable key columns or a partition scope for each applicable target. Do not
  dispatch with an unresolved key.
- For a workspace artifact, collect the destination path only when it was not
  already extracted from the outcome.
- When an artifact was explicitly named, preserve that name. Otherwise state
  `agent's choice`; do not silently drop the name.
- For a mutative task, use a supplied expected affected-row count or mutation
  cap. If neither is supplied and the task is broad or ambiguous, ask for a
  limit before dispatch.
- For folder or multi-file ingest, preserve a supplied glob/date boundary. If
  the source scope is ambiguous, ask which files are in scope.

Then compare the complete plan with the original outcome. At minimum, detect:

| Outcome signal | Incompatible setting |
|---|---|
| `rerun`, `run again`, `counts unchanged`, `idempotent`, `safe to re-run` | `fail if target already populated` or `append (duplicates allowed)` |
| `append`, `incremental`, `new rows` | `overwrite (truncate then write)` |
| `replace`, `full refresh`, `rebuild` | append-only semantics |
| `review`, `approve`, `before publishing`, `let me validate` | `Approval gates: none` |
| a write, delete, update, or schema change | every named resource is `read-only` |
| a missing target | clone-only or locked-existing-schema behavior |

When a conflict exists, do not use precedence and do not dispatch. Show one
targeted question that quotes both conflicting requirements and asks the user
to choose. Re-run reconciliation after the answer. If the user cannot resolve
the conflict, fail task creation locally with the conflict named; never hand an
ambiguous contract to Osmos.

### Step 3 — `explain <N>` rendering

```
[Q4] Re-run semantics
   If you run the same task multiple times, what should happen subsequently?

   | Pick | Option                         | Plain English |
   |------|--------------------------------|---------------|
   | a    | <canonical option 1>           | <canonical executable meaning> |
   | b    | <canonical option 2>           | <canonical executable meaning> |
   | ...  | ...                            | ... |

   Reply with the displayed letter to change the answer, or `cancel` to dismiss this table without changing anything.
```

Generate this table directly from the canonical option table for the question;
never maintain a second hand-written option list. The `Pick` letters start at
`a` and proceed alphabetically across visible options in canonical display
order. The `← recommended` marker stays on the derived recommendation (which
may not be `a`).

### Step 4 — marking changed rows

After a `change` or `explain` mutation, append literal `(changed)` to the row's `→ <answer>` line. Do **not** use ANSI color codes. Do not mark rows re-confirmed at their default; only active overrides.

### Ripple handling

When a change to one question changes which other questions apply (e.g.,
Question 2 from `clone-and-promote` to `staging table + manual promotion`
means Question 3 is no longer asked):

- **Preserve** the user's overrides for any question that is still asked.
- **Remove** any override that becomes inapplicable; re-run dynamic derivation
  for any newly applicable question.
- **Re-render** the card so the user sees the cascade explicitly.
- **Never** silently start a run after a ripple — always offer the four reply commands again.

If the change is large enough that the task type itself flips (e.g., user adds a write target in Question 1 that turns Exploration into Additive), restart the card from scratch with the new classification and tell the user explicitly: *"That change reclassified this as Additive — here's the new recommendation set."*

## The questions

Canonical text for `change <N>`, `explain <N>`, and `walk through` mode.
The `recommended` marker is applied after dynamic derivation; the table order
does not change based on which option is recommended.

> **Rendering rule for the CLI:** in `change` or `walk through` mode, render
> the **subtitle line** ("What this means") above the options, and render each
> option label with its short gloss (text after the em-dash). That gloss is the
> option's executable meaning. Serialize it into the handoff; never send a bare
> option key and assume Osmos can read this questionnaire.

### Question 1. Per-resource permission *(asked once per named resource)*

**What this means:** For each thing you named (a table, folder, or
file), what is the agent allowed to do with it — only look at it, or
also change it?

> ⚠️ Model-only guidance, not a hard Fabric/OneLake system constraint.
> The agent will follow this permission boundary during the run, but if a
> resource must not be mutated, enforce that with Fabric/OneLake permissions.

| Option | Label shown to user | Notes |
|---|---|---|
| `read-only` | **read-only** — agent can SELECT from it but cannot modify it. | Safe fallback when no write is requested. |
| `write` | **write** — agent can modify, append, overwrite, or create rows here. | Triggers Questions 2–5 for this resource. |

### Question 2. Safety pattern for writes *(once per write target)*

**What this means:** The agent will iterate (write code, run, fix, run
again). Where should those in-progress attempts land so they don't
corrupt your real table?

| Option | Label shown to user | Notes |
|---|---|---|
| `let the agent decide` | **let the agent decide** — pick per resource based on what kind of write it is. | |
| `staged create-and-promote` | **staged create-and-promote** — build and validate a candidate, then atomically create the missing target from that candidate. | Use when the target does not yet exist. No human approval unless explicitly requested. |
| `clone-and-promote` | **clone-and-promote** — clone an existing target, iterate on the clone, retain it until the selected promote step succeeds, and then promote it. | Only valid for an existing target. The promote step determines whether the final mutation is atomic. |
| `staging table + manual promotion` | **staging table + manual promotion** — write and validate a side table, stop before changing the real target, and wait for the user's explicit approval to promote. | Creates a real approval gate. |
| `iterate in place` | **iterate in place** — write directly to the real target. Failed attempts leave partial/garbage rows in production. | Only use for throwaway tables. |

### Question 3. Promote step *(only for staged create-and-promote or clone-and-promote)*

**What this means:** Once the agent's code works on the candidate or clone, how
should the verified result become the real table?

| Option | Label shown to user | Notes |
|---|---|---|
| `let the agent decide` | **let the agent decide** | |
| `re-run final code against real target` | **re-run final code against real target** — retain the clone as evidence, then run the validated code against the real target. This final production write is not atomic and does not require human approval unless a gate is listed separately. | Use only when atomic promotion is unavailable or fresh-data execution is required. |
| `data swap (INSERT OVERWRITE)` | **data swap (`INSERT OVERWRITE`)** — atomically replace the real target's contents with whatever is in the clone. Faster but no fresh-data guarantee. | |
| `atomic rename` | **atomic rename** — the candidate or clone becomes the real target; an existing real target is renamed with a timestamp suffix as a retained backup. | Safe fallback when supported. |

### Question 4. Re-run semantics

**What this means:** If this same task is run a second time (later
today, tomorrow, after a fix), and the agent finds rows already in the
target table from a previous run, what should it do?

| Option | Label shown to user | Notes |
|---|---|---|
| `let the agent decide` | **let the agent decide** | |
| `fail if target already populated` | **fail if target already populated** — before any mutation, fail if the target already contains rows. This is a terminal safety policy, not a request for approval, and a confirmation message does not override it. | Safe when a second successful run is not required. |
| `append (duplicates allowed)` | **append (duplicates allowed)** — just add more rows, don't check for duplicates. | Use only when duplicate rows are acceptable. |
| `append with dedup key` | **append with dedup key** — for each target, use the supplied key columns to atomically replace matching rows and insert new rows. | Requires one or more stable keys per target. |
| `reconcile idempotently` | **reconcile idempotently** — use the supplied key or partition scope so rerunning with the same inputs leaves target contents and counts unchanged. | Required when the outcome asks for idempotent or unchanged-count reruns. |
| `verify desired state` | **verify desired state** — if the requested row mutation or schema change is already applied, report zero mutations and succeed; otherwise apply it once. | Default for Mutative and Schema migration tasks. |
| `overwrite (truncate then write)` | **overwrite (truncate then write)** — delete everything in the target, then write. Destroys whatever was there. | Only for tables you fully own. |

### Question 5. Schema evolution on real targets *(once per write target)*

**What this means:** If the source data has new columns, missing
columns, or different types than the target, what should the agent do?
This controls how much the table's shape is allowed to drift.

| Option | Label shown to user | Notes |
|---|---|---|
| `let the agent decide` | **let the agent decide** | |
| `locked` | **locked — schema must match exactly, fail on mismatch** — for an existing target, its columns and types are the contract; for a missing target, establish the explicitly requested or source-derived first schema and lock later writes to it. | Safe fallback for production tables. |
| `auto-evolve (mergeSchema)` | **auto-evolve (`mergeSchema`)** — new columns from the source get added automatically. Risky if other consumers depend on the table's shape. | |
| `type-widening only` | **type-widening only** — allows safe widening (e.g., `int → long`) but blocks new columns and narrowing types. | Middle-ground. |

### Question 6. Artifact format

**What this means:** What kind of code artifact do you want saved at the
end so the work is reproducible?

| Option | Label shown to user | Notes |
|---|---|---|
| `let the agent decide` | **let the agent decide** — usually a Fabric notebook capturing the steps. | Used only when the outcome and task type do not decide the format. |
| `notebook always` | **notebook always** — always save a Fabric notebook. | |
| `don't save artifacts` | **don't save artifacts** — ephemeral, only chat messages preserved. | Skips Question 7. |

### Question 7. Artifact destination *(only if Question 6 ≠ "don't save")*

**What this means:** Where should the saved notebook live so
you can find it later?

| Option | Label shown to user | Notes |
|---|---|---|
| `let the agent decide` | **let the agent decide** | |
| `workspace folder` | **workspace folder (user-specified path)** — saved into the Fabric workspace at a path you provide, e.g., `ETL/notebooks/`. | **Hard rule:** if the workspace publish fails, the task must fail loudly — no silent fallback to Lakehouse Files. |
| `lakehouse Files` | **lakehouse Files** — saved under `Files/<path>/` inside the lakehouse. | Useful when workspace publish isn't available. |
| `both` | **both** — workspace + Lakehouse mirror. Belt + suspenders. | |

### Question 8. Reasoning effort

**What this means:** How much planning/search budget should the orchestrator
spend before and during execution? Higher effort can improve complex or risky
work, but may cost more time.

| Option | Label shown to user | Notes |
|---|---|---|
| `low` | **low** — fastest path; minimal exploration and straightforward validation. | User can choose this for simple read-only or low-risk work. |
| `medium` | **medium** — balanced budget with normal validation. | Always recommend this unless the user explicitly chooses another level. |
| `high` | **high** — extra budget; the agent runs more experiments and considers more alternatives, validating more deeply before final writes. | User can choose this when complexity, ambiguity, write risk, schema risk, or rollback risk is high. |
| `xhigh` (aliases: `max`, `extra high`, `ultra`) | **xhigh** — maximum budget; the agent runs many experiments across planning and validation, revisiting steps and comparing results to converge on the best outcome. Slowest and most thorough. | User can choose this for the hardest, riskiest, or most ambiguous work, where quality matters more than time or cost. |

### Reasoning effort default

Always recommend `medium` when the user has not explicitly selected a
reasoning-effort level. Do not infer `low`, `high`, or `xhigh` from task
complexity, ambiguity, write risk, schema risk, or number of targets. Preserve
an explicit user choice and allow the user to override `medium` from the card.

## Dynamic recommendation rules

The task-type matrix is a fallback for unanswered decisions, not the source of
truth for the final plan. Apply these higher-priority rules first:

| Signal or discovered fact | Derived recommendation |
|---|---|
| Target is missing | `staged create-and-promote`; schema establishes an explicit first version |
| Target exists and the write replaces or mutates data | `clone-and-promote` with `atomic rename` when supported |
| Outcome says `rerun`, `idempotent`, or `counts unchanged` | `reconcile idempotently`; collect key or partition scope |
| Outcome says `append` or `incremental` | `append with dedup key`; collect key columns |
| Outcome says `replace`, `rebuild`, or `full refresh` | `overwrite` with staged or cloned atomic promotion |
| Outcome says `review`, `approve`, or `before publishing` | `staging table + manual promotion`; declare one explicit approval gate |
| Mutative or schema change | `verify desired state` |
| Explicit artifact path or name | preserve it; do not ask again |

### Fallback matrix

Use this table only for values still unresolved after applying explicit
requirements and discovered facts. *skip* means the question is inapplicable.

| | Exploration | Transformative ingest | Additive | Mutative | Schema migration | Unclear |
|---|---|---|---|---|---|---|
| **Question 1** Permission | all `read-only` | source `read-only`, targets `write` | targets `write` | targets `write` | targets `write` | default `read-only`, user picks |
| **Question 2** Safety pattern | *skip* | derive per target state | derive per target state | `clone-and-promote` | `clone-and-promote` | derive per target state |
| **Question 3** Promote step | *skip* | `atomic rename` for cloned targets | `atomic rename` for cloned targets | `atomic rename` | `atomic rename` | `atomic rename` for cloned targets |
| **Question 4** Re-run semantics | *skip* | `fail if target already populated` | `append with dedup key` | `verify desired state` | `verify desired state` | ask |
| **Question 5** Schema evolution | *skip* | `locked` | `locked` | `locked` | *n/a — schema is the requested change* | `locked` |
| **Question 6** Artifact format | `don't save artifacts` | `notebook always` | `notebook always` | `notebook always` | `notebook always` | `let the agent decide` |
| **Question 7** Artifact destination | *skip* | `workspace folder` | `workspace folder` | `workspace folder` | `workspace folder` | `workspace folder` |
| **Question 8** Reasoning effort | `medium` | `medium` | `medium` | `medium` | `medium` | `medium` |

## Skip and dependency rules

- Ask Questions 2, 4, and 5 once per write target.
- Ask Question 3 only for a target whose Question 2 answer is
  `staged create-and-promote` or `clone-and-promote`.
- Skip Question 4 for a task with no write target.
- If Question 6 is `don't save artifacts`, skip Question 7.
- `append with dedup key` and `reconcile idempotently` remain unresolved until
  their per-target keys or partition scopes are collected.
- For Questions 2–5, `let the agent decide` delegates the choice to the intake
  compiler, not to the remote run. Resolve it to a concrete per-target option
  and show the resolved value before `accept`; never serialize `let the agent
  decide` for write behavior.
- `staging table + manual promotion` creates an approval gate; no other option
  creates a gate merely because it is cautious or can fail.

## Compact handoff contract

The service accepts at most **10,000 characters** in `instruction`. Target
**9,500 characters or fewer** to preserve error-message and serialization
headroom.

Preserve the user's complete outcome verbatim. The generated execution-plan
block is subordinate to that character budget:

1. Measure the user outcome first.
2. Reserve its full character count plus the `## User outcome` heading.
3. Keep the generated operational block to at most **2,500 characters**, or
   the smaller remaining amount needed to keep the final instruction at or
   below 9,500 characters.
4. Before `PUT /{taskId}`, write the final instruction to a temporary file and
   run `python3 skills/project-osmos/scripts/check-instruction-length.py
   --path <file> --limit 9500`.
5. If it does not fit, remove generated verbosity—not user text. If the
   complete handoff still exceeds 9,500 characters, use the
   [oversized instruction fallback](oversized-instructions.md). Upload the
   exact complete handoff to the selected Lakehouse and submit only its
   lossless bootstrap reference. Never paraphrase, truncate, or ask the user
   to shorten the outcome.

The remote handoff is **not** a copy of the questionnaire. Include only:

- selected answers that affect execution;
- the concise executable behavior of each selected answer;
- required parameters such as keys, scopes, paths, limits, and gates;
- exact failure behavior where ambiguity would be unsafe.

Do not include unselected options, card `Why:` text, general risk education,
question subtitles, repeated warnings, or `n/a` fields. Those remain in
`intake.answers` and the dashboard audit state. Define shared rules once rather
than repeating them for every resource.

Use this compact shape:

```text
## User outcome
<original instruction text, verbatim>

## Execution plan
Task: name=<name>; type=<type>; mode=autonomous; gates=<none|explicit gate>; effort=<level>
Resources:
- <resource>: <source|intermediate|final>, <read-only|write>, state=<state>[, scope=<scope>]
Writes:
- <target>: safety=<choice> (<concise behavior>); promote=<choice> (<concise behavior>); rerun=<choice> (<exact populated-target behavior>, key/scope=<value>); schema=<choice> (<concise behavior>); approval=<none|gate>; cap=<value if applicable>
Artifact: <format>; name=<name|agent choice>; destination=<destination>; publish failure=fail, no fallback
Counts: report literal count()/SQL outputs.
Ambiguity: fail once naming the conflict and required input; never repeat a question.
```

Omit the `Writes`, `Artifact`, `Counts`, gate, scope, or cap clauses when they
do not apply. Keep one resource or target to one line. A label without its
selected behavior remains invalid, but a concise behavior clause is enough;
do not paste the full questionnaire definition.

### Compact Guidewire example

Assume read-only discovery confirmed both targets are missing and the user
confirmed `claim_id` as the stable identifier:

```text
## User outcome
<original instruction text, verbatim>

## Execution plan
Task: name=Attempt#1-Guidewire Claims only; type=Transformative ingest; mode=autonomous; gates=none; effort=medium
Resources:
- Files/guidewire/claimcenter/Claim.csv: source, read-only, state=existing, scope=exact file
- bronze_guidewire_claim: intermediate, write, state=missing
- gold_claim_starter: final, write, state=missing
Writes:
- bronze_guidewire_claim: safety=staged create-and-promote (validate candidate, then atomically create); promote=atomic rename (retain old target as backup if present); rerun=reconcile idempotently (same input leaves data/count unchanged, key=claim_id); schema=locked (establish first schema, reject later drift); approval=none
- gold_claim_starter: safety=staged create-and-promote (validate candidate, then atomically create); promote=atomic rename (retain old target as backup if present); rerun=reconcile idempotently (same input leaves data/count unchanged, key=claim_id); schema=locked (establish first schema, reject later drift); approval=none
Artifact: notebook; name=agent choice; destination=workspace:ClaimsTeam/notebooks/guidewire-claims; publish failure=fail, no fallback
Counts: report literal count()/SQL outputs.
Ambiguity: fail once naming the conflict and required input; never repeat a question.
```
