# ADR — Foreign keys: report with anti-join validation, don't enforce with DuckDB constraints

Status: **accepted** · Date: 2026-10-01 (spike 1), 2026-10-02 (spike 2) · Owner: corral core ·
Related: [engine strategy ADR](2026-10-01-engine-strategy-reevaluation.md)

## Context

corral validates primary keys, foreign keys, NOT NULL, enum and range rules by running pushed-down
SQL aggregates and anti-joins through ibis (`corral.validation.check_schema`,
`corral.validation.foreign_keys.check_foreign_keys`). Every violation becomes a finding in a
`ValidationReport`; nothing is rejected at load time.

With DuckDB as the only compute engine, the obvious alternative is to declare native
`PRIMARY KEY` / `FOREIGN KEY` / `UNIQUE` / `CHECK` constraints on the tables and let DuckDB enforce
them. Two spikes measured that against the current approach.

## Evidence

Synthetic GMNS-like data, 2M links / 1M nodes, in memory.

**Spike 1 (DuckDB 1.1.3), FK in isolation**

| | Load time | vs. no constraints |
|---|---|---|
| No constraints | 0.034 s | 1× |
| + PK | 0.574 s | ~17× |
| + PK + FK | 4.075 s | ~120× |

- Peak RSS: +100 MB for PK, +186 MB for PK + FK (ART indexes).
- Point lookup of 2k links by id: 1.6× faster with a PK — the only upside, and it comes from the PK, not the FK.
- link→node join: FK made it slightly *slower*; the optimizer does not use declared FKs for join elimination.
- Anti-join "find all dangling refs": ~0.03 s, independent of constraints.
- Enforcement semantics: one dangling row in a 10k-row bulk insert rolls back **all** rows, and DuckDB does not report which rows are bad.

**Spike 2 (DuckDB 1.5.6, ibis 12), the full constraint set**

- corral's full reporting validation (not-null + unique/PK + enum/range + FK): **0.34 s**.
- Loading the same rows into a table with PK + NOT NULL + CHECK + UNIQUE + FK: **2.93 s** (~46× a bare load).
- Our validators are ~9× cheaper than the constrained load, because they scan once and never build persistent indexes.

Caveats: synthetic data (no strings or geometry) and clean-data timings. Violations add bounded
row sampling on our side; DuckDB aborts on the first one.

## Decision

1. **Keep anti-join / aggregate validation** as the only integrity mechanism on the read and validate path.
   It reports every problem, never fails a load, supports `ignore_missing` and the findings workflow, and is cheaper.
2. **Don't declare native constraints by default.** That includes PKs: a 1.6× faster point lookup
   doesn't justify ~10–17× load time and +100 MB, and the viewer already keeps in-memory id→index maps.
3. **Native constraints are only allowed in an opt-in "trusted store" export**, written after validation passes.
   This would generate constrained `CREATE TABLE` DDL from the Frictionless schema. It is backlog, not planned.
   Building it would need:
   - a sanctioned `lint_no_sql` exception, since ibis can't emit FK DDL;
   - tables created in topological order;
   - geometry mapped to `BLOB` or `GEOMETRY`;
   - handling for composite and soft references.

## Consequences

- `corral.validation` stays the single place integrity rules live; there is no second enforcement path to keep in sync.
- Re-check the numbers if the DuckDB ART index costs change materially.
