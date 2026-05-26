---
title: Validate a network and read the report
audience: users
kind: howto
summary: Run validation against the GMNS spec and interpret the ValidationReport — severity, category, code, and how to filter findings programmatically.
---

# Validate a network and read the report

## When to use this

You have a GMNS network — yours, a vendor's, the output of an edit — and you need to know whether it conforms to the spec before downstream tools (assignment models, AI agents, regulators) touch it. Validation is fast (sub-second on Leavenworth, a few seconds on a regional network) and answers four questions at once: do all required tables exist, do columns match the schema, do foreign keys resolve, and are any of those FKs stale from a recent edit?

## Quick example

```text
$ gmnspy validate --json packages/gmnspy/gmnspy/fixtures/leavenworth/csv
{"spec_version": "0.97", "passed": true, "issues": [], ...}
```

Or from Python:

```python
from gmnspy import Network
from gmnspy.fixtures import leavenworth

net = Network.from_source(leavenworth.csv_dir())
report = net.validate()
print(f"passed={report.passed}  issues={len(report.issues)}")
```

The Leavenworth fixture is clean, so the issue list is empty and `passed` is `True`. The CLI exits non-zero if any ERROR-severity finding fires.

## Step-by-step

### 1. Run validation

```python
report = net.validate()                              # all four passes
report = net.validate(passes=["schema", "fk"])       # only two of them
```

Equivalent CLI:

```text
$ gmnspy validate <source>                  # human-readable summary
$ gmnspy validate <source> --json           # machine-readable
$ gmnspy validate <source> --format html    # standalone HTML report
```

### 2. Read the report shape

`ValidationReport` is a dataclass with three fields you'll touch:

| Field | Type | Description |
|---|---|---|
| `report.passed` | `bool` | `True` iff no ERROR-severity issue fired. WARNINGs and INFOs do not flip this. |
| `report.spec_version` | `str` | The GMNS spec version the validator ran against. |
| `report.issues` | `list[Issue]` | One entry per finding. |

Each `Issue` carries:

```python
@dataclass
class Issue:
    severity: Severity      # ERROR | WARNING | INFO
    category: Category      # SCHEMA | STRUCTURAL | FOREIGN_KEY | SYNC_STATE | DATA_QUALITY
    code: str               # stable identifier, e.g. "schema.required"
    message: str            # human-readable
    table: str | None       # table the finding is about
    column: str | None      # column, if applicable
    row: int | None         # row index, if applicable
    fix_hint: str | None    # what to do about it
```

### 3. Filter by severity

```python
from datagrove.validation import Severity

errors = [i for i in report.issues if i.severity is Severity.ERROR]
warnings = [i for i in report.issues if i.severity is Severity.WARNING]
```

Most CI gates want `if errors: sys.exit(1)`. The CLI does this for you.

### 4. Filter by category

```python
from datagrove.validation import Category

schema_problems = [i for i in report.issues if i.category is Category.SCHEMA]
fk_problems = [i for i in report.issues if i.category is Category.FOREIGN_KEY]
```

Categories let you group findings by which validation pass produced them:

* `SCHEMA` — field-level type / enum / required-column violations.
* `STRUCTURAL` — package-level shape problems (missing required table, missing required file).
* `FOREIGN_KEY` — cross-table integrity (`link.from_node_id` points at a node that doesn't exist).
* `SYNC_STATE` — FKs that resolved on disk but were invalidated by an in-memory edit (see [edit-with-rollback](edit-with-rollback.md)).
* `DATA_QUALITY` — rule-pack findings (high-speed-residential, lane-count-mismatch, etc.). Always WARNING / INFO; see [customise the quality pack](index.md#validation--data-quality).

### 5. Common codes you'll see

| Code | Category | Severity | What it means |
|---|---|---|---|
| `schema.required` | SCHEMA | ERROR | A required column is missing or null on a row. |
| `schema.enum` | SCHEMA | ERROR | A column value isn't in the spec-defined enum set. |
| `schema.type` | SCHEMA | ERROR | A value doesn't parse as the declared type. |
| `structural.missing_table` | STRUCTURAL | ERROR | A required table (`link`, `node`) isn't in the package. |
| `structural.missing_file` | STRUCTURAL | ERROR | A table is declared in the package descriptor but the file isn't there. |
| `fk.missing_target` | FOREIGN_KEY | ERROR | FK points at a row that doesn't exist in the parent table. |
| `fk.dangling_child` | FOREIGN_KEY | WARNING | Parent row has no children (often benign). |
| `sync.fk_stale` | SYNC_STATE | ERROR | An edit invalidated an FK and no `recompute` ran. |
| `quality.high_speed_residential` | DATA_QUALITY | WARNING | Residential link with speed limit above the configured threshold. |

The full list lives in `datagrove.validation.codes` and is enumerated in the [reference](../reference/api.md).

## Common variations

| You want... | Do this |
|---|---|
| HTML report for a stakeholder | `report.to_html("report.html")` or `gmnspy validate <src> --format html > report.html`. |
| Just the failing tables | `{i.table for i in report.issues if i.is_error()}`. |
| Embed validation in a CI step | `gmnspy validate <src>` — non-zero exit code on ERROR, no extra wiring needed. |
| Pretty-print in a notebook | `report` renders an HTML summary via `_repr_html_` — call `display(report)` or just leave it as the last cell expression. |
| Server response | The HTTP server returns JSON by default and HTML when the request sets `Accept: text/html`. |

## Pitfalls

* **WARNING-level findings don't fail CI.** That's intentional — data-quality findings are advisory. If you want them to be blocking, post-process: `if any(i.code.startswith("quality.") for i in report.issues): sys.exit(1)`.
* **Data-quality thresholds are configurable.** A WARNING firing on your network may just mean the default threshold doesn't match your context (e.g. metric vs imperial speed). See the [customise the quality pack](index.md#validation--data-quality) recipe.
* **`sync.fk_stale` only fires after an edit.** A freshly-loaded package can't be out of sync with itself. If you see this in CI, an upstream step in the same process mutated the network.
* **The validator runs against the spec version embedded in the package.** Override with `Network.from_source(path, spec_version="0.96")` if the package is mislabeled.

## See also

* [Architecture](../architecture.md) — the four-pass validator design.
* [Edit with rollback](edit-with-rollback.md) — `sync.fk_stale` is produced by edits without a `recompute_fks`.
* [API reference](../reference/api.md) — `ValidationReport`, `Issue`, `Severity`, `Category`.
