---
name: datagrove-validate
description: Validate any Frictionless-aligned tabular data package using the datagrove CLI. Use when the user has a directory with datapackage.json + table files (CSV/Parquet) and wants schema, type, and foreign-key validation — independent of GMNS.
---

# datagrove-validate

Use this skill when a user points at a folder, zip, or DuckDB file containing a
Frictionless `datapackage.json` and asks "is this valid?", "what's wrong with
this data?", or wants to gate a pipeline on schema conformance.

`datagrove` is the generic Frictionless validation engine that underpins
`gmnspy`. It knows nothing about GMNS — it validates whatever schema your
`datapackage.json` declares. If the user's question is specifically about GMNS
semantics (lane counts, network connectivity, etc.), use the `gmns-validate`
skill instead.

## Workflow

1. **Locate the source.** A datagrove source is one of:
   - A directory with `datapackage.json` at its root
   - A `.zip` containing the same
   - A `.duckdb` file with a `datapackage` table
   - A single CSV/Parquet with an inferred schema (`--infer`)
2. **Run `datagrove info` first** to confirm datagrove can read the package
   and see which tables it found. This catches missing files, bad JSON, or
   wrong working directory before the slower validation pass.
3. **Run `datagrove validate <source> --json`** and capture stdout. The JSON
   shape is:
   ```json
   {
     "source": "...",
     "ok": false,
     "summary": {"errors": 3, "warnings": 12, "tables": 5},
     "issues": [
       {"table": "link", "code": "schema.required",
        "severity": "error", "row": 14, "field": "from_node_id",
        "message": "..."}
     ]
   }
   ```
4. **Group issues by severity.** Always surface `error` first, then
   `warning`, then `info`. Within severity, group by `code` so the user sees
   "23 of these, all the same root cause" rather than a 200-line wall.
5. **Map common codes to remedies:**
   - `schema.required` → required column missing or null; check the source
     export
   - `schema.type` → cell can't parse as declared type; usually empty strings
     vs nulls, or commas in numeric fields
   - `schema.enum` → value outside the allowed list; check schema vs source
     vocabulary
   - `fk.missing_target` → foreign key points at an id that doesn't exist in
     the parent table; usually a join key drift or stale export
   - `package.missing_resource` → `datapackage.json` references a file that
     isn't on disk
6. **Suggest the next command.** If the user has issues to triage, point them
   at `datagrove validate <source> --severity=error --json` to filter, or at
   `--table=<name>` to scope to one resource.

## Example

Validate a package, count issues by code, print top offenders:

```bash
# Quick sanity check
datagrove info ./my_package

# Full validation, JSON output piped to jq
datagrove validate ./my_package --json \
  | jq '.issues | group_by(.code) | map({code: .[0].code, count: length})'
```

Example output:

```json
[
  {"code": "fk.missing_target", "count": 47},
  {"code": "schema.required", "count": 3},
  {"code": "schema.type", "count": 1}
]
```

Interpretation:

- 47 `fk.missing_target` from one table almost always means a join column was
  renamed or an upstream filter dropped rows. Don't fix 47 rows by hand —
  re-run the export.
- 3 `schema.required` is fixable inline; tell the user which rows.
- 1 `schema.type` is usually a single dirty cell; show the row and field.

For Python integration:

```python
from datagrove import Package

pkg = Package.from_source("./my_package")
report = pkg.validate()  # ValidationReport
print(report.ok, report.summary)
for issue in report.errors():
    print(issue.code, issue.table, issue.row, issue.message)
```

## Severity guidance

- `error` — schema violation; downstream consumers will break. Block the
  pipeline.
- `warning` — likely-bad data that still parses; surface to the user but
  don't block.
- `info` — advisory; e.g. "table has 0 rows".

When reporting to the user, never say "the data is valid" if there are
warnings. Say "0 errors, N warnings — here's what to look at."

## See also

- `gmns-validate` — GMNS-specific schema and quality codes
- `gmns-convert` — convert between datagrove-readable formats
- Frictionless Data spec: <https://specs.frictionlessdata.io/>
- Repo docs: `packages/datagrove/README.md`
