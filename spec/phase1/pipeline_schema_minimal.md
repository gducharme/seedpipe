# Phase 1 Minimal Pipeline Spec Schema (v0)

Goal: a **tiny** `pipeline.yaml` that can run end-to-end deterministically.
No branching, no retries, no parallelism. Just an ordered list of stages.

## Design constraints
- **Ordered stages only** (linear).
- Each stage declares **inputs** and **outputs** as **artifact names** (strings).
- Each stage declares an **execution mode**:
  - `whole_run` = stage runs once for the run
  - `per_item` = stage runs once per item (item = the generic unit)
  - `human_required` = runner emits a task packet and waits for manual completion proof before continuing
- Determinism policy exists at pipeline level; **defaults to strict**.
- Optional dependencies are allowed as **soft requirements** (for future integrations), but must not change semantics when absent.

---

## Minimal schema (v0)

### Top-level fields
- `pipeline_id` *(string, required)*
  Stable identifier for the pipeline.

- `item_unit` *(string, required)*
  Name for the generic unit of work (e.g., `item`, `record`, `doc`). Purely semantic; execution semantics come from `mode`.

- `determinism` *(object, optional; default `{ policy: strict }`)*
  - `policy` *(enum: `strict` | `best_effort`, optional; default `strict`)*
    `strict`: must enforce invariants like deterministic ordering, stable hashing inputs, no hidden ambient inputs.
    `best_effort`: allows explicitly documented nondeterminism (still discouraged in Phase 1).

- `dependencies` *(list, optional; default `[]`)*
  Optional dependencies that may be used by the runner or stages, but must not be required for correctness unless explicitly enforced elsewhere.
  Each entry:
  - `id` *(string, required)*
  - `optional` *(bool, optional; default `true`)*
  - `notes` *(string, optional)*

- `stages` *(list, required; non-empty)*
  Ordered list of stage objects.

### Stage object
- `id` *(string, required)*
  Unique within `stages`.

- `mode` *(enum: `whole_run` | `per_item` | `human_required`, required)*

- `inputs` *(list[string], optional; default `[]`)*
  Artifact names required to run this stage.

- `outputs` *(list[string], required; non-empty)*
  Artifact names produced by this stage.

- `placeholder` *(bool, optional; default `false`)*
  When `true`, the stage is a documented no-op placeholder. It bypasses forward-input dependency checks and does not execute any implementation code.

- `instructions` *(object, required when `mode=human_required`)*
  Manual task packet metadata for human-gated stages.
  Required fields:
  - `summary` *(string)*
  - `steps` *(list[string], non-empty)*
  - `done_when` *(list[string], non-empty)*
  Optional fields:
  - `troubleshooting` *(list[string])*
  - `validation_command` *(string)*

#### Minimal validation rules
1. `stages` must be non-empty and **ordered** as written.
2. Stage `id` values must be unique.
3. Every `inputs[]` artifact name must have been produced by **some prior stage output** (no forward refs).
   *(Exception: future extension could allow declared “external inputs”; not in v0.)*
4. No duplicate artifact names within a single `outputs[]`.
5. `placeholder` must be a boolean when present.
6. Artifact names are simple strings (recommended: filenames like `items.jsonl`).
7. If `mode=human_required`, `instructions.summary`, `instructions.steps`, and `instructions.done_when` are required.

---

## Example `pipeline.yaml` (v0)

```yaml
pipeline_id: seed_minimal
item_unit: item
determinism:
  policy: strict

stages:
  - id: ingest
    mode: whole_run
    outputs: [items.jsonl]

  - id: transform
    mode: per_item
    inputs: [items.jsonl]
    outputs: [transformed.jsonl]

  - id: validate
    mode: whole_run
    inputs: [transformed.jsonl]
    outputs: [validation.json]

  - id: future_review
    mode: whole_run
    placeholder: true
    inputs: [transformed.jsonl, validation.json]
    outputs: [reviewed.json]

  - id: publish
    mode: whole_run
    inputs: [reviewed.json]
    outputs: [published.marker]
```

## Example `human_required` stage (future extension)

```yaml
stages:
  - id: ingest
    mode: whole_run
    outputs: [items.jsonl]

  - id: align_quotes
    mode: human_required
    inputs: [items.jsonl]
    outputs: [quote_map.json]
    instructions:
      summary: "Align quotes and anchors for mapping."
      steps:
        - "Run: python scripts/build_quote_map.py --in runs/{run_id}/items.jsonl --out runs/{run_id}/quote_map.json"
        - "Open quote_map.json and fix any 'AMBIGUOUS' entries"
        - "Re-run: python scripts/validate_quote_map.py runs/{run_id}/quote_map.json"
      done_when:
        - "validate_quote_map exits 0"
      validation_command: "python scripts/validate_quote_map.py runs/{run_id}/quote_map.json"
```
