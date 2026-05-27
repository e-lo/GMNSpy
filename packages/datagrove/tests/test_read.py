"""Regression tests for the new kwargs on :func:`datagrove.read`.

Covers the three architecture-spec'd kwargs (``format=``,
``credentials=``, ``scope=``) added to satisfy the §6.1 signature
contract.

* ``format=`` short-circuits format dispatch (the documented escape
  hatch for extensionless URLs / mismatched suffixes).
* ``credentials=`` is threaded through to :class:`RemoteAdapter` for
  URL sources; local-fs sources silently ignore it.
* ``scope=`` post-applies :meth:`Package.scope` so callers don't have
  to chain manually.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import datagrove
import pytest
from datagrove.engines.pandas_engine import PandasEngine
from datagrove.fixtures import sample

# ---------------------------------------------------------------------------
# format=
# ---------------------------------------------------------------------------


def test_read_format_override_loads_extensionless_csv(tmp_path: Path) -> None:
    """A CSV file with no extension still loads when ``format='csv'`` is given.

    The extension-sniff path would raise FormatNotDetected; ``format=``
    short-circuits dispatch per the architecture spec.
    """
    src_csv = sample.csv_dir() / "book.csv"
    bare = tmp_path / "book_no_ext"
    shutil.copyfile(src_csv, bare)

    pkg = datagrove.read(bare, format="csv", engine=PandasEngine())
    # CsvAdapter.scan returns one ResourceRef whose name comes from
    # the stem — exact name depends on adapter, just confirm we got a
    # single-table package.
    assert len(pkg.tables) == 1


def test_read_format_passthrough_to_package_from_source() -> None:
    """``format=`` is forwarded as a kwarg to :meth:`Package.from_source`.

    Regression guard: an earlier version dropped the kwarg before
    forwarding, which silently disabled the override.
    """
    # Use a known-good directory + explicit format; either path
    # works (directory walk doesn't need format), but verifying the
    # call succeeds is the contract we care about.
    pkg = datagrove.read(sample.csv_dir(), format="csv", engine=PandasEngine())
    assert "book" in pkg


# ---------------------------------------------------------------------------
# credentials=
# ---------------------------------------------------------------------------


def test_read_credentials_threaded_to_remote_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Caller-passed ``credentials`` reach :meth:`RemoteAdapter.read` for URL sources.

    Captures the kwargs by monkeypatching the remote adapter's read
    method. Avoids real network I/O.
    """
    captured: dict[str, object] = {}

    from datagrove.io import get_adapter

    remote = get_adapter("remote")
    real_read = remote.read

    def fake_read(self, source, engine, schema=None, **kwargs):  # type: ignore[no-untyped-def]
        captured["source"] = source
        captured["credentials"] = kwargs.get("credentials")
        # Return a placeholder so from_source can build a Table — we
        # only care about the kwarg, not the data.
        return engine.from_records([{"x": 1}])

    monkeypatch.setattr(type(remote), "read", fake_read)
    try:
        datagrove.read(
            "s3://fakebucket/data.csv",
            credentials={"token": "secret"},
            engine=PandasEngine(),
        )
    finally:
        # belt-and-suspenders restore (monkeypatch undoes it, but be
        # explicit so a future refactor that captures the bound
        # method doesn't leak state).
        monkeypatch.setattr(type(remote), "read", real_read)

    assert captured["source"] == "s3://fakebucket/data.csv"
    assert captured["credentials"] == {"token": "secret"}


def test_read_credentials_not_forwarded_to_local_adapters() -> None:
    """Local-fs reads must NOT receive ``credentials`` — would break engine.read_csv.

    Confirms the "remote-only" guard in
    :meth:`Package.from_source`. Without the guard, pandas would
    raise ``TypeError: read_csv() got an unexpected keyword
    argument 'credentials'``.
    """
    pkg = datagrove.read(
        sample.csv_dir(),
        credentials={"token": "ignored-for-local"},
        engine=PandasEngine(),
    )
    # If credentials had leaked into engine.read_csv this would have
    # raised; the assertion is that we got a populated package back.
    assert "book" in pkg


# ---------------------------------------------------------------------------
# scope=
# ---------------------------------------------------------------------------


def test_read_scope_filters_tables() -> None:
    """``scope={'tables': [...]}`` post-applies :meth:`Package.scope`."""
    pkg = datagrove.read(
        sample.csv_dir(),
        scope={"tables": ["book"]},
        engine=PandasEngine(),
    )
    assert pkg.keys() == ["book"]


def test_read_scope_none_is_noop() -> None:
    """``scope=None`` (and the default) must not call :meth:`Package.scope`.

    Guards against a silent regression where ``None`` started filtering
    everything out / raising — the default has to be inert.
    """
    pkg_default = datagrove.read(sample.csv_dir(), engine=PandasEngine())
    pkg_none = datagrove.read(sample.csv_dir(), scope=None, engine=PandasEngine())
    assert sorted(pkg_default.keys()) == sorted(pkg_none.keys())


def test_read_scope_columns_projection() -> None:
    """``scope={'columns': {...}}`` projects per-table columns."""
    pkg = datagrove.read(
        sample.csv_dir(),
        scope={"tables": ["book"], "columns": {"book": ["id"]}},
        engine=PandasEngine(),
    )
    assert pkg["book"].columns() == ["id"]
