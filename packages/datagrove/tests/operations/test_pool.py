"""Tests for the pool/batch context manager (task 3.2 / issue #70).

Coverage matrix:

* Batch defers ops — state unchanged until ``__exit__``.
* Batch is atomic on exception — no Session is opened, state intact.
* Coalescing: multiple ``add_rows`` on the same table collapse to one.
* Coalescing: ``replace_table`` discards prior edits on that table.
* Coalescing: ``update_rows`` / ``delete_rows`` are NOT merged.
* ``Batch.flush()`` applies the queue mid-block and clears it.
* Validation runs once on clean commit (not per op).
* ``strict=True`` rolls back when validation surfaces an error.
* ``Package.batch()`` convenience returns a :class:`Batch`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from datagrove.dataset import Package, Table
from datagrove.editing import Edit
from datagrove.engines.pandas_engine import PandasEngine
from datagrove.operations import Batch, coalesce

if TYPE_CHECKING:
    pass


def _pkg(rows: list[dict] | None = None) -> Package:
    """One-table Package over the pandas engine; default 3-row fixture."""
    eng = PandasEngine()
    if rows is None:
        rows = [{"id": 1, "v": "a"}, {"id": 2, "v": "b"}, {"id": 3, "v": "c"}]
    t = Table(name="t", expr=eng.from_records(rows), engine=eng)
    return Package.from_tables({"t": t})


def _ids(pkg: Package, table: str = "t") -> list[int]:
    """Sorted ``id`` column for state assertions."""
    return sorted(pkg[table].to_pandas()["id"].tolist())


# ---------------------------------------------------------------------------
# coalesce() unit
# ---------------------------------------------------------------------------


def test_coalesce_merges_add_rows_on_same_table() -> None:
    """Two add_rows on the same table merge into one with concatenated rows."""
    e1 = Edit(op="add_rows", table="t", payload={"rows": [{"id": 10}]})
    e2 = Edit(op="add_rows", table="t", payload={"rows": [{"id": 11}, {"id": 12}]})
    out = coalesce([e1, e2])
    assert len(out) == 1
    assert out[0].op == "add_rows"
    assert out[0].table == "t"
    assert out[0].payload["rows"] == [{"id": 10}, {"id": 11}, {"id": 12}]


def test_coalesce_preserves_add_rows_on_different_tables() -> None:
    """add_rows on different tables are NOT merged."""
    a = Edit(op="add_rows", table="t1", payload={"rows": [{"id": 1}]})
    b = Edit(op="add_rows", table="t2", payload={"rows": [{"id": 2}]})
    out = coalesce([a, b])
    assert len(out) == 2
    assert {e.table for e in out} == {"t1", "t2"}


def test_coalesce_preserves_update_and_delete() -> None:
    """update_rows / delete_rows are NOT merged — predicate order matters."""
    u1 = Edit(op="update_rows", table="t", payload={"predicate": lambda t: t.id == 1, "set": {"v": "x"}})
    u2 = Edit(op="update_rows", table="t", payload={"predicate": lambda t: t.id == 2, "set": {"v": "y"}})
    d1 = Edit(op="delete_rows", table="t", payload={"predicate": lambda t: t.id == 3})
    out = coalesce([u1, u2, d1])
    assert len(out) == 3


def test_coalesce_replace_table_discards_prior_edits_on_same_table() -> None:
    """replace_table on table X discards any pending edits queued earlier on X."""
    eng = PandasEngine()
    expr = eng.from_records([{"id": 99}])
    a = Edit(op="add_rows", table="t", payload={"rows": [{"id": 1}]})
    u = Edit(op="update_rows", table="t", payload={"predicate": lambda t: True, "set": {"v": "z"}})
    r = Edit(op="replace_table", table="t", payload={"expr": expr})
    other = Edit(op="add_rows", table="other", payload={"rows": [{"id": 5}]})
    out = coalesce([a, u, r, other])
    # The replace and the other-table add survive; the t-edits before the
    # replace are dropped.
    ops = [(e.op, e.table) for e in out]
    assert ops == [("replace_table", "t"), ("add_rows", "other")]


# ---------------------------------------------------------------------------
# Batch context manager
# ---------------------------------------------------------------------------


def test_batch_defers_until_exit() -> None:
    """State remains unchanged until ``__exit__`` runs."""
    pkg = _pkg()
    starting = _ids(pkg)
    with Batch(pkg) as b:
        b.add_edit(Edit(op="add_rows", table="t", payload={"rows": [{"id": 10}]}))
        # Mid-block: state still the original three rows.
        assert _ids(pkg) == starting
    # After exit: the queued row is present.
    assert _ids(pkg) == [*starting, 10]


def test_batch_atomic_on_exception() -> None:
    """An exception inside ``with`` discards every pending op."""
    pkg = _pkg()
    starting = _ids(pkg)
    with pytest.raises(RuntimeError, match="boom"), Batch(pkg) as b:
        b.add_edit(Edit(op="add_rows", table="t", payload={"rows": [{"id": 10}]}))
        b.add_edit(Edit(op="add_rows", table="t", payload={"rows": [{"id": 11}]}))
        raise RuntimeError("boom")
    # No Session was opened, no edits applied.
    assert _ids(pkg) == starting


def test_batch_coalesces_add_rows_on_commit() -> None:
    """Multiple add_rows on the same table collapse to one Session edit."""
    pkg = _pkg()
    with Batch(pkg) as b:
        b.add_edit(Edit(op="add_rows", table="t", payload={"rows": [{"id": 10}]}))
        b.add_edit(Edit(op="add_rows", table="t", payload={"rows": [{"id": 11}]}))
        b.add_edit(Edit(op="add_rows", table="t", payload={"rows": [{"id": 12}]}))
    result = b.last_result
    assert result is not None
    # Three queued add_rows → one coalesced result with all rows applied.
    assert len(result.results) == 1
    assert _ids(pkg) == [1, 2, 3, 10, 11, 12]


def test_batch_flush_applies_and_clears_queue() -> None:
    """flush() applies queued ops mid-block and clears the queue."""
    pkg = _pkg()
    with Batch(pkg) as b:
        b.add_edit(Edit(op="add_rows", table="t", payload={"rows": [{"id": 10}]}))
        flushed = b.flush()
        assert flushed is not None
        assert _ids(pkg) == [1, 2, 3, 10]
        # Queue cleared — a follow-up add only queues the new row.
        b.add_edit(Edit(op="add_rows", table="t", payload={"rows": [{"id": 20}]}))
    assert _ids(pkg) == [1, 2, 3, 10, 20]


def test_batch_validates_once_on_commit() -> None:
    """Batch calls package.validate() exactly once on clean exit."""
    pkg = _pkg()
    calls: list[int] = []
    original = pkg.validate

    def _tracking_validate(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    pkg.validate = _tracking_validate  # type: ignore[method-assign]

    with Batch(pkg) as b:
        b.add_edit(Edit(op="add_rows", table="t", payload={"rows": [{"id": 10}]}))
        b.add_edit(Edit(op="add_rows", table="t", payload={"rows": [{"id": 11}]}))
        # Mid-block: not yet validated.
        assert len(calls) == 0
    # Exit validated once, despite three queued edits coalescing into one.
    assert len(calls) == 1


def test_batch_strict_rolls_back_on_validation_error() -> None:
    """strict=True reverses the applied batch when validation surfaces an error."""
    pkg = _pkg()

    # Force validate() to return a report with at least one ERROR issue.
    from datagrove.reports import Category, Issue, Severity, ValidationReport

    def _fake_validate(*args, **kwargs):
        report = ValidationReport(source=pkg.source)
        report.issues.append(
            Issue(
                category=Category.SCHEMA,
                severity=Severity.ERROR,
                code="schema.test",
                message="synthetic failure",
                table="t",
            )
        )
        return report

    pkg.validate = _fake_validate  # type: ignore[method-assign]

    starting = _ids(pkg)
    with pytest.raises(Exception, match="validation"), Batch(pkg, strict=True) as b:
        b.add_edit(Edit(op="add_rows", table="t", payload={"rows": [{"id": 10}]}))
    # strict rollback: state restored.
    assert _ids(pkg) == starting


def test_package_batch_returns_batch_bound_to_package() -> None:
    """Package.batch() is a convenience that returns a Batch over self."""
    pkg = _pkg()
    b = pkg.batch()
    assert isinstance(b, Batch)
    assert b.package is pkg
    # Round-trip use:
    with b:
        b.add_edit(Edit(op="add_rows", table="t", payload={"rows": [{"id": 42}]}))
    assert 42 in _ids(pkg)
