# Operational intake questionnaire

Runtime reference for the `project-osmos` skill's operational-intake step.

The intake classifies the task type, asks only relevant questions with task-type-aware defaults, then renders a `## Operational constraints` block appended verbatim before any API call.

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
  > `I'm treating this as a transformative ingest. Type "change" to pick a different task type, anything else to continue.`
- When in doubt, classify as **Unclear** and run the full questionnaire; the intake exists to prevent correctness loss from over-pruning questions.
- **Red-flag verbs that force `Unclear`** unless the description is
  unusually specific: `update`, `delete`, `fix`, `clean up`, `migrate`,
  `sync`, `merge`, `correct`. These verbs map to multiple task types
  and the user must disambiguate explicitly.

## Intake flow: recommendations card first

After classification, compute each relevant recommended answer from the matrix, render one CLI **summary card**, and offer four reply commands instead of asking questions one by one.

### Step 1 — render the recommendation card

Render the card inside a **fenced code block** (triple backticks, no language tag) so CLI markdown renderers keep plain monospace alignment and avoid bogus syntax coloring.

Use a **vertical, line-oriented layout**: each row has an answer line and a `Why:` line, and rows may include short follow-up guidance blocks such as the Question 1 warning. Never use a wide 4-column ASCII table that wraps badly below ~120 columns.

```
Based on your task description (<task type>), I recommend these settings.

Note: To change any recommended setting, reply with `change <N>`. To understand the options for a setting, reply with `explain <N>`.

 1. Permission boundary
    → <answer — multi-line if more than one resource>
    Why: <one-line plain-English justification>
    ⚠️ Model-only guidance, not a hard Fabric/OneLake system constraint.
    The agent will follow this permission boundary during the run.
    If a resource must not be mutated, enforce that with Fabric/OneLake permissions.

 2. Safety pattern
    → <answer | skipped>
    Why: <…>

 3. Promote step
    → <answer | skipped>
    Why: <…>

 4. Re-run semantics
    → <answer>
    Why: <…>

 5. Schema evolution
    → <answer | skipped>
    Why: <…>

 6. Artifact format
    → <answer>
    Why: <…>

 7. Artifact destination
    → <destination keyword only; ask for the concrete path only after accept/change 7>
    Why: <…>

 8. Reasoning effort
    → low
    Why: Low is selected by default for fastest execution; increase reasoning effort if you want the agent to spend more planning/search time on complex logic, risky writes, schema changes, or deeper validation.

Reply with one of:
  • accept         — start the run with these settings
  • change <N>     — edit one row (e.g. "change 4")
  • explain <N>    — see the other options for that row
  • walk through   — answer every question from scratch
```

**Rules for the card:**

- Use matrix recommendations; render skipped/`n/a` rows as `→ skipped` rather than omitting them so all 8 rows remain visible.
- The "Why:" line is required: one fresh plain-English sentence for the user's task, not the question's "What this means" subtitle.
- For Question 7 (artifact destination), render only the destination keyword (`workspace folder`, `lakehouse Files`, `both`, or `let the agent decide`) — **do not prompt for the folder path inline with the card.** After `accept` or `change 7 …`, check the resolved Q7 value:
  - If Q7 ∈ {`workspace folder`, `both`}: emit one standalone prompt asking only for the path (*"What folder in the workspace should the notebook be saved to? (e.g. `/notebooks/` or `ETL/notebooks/`)"*) and wait for the reply before starting the run.
  - If Q7 ∈ {`lakehouse Files`, `let the agent decide`}: no path prompt — start immediately.
  Never emit the folder-path question with the `accept / change / explain / walk through` reply list; the user cannot answer both at once.
- Permission boundary may be multi-line under `→` when the user named more than one resource (one sub-line per resource).
- Always include the three-line warning block directly under Question 1's
  `Why:` line, including when re-rendering the card after `change <N>` or
  `explain <N>`. The warning block starts with:
  `⚠️ Model-only guidance, not a hard Fabric/OneLake system constraint.`
- **Never use ANSI escape sequences** inside the card (`\033[…m`); raw `\033` characters leak through on some clients.

### Step 2 — handle the reply

| User reply | Skill behavior |
|---|---|
| `accept` | Compose the `## Operational constraints` preamble from the recommendations. **If the resolved Q7 is `workspace folder` or `both`, ask one standalone follow-up prompt for the folder path before starting the run; otherwise start immediately.** Never bundle the path question with the four reply commands. |
| `change <N>` | Re-ask question N using the verbose single-question rendering (subtitle + options + glosses), accept the user's pick, **re-show the summary card** with row N updated and marked `(changed)`, then offer the four commands again. |
| `explain <N>` | Render the option table for question N (see below), let the user pick `a/b/c/...` to change, or `cancel` to dismiss the table without changing the answer. After the pick, re-show the summary card. |
| `walk through` | Abandon the card; fall through to the legacy one-question-at-a-time flow (full questionnaire below). For power users, audits, or training. |
| anything else | Treat as a soft no-match: repeat the card and the four commands. Never auto-start. |

### Step 3 — `explain <N>` rendering

```
[Q4] Re-run semantics
   If you run the same task multiple times, what should happen subsequently?

   | Pick | Option                          | Plain English                              |
   |------|---------------------------------|--------------------------------------------|
   | a    | append w/ dedup ← recommended   | <gloss>                                    |
   | b    | append blindly                  | <gloss>                                    |
   | c    | fail if populated               | <gloss>                                    |
   | d    | truncate and reload             | <gloss>                                    |

   Reply with `a`, `b`, `c`, `d` to change the answer, or `cancel` to dismiss this table without changing anything.
```

The `Pick` letters are 0-indexed alphabetically across visible options in matrix-defined display order. The `← recommended` marker stays on the recommended option (which may not be `a`).

### Step 4 — marking changed rows

After a `change` or `explain` mutation, append literal `(changed)` to the row's `→ <answer>` line. Do **not** use ANSI color codes. Do not mark rows re-confirmed at their default; only active overrides.

### Ripple handling

When a change to one question changes which other questions apply (e.g., Question 2 from `clone-and-promote` to `staging table` means Question 3 is no longer asked):

- **Preserve** the user's overrides for any question that is still asked.
- **Remove** any override that becomes inapplicable; restore the matrix default for any newly-applicable question.
- **Re-render** the card so the user sees the cascade explicitly.
- **Never** silently start a run after a ripple — always offer the four reply commands again.

If the change is large enough that the task type itself flips (e.g., user adds a write target in Question 1 that turns Exploration into Additive), restart the card from scratch with the new classification and tell the user explicitly: *"That change reclassified this as Additive — here's the new recommendation set."*

## The questions

Canonical text for `change <N>`, `explain <N>`, and `walk through` mode. The "recommended" mark is the `Unclear` fallback; per-task-type overrides live in the matrix.

> **Rendering rule for the CLI:** in `change` or `walk through` mode, render the **subtitle line** ("What this means") above the options, and render each option label with its short gloss (text after the em-dash). Do not show bare option keys alone.

### Question 1. Per-resource permission *(asked once per named resource)*

**What this means:** For each thing you named (a table, folder, or
file), what is the agent allowed to do with it — only look at it, or
also change it?

> ⚠️ Model-only guidance, not a hard Fabric/OneLake system constraint.
> The agent will follow this permission boundary during the run, but if a
> resource must not be mutated, enforce that with Fabric/OneLake permissions.

| Option | Label shown to user | Notes |
|---|---|---|
| `read-only` ← recommended | **read-only** — agent can SELECT from it but cannot modify it. | Safe default. |
| `write` | **write** — agent can modify, append, overwrite, or create rows here. | Triggers Questions 2–5 for this resource. |

### Question 2. Safety pattern for writes *(only if any resource is `write`)*

**What this means:** The agent will iterate (write code, run, fix, run
again). Where should those in-progress attempts land so they don't
corrupt your real table?

| Option | Label shown to user | Notes |
|---|---|---|
| `let the agent decide` | **let the agent decide** — pick per resource based on what kind of write it is. | |
| `clone-and-promote` ← recommended | **clone-and-promote** — make a copy of the real table, iterate on the copy, swap to the real target only when it works. | Recommended for most production targets. |
| `staging table + manual promotion` | **staging table + manual promotion** — write to a new side table; you decide later when (and whether) to publish it to the real target. | Highest control, requires a manual follow-up. |
| `iterate in place` | **iterate in place** — write directly to the real target. Failed attempts leave partial/garbage rows in production. | Only use for throwaway tables. |

### Question 3. Promote step *(only if Question 2 = clone-and-promote)*

**What this means:** Once the agent's code works on the clone, how
should the verified result move from the clone onto the real table?

| Option | Label shown to user | Notes |
|---|---|---|
| `let the agent decide` | **let the agent decide** | |
| `re-run final code against real target` ← recommended | **re-run final code against real target** — throw away the clone, run the verified notebook/SQL one more time directly against the real target. Fresh data, proper lineage. | Recommended. |
| `data swap (INSERT OVERWRITE)` | **data swap (`INSERT OVERWRITE`)** — atomically replace the real target's contents with whatever is in the clone. Faster but no fresh-data guarantee. | |
| `atomic rename` | **atomic rename** — the clone becomes the real target; the old real target is renamed with a timestamp suffix as a backup. | |

### Question 4. Re-run semantics

**What this means:** If this same task is run a second time (later
today, tomorrow, after a fix), and the agent finds rows already in the
target table from a previous run, what should it do?

| Option | Label shown to user | Notes |
|---|---|---|
| `let the agent decide` | **let the agent decide** | |
| `fail if target already populated` ← recommended | **fail if target already populated** — hard stop with an error. Forces you to confirm the re-run intent explicitly. | Recommended. |
| `append (duplicates allowed)` | **append (duplicates allowed)** — just add more rows, don't check for duplicates. | Use only when duplicate rows are acceptable. |
| `append with dedup key` | **append with dedup key** — you name a key column (e.g., `INVOICE_ID`); agent removes existing rows that match before inserting. | Best for incremental loads. |
| `overwrite (truncate then write)` | **overwrite (truncate then write)** — delete everything in the target, then write. Destroys whatever was there. | Only for tables you fully own. |

### Question 5. Schema evolution on real targets *(only if any write)*

**What this means:** If the source data has new columns, missing
columns, or different types than the target, what should the agent do?
This controls how much the table's shape is allowed to drift.

| Option | Label shown to user | Notes |
|---|---|---|
| `let the agent decide` | **let the agent decide** | |
| `locked` ← recommended | **locked — schema must match exactly, fail on mismatch** — the real target's columns and types are the contract; any drift is a hard error. | Recommended for prod tables. |
| `auto-evolve (mergeSchema)` | **auto-evolve (`mergeSchema`)** — new columns from the source get added automatically. Risky if other consumers depend on the table's shape. | |
| `type-widening only` | **type-widening only** — allows safe widening (e.g., `int → long`) but blocks new columns and narrowing types. | Middle-ground. |

### Question 6. Artifact format

**What this means:** What kind of code artifact do you want saved at the
end so the work is reproducible?

| Option | Label shown to user | Notes |
|---|---|---|
| `let the agent decide` ← recommended | **let the agent decide** — usually a Fabric notebook capturing the steps. | Recommended. |
| `notebook always` | **notebook always** — always save a Fabric notebook. | |
| `don't save artifacts` | **don't save artifacts** — ephemeral, only chat messages preserved. | Skips Question 7. |

### Question 7. Artifact destination *(only if Question 6 ≠ "don't save")*

**What this means:** Where should the saved notebook live so
you can find it later?

| Option | Label shown to user | Notes |
|---|---|---|
| `let the agent decide` | **let the agent decide** | |
| `workspace folder` ← recommended | **workspace folder (user-specified path)** — saved into the Fabric workspace at a path you provide, e.g., `ETL/notebooks/`. | **Hard rule:** if the workspace publish fails, the task must fail loudly — no silent fallback to Lakehouse Files. |
| `lakehouse Files` | **lakehouse Files** — saved under `Files/<path>/` inside the lakehouse. | Useful when workspace publish isn't available. |
| `both` | **both** — workspace + Lakehouse mirror. Belt + suspenders. | |

### Question 8. Reasoning effort

**What this means:** How much planning/search budget should the orchestrator
spend before and during execution? Higher effort can improve complex or risky
work, but may cost more time.

| Option | Label shown to user | Notes |
|---|---|---|
| `low` ← default | **low** — fastest path; use minimal branching/search and straightforward validation. | Always pre-filled by default. |
| `medium` | **medium** — balanced planning/search with normal validation. | User can choose this for ordinary multi-step ingest/additive work. |
| `high` | **high** — spend extra planning/search budget, consider more alternatives, and validate more deeply before final writes. | User can choose this when complexity, ambiguity, write risk, schema risk, or rollback risk is high. |

### Reasoning effort escalation guidance

Question 8 always defaults to `low` in the recommendations card; do not auto-escalate by task type or complexity. The user may choose `medium` or `high`.

- Keep `low` for small or straightforward work: simple read-only analysis, a narrow single-file/table task, few transforms, no destructive writes, and low ambiguity.
- Choose `medium` when the user wants more budget for normal-complexity work: multiple steps, normal ingestion/transformation, moderate validation needs, or ordinary writes with standard safety settings.
- Choose `high` when the user wants more budget for complex or risky work: ambiguous requirements, many resources, non-trivial joins/cleaning, mutative writes, schema changes, difficult rollback/promotion, or strict validation requirements.

## Per-task-type recommendations matrix

Single source of truth for asked questions and pre-filled options. *skip* = not asked; *n/a* = logically inapplicable; *hide* = hidden because nothing will be re-run-protected.

| | Exploration | Transformative ingest | Additive | Mutative | Schema migration | Unclear |
|---|---|---|---|---|---|---|
| **Question 1** Permission | all `read-only` | source `read-only`, target `write` | target `write` | target `write` | target `write` | default `read-only`, user picks |
| **Question 2** Safety pattern | *skip* | `clone-and-promote` | *skip — additive doesn't iterate* | `clone-and-promote` | `staging table` | `clone-and-promote` |
| **Question 3** Promote step | *skip* | `re-run final code` | *skip* | `re-run final code` | *n/a — DDL is its own promotion* | `re-run final code` |
| **Question 4** Re-run semantics | *hide — n/a* | `fail if populated` | `append with dedup key` | `fail if populated` | `fail if populated` | `fail if populated` |
| **Question 5** Schema evolution | *skip* | `locked` | `locked` | `locked` | *n/a — schema IS the change* | `locked` |
| **Question 6** Artifact format | `don't save` | `notebook` | `notebook` | `notebook` | `notebook` | `let the agent decide` |
| **Question 7** Artifact destination | *skip* | `workspace folder` | `workspace folder` | `workspace folder` | `workspace folder` | `workspace folder` |
| **Question 8** Reasoning effort | `low` | `low` | `low` | `low` | `low` | `low` |

### Question count by task type

| Task type | Questions asked | Count |
|---|---|---|
| Exploration | Question 1, Question 6, Question 8 | 3 |
| Additive | Question 1, Question 4, Question 5, Question 6, Question 7, Question 8 | 6 |
| Schema migration | Question 1, Question 2, Question 4, Question 6, Question 7, Question 8 | 6 |
| Transformative ingest | Question 1, Question 2, Question 3, Question 4, Question 5, Question 6, Question 7, Question 8 | 8 |
| Mutative | Question 1, Question 2, Question 3, Question 4, Question 5, Question 6, Question 7, Question 8 | 8 |
| Unclear | Question 1, Question 2, Question 3, Question 4, Question 5, Question 6, Question 7, Question 8 | 8 |

## Skip rules within a task type

After matrix pruning, two runtime conditional skips still apply:

- If Question 2 ≠ `clone-and-promote`, skip Question 3.
- If Question 6 = `don't save artifacts`, skip Question 7.

## Rendered preamble template

After the questionnaire, prepend this **binding** block verbatim to the user's instruction before `PUT /{taskId}`; it overrides anything below it.

```text
## Operational constraints (binding — overrides anything below)
- Task type: <classified type>
- Per-resource permission:
  - <resource 1>: <read-only | write>
  - <resource 2>: <read-only | write>
- Safety pattern for writes: <answer | n/a>
- Promote step: <answer | n/a>
- Re-run semantics: <answer>
- Schema evolution: <answer | n/a>
- Artifact format: <answer>
- Artifact destination: <answer | n/a>
- Reasoning effort: <low | medium | high>
- Report all row counts and mutation counts as the literal output of `count()` / SQL — never paraphrased.
- If artifact destination is a workspace folder and publish fails, fail the task; do not silently fall back to Lakehouse Files.

## User outcome
<original instruction text, verbatim>
```

For skipped or *n/a* questions, render `n/a` instead of dropping the line so the audit trail stays complete and diffable.

`Reasoning effort` is the orchestrator-facing planning/search/MCTS-style budget hint:

- `low` — prefer the fastest direct plan, minimal branching, and basic validation suitable for simple read-only or low-risk work.
- `medium` — user-selected balanced planning/search and normal validation.
- `high` — user-selected extra effort for alternatives, rollback/safety implications, or deeper validation.

## Example renders

### Exploration

User: "Profile the Invoice table. Show me row count, null counts per column, and the top 5 invoice amounts."

```text
## Operational constraints (binding — overrides anything below)
- Task type: Exploration
- Per-resource permission:
  - Invoice (table): read-only
- Safety pattern for writes: n/a
- Promote step: n/a
- Re-run semantics: n/a
- Schema evolution: n/a
- Artifact format: don't save artifacts
- Artifact destination: n/a
- Reasoning effort: low
- Report all row counts and mutation counts as the literal output of `count()` / SQL — never paraphrased.
- If artifact destination is a workspace folder and publish fails, fail the task; do not silently fall back to Lakehouse Files.

## User outcome
Profile the Invoice table. Show me row count, null counts per column, and the top 5 invoice amounts.
```

### Transformative ingest (the 5/3 invoice scenario, re-run with the intake)

User: "In `naresh_daily_lh2` there is a folder called `Invoice` with invoice files and a table called `Invoice` for the final schema. Write a notebook to ingest the invoices into the Invoice table. Save the notebook in `ETL/notebooks/` as `05-03-DataProject-invoice-processing`."

```text
## Operational constraints (binding — overrides anything below)
- Task type: Transformative ingest
- Per-resource permission:
  - Invoice (folder): read-only
  - Invoice (table): write
- Safety pattern for writes: clone-and-promote
- Promote step: re-run final code against real target
- Re-run semantics: fail if target already populated
- Schema evolution: locked
- Artifact format: notebook
- Artifact destination: workspace folder → ETL/notebooks/
- Reasoning effort: low
- Report all row counts and mutation counts as the literal output of `count()` / SQL — never paraphrased.
- If artifact destination is a workspace folder and publish fails, fail the task; do not silently fall back to Lakehouse Files.

## User outcome
In naresh_daily_lh2 there is a folder called Invoice with invoice files and a table called Invoice for the final schema. Write a notebook to ingest the invoices into the Invoice table. Save the notebook in ETL/notebooks/ as 05-03-DataProject-invoice-processing.
```
