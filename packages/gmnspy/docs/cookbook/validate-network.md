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

Validate the bundled Leavenworth fixture from the shell. Add `--json` to any `gmnspy` (or `datagrove`) CLI command and the output becomes a single machine-readable JSON document on stdout — pipe into `jq`, save to a file, feed to a script or AI agent. Default output is human-readable rich panels.

```bash
gmnspy validate --json packages/gmnspy/gmnspy/fixtures/leavenworth/csv
```

Expected — Leavenworth is clean of ERRORs and WARNINGs, so the issue list contains only INFO entries (optional tables not present):

```json
{"header": "validation report: ...", "issues": [{"severity": "info", ...}]}
```

The same call from Python returns a `ValidationReport` dataclass:

```python
from gmnspy import Network
from gmnspy.fixtures import leavenworth

net = Network.from_source(leavenworth.csv_dir())
report = net.validate()
print(f"is_clean={report.is_clean}  issues={len(report.issues)}")
```

The CLI exits non-zero if any ERROR-severity finding fires, so it drops straight into a CI gate.

![Validation report card for the Leavenworth fixture](../assets/screenshots/leavenworth-validation-report.png){ .screenshot }
*Validation report card. Zero ERRORs (Leavenworth is clean); a handful of DATA_QUALITY warnings from the residential-speed rule.*

## Step-by-step

### 1. Run validation

`net.validate()` runs all four passes — structural, schema, FK, sync-state — and returns a `ValidationReport`. Toggle individual passes with boolean kwargs:

```python
report = net.validate()                                                  # all four passes
report = net.validate(structural=False, sync_state=False)                # schema + FK only
```

The same operation is available from the shell, with three output formats:

```bash
gmnspy validate <source>                       # human-readable summary
gmnspy validate <source> --json                # machine-readable
gmnspy validate <source> --html report.html    # standalone HTML report
```

### 2. Read the report shape

`ValidationReport` is a dataclass with three fields you'll touch:

| Field / property | Type | Description |
|---|---|---|
| `report.is_clean` | `bool` | `True` iff zero issues of any severity fired. |
| `report.has_errors` | `bool` | `True` iff ≥1 ERROR-severity issue fired. CI gates usually want `if report.has_errors:`. |
| `report.has_warnings` | `bool` | `True` iff ≥1 WARNING-severity issue fired. |
| `report.spec_version` | `str` | The GMNS spec version the validator ran against. |
| `report.issues` | `list[Issue]` | One entry per finding. |

Each `Issue` is a small dataclass carrying severity, category, a stable code, a human-readable message, and the offending row coordinates when known:

<!-- doctest: skip -->
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

Most CI gates want `if errors: sys.exit(1)`. The CLI does this for you; from Python it's a one-liner:

```python
from datagrove.validation import Severity

errors = [i for i in report.issues if i.severity is Severity.ERROR]
warnings = [i for i in report.issues if i.severity is Severity.WARNING]
```

### 4. Filter by category

Categories group findings by which validation pass produced them:

```python
from datagrove.validation import Category

schema_problems = [i for i in report.issues if i.category is Category.SCHEMA]
fk_problems = [i for i in report.issues if i.category is Category.FOREIGN_KEY]
```

* `SCHEMA` — field-level type / enum / required-column violations.
* `STRUCTURAL` — package-level shape problems (missing required table, missing required file).
* `FOREIGN_KEY` — cross-table integrity (`link.from_node_id` points at a node that doesn't exist).
* `SYNC_STATE` — FKs that resolved on disk but were invalidated by an in-memory edit (see [edit-with-rollback](edit-with-rollback.md)).
* `DATA_QUALITY` — rule-pack findings (high-speed-residential, lane-count-mismatch, etc.). Always WARNING / INFO; see [customise the quality pack](customise-quality.md).

### 5. Common codes you'll see

Stable identifier strings let you script around specific findings without parsing free-text messages. Codes live inline at the top of each validator module (see [`datagrove.validation.structural`](https://github.com/e-lo/GMNSpy/blob/main/packages/datagrove/datagrove/validation/structural.py), [`schema_check`](https://github.com/e-lo/GMNSpy/blob/main/packages/datagrove/datagrove/validation/schema_check.py), [`foreign_keys`](https://github.com/e-lo/GMNSpy/blob/main/packages/datagrove/datagrove/validation/foreign_keys.py), [`sync_state`](https://github.com/e-lo/GMNSpy/blob/main/packages/datagrove/datagrove/validation/sync_state.py)). The most common ones:

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

## Common variations

???+ note "Default — full validation, rich console output"
    The most common path: run all four passes and read the panel.

    ```bash
    gmnspy validate <source>
    ```

??? note "JSON for scripts and AI agents"
    `--json` emits one parseable document on stdout — exits non-zero on ERROR.

    ```bash
    gmnspy validate <source> --json | jq '.issues[] | select(.severity=="error")'
    ```

??? note "Standalone HTML report for a stakeholder"
    Self-contained file you can email or upload to a docs site.

    ```bash
    gmnspy validate <source> --html report.html
    ```

    Or programmatically:

    ```python
    report.to_html("report.html")
    ```

??? note "Just the failing tables"
    Useful for triaging which datasets need attention first.

    ```python
    from datagrove.reports import Severity
    failing = {i.table for i in report.issues if i.severity is Severity.ERROR}
    ```

??? note "Embed in a CI step"
    Non-zero exit code on ERROR — no extra wiring needed.

    ```bash
    gmnspy validate ./data || exit 1
    ```

??? note "Pretty-print in a notebook"
    `ValidationReport` ships a `_repr_html_`; just leave it as the last cell expression.

    ```python
    report  # renders an HTML summary in Jupyter
    ```

??? note "Server response"
    The HTTP server returns JSON by default and HTML when the request sets `Accept: text/html`. See [serve-http](serve-http.md).

## Pitfalls

* **WARNING-level findings don't fail CI.** That's intentional — data-quality findings are advisory. If you want them to be blocking, post-process: `if any(i.code.startswith("quality.") for i in report.issues): sys.exit(1)`.
* **Data-quality thresholds are configurable.** A WARNING firing on your network may just mean the default threshold doesn't match your context (e.g. metric vs imperial speed). See the [customise the quality pack](customise-quality.md) recipe.
* **`sync.fk_stale` only fires after an edit.** A freshly-loaded package can't be out of sync with itself. If you see this in CI, an upstream step in the same process mutated the network.
* **The validator runs against the spec version embedded in the package.** Override with `Network.from_source(path, spec_version="0.96")` if the package is mislabeled.

## See also

* [Architecture](https://e-lo.github.io/GMNSpy/datagrove/architecture/) — the four-pass validator design.
* [Edit with rollback](edit-with-rollback.md) — `sync.fk_stale` is produced by edits without a `recompute_fks`.
* [API reference](../reference/api.md) — `ValidationReport`, `Issue`, `Severity`, `Category`.
