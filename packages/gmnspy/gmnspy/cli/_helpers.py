"""Shared helpers for the per-command modules in :mod:`gmnspy.cli.commands`.

Kept thin on purpose: each helper here is used by 2+ command modules. Per-command
helpers live with the command (e.g. doctor's ``_check_*`` functions are in
``commands/doctor.py``, the spec-diff field walker lives in ``commands/spec.py``).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from gmnspy import Network

__all__ = [
    "list_index_sidecars",
    "load_network_and_session_cls",
    "resolve_engine",
    "save_index_sidecar",
    "summarise_results",
    "summarise_scope",
    "write_network",
]


def resolve_engine(name: str | None):
    """Thin CLI wrapper around :func:`datagrove.engines.resolve_engine`.

    Converts the public resolver's :class:`ValueError` (raised on an
    unknown engine name) into :class:`typer.BadParameter` so the CLI
    exits with a clean non-zero + help message instead of a traceback.
    The actual ``name → Engine`` logic lives in :mod:`datagrove.engines`
    so both CLIs share it.
    """
    from datagrove.engines import resolve_engine as _resolve

    try:
        return _resolve(name)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def load_network_and_session_cls(source: Path, engine_name: str | None = None):
    """Return ``(Network, Session class)``.

    :class:`Session` lives in datagrove, imported here so each ``clean``
    command stays one expression long.

    ``engine_name`` follows the same ibis/pandas/polars resolution as
    :func:`resolve_engine`. Callers can override the default ibis engine
    to dodge backend-specific edge cases (e.g. duckdb refusing null-typed
    columns when re-materialising via ``engine.from_records`` during a
    ``replace_table`` edit on a fixture that carries empty string
    columns typed as null).
    """
    from datagrove.editing import Session

    from gmnspy import Network

    return Network.from_source(source, engine=resolve_engine(engine_name)), Session


def summarise_results(
    results,
    *,
    op: str,
    source: Path,
    dest: Path | None,
    dry_run: bool,
) -> dict[str, object]:
    """Render an :class:`EditResult` (or list thereof) into the CLI's standard summary dict."""
    if not isinstance(results, list):
        results = [results]
    return {
        "op": op,
        "source": str(source),
        "dest": str(dest) if dest is not None else str(source),
        "dry_run": dry_run,
        "edits": [
            {
                "table": r.edit.table,
                "op": r.edit.op,
                "rows_added": r.diff.rows_added,
                "rows_removed": r.diff.rows_removed,
                "rows_changed": r.diff.rows_changed,
            }
            for r in results
        ],
    }


def summarise_scope(scope) -> dict[str, object]:
    """Render a :class:`NetworkScope` into the CLI's standard summary dict."""
    return {
        "node_count": len(scope.node_ids),
        "link_count": len(scope.link_ids),
        "node_ids": sorted(scope.node_ids),
        "link_ids": sorted(scope.link_ids),
        "provenance": scope.provenance,
    }


def write_network(net: Network, *, source: Path, dest: Path | None) -> None:
    """Write ``net`` back to ``dest`` (or ``source`` when ``dest`` is None).

    Uses :meth:`Package.write`; the format is inferred from the
    target's extension, falling back to ``parquet`` for directory
    targets — matches the read-path convention so a round-trip lands
    the same logical package.

    Suppresses :class:`OutOfSyncWarning` (raised by the dirty tracker
    on tables we just edited). The whole point of these CLI ops is
    "edit then write" — the dirty flag is expected, and the warning
    would be promoted to an error under the project's
    ``filterwarnings = ["error"]`` pytest config.
    """
    import warnings

    from datagrove.dataset.package import OutOfSyncWarning

    target = dest if dest is not None else source
    overwrite = target.exists()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", OutOfSyncWarning)
        net.write(target, overwrite=overwrite)


def list_index_sidecars(source: Path) -> list[Path]:
    """Return sorted sidecar parquet files for the network at ``source`` (empty list when none)."""
    sidecar_dir = source.parent / "_gmnspy_indexes"
    if not sidecar_dir.is_dir():
        return []
    return sorted(sidecar_dir.glob(f"{source.stem}.*.parquet"))


def save_index_sidecar(
    indexes,
    source: Path,
    net: Network,
    kind: str,
    index_obj,
    *,
    kind_target: str,
) -> Path:
    """Hash the relevant source table(s), compute the sidecar path, write the index."""
    from datagrove.validation import hash_table

    if kind_target == "link":
        content_hash = hash_table(net.links.expr, net.engine)
    else:
        # graph index keys off both links + nodes — combine the digests
        # by hashing the concatenation; only the first 8 chars land in
        # the filename anyway (see cache_path docstring).
        import hashlib

        link_h = hash_table(net.links.expr, net.engine)
        node_h = hash_table(net.nodes.expr, net.engine)
        content_hash = hashlib.sha256(f"{link_h}::{node_h}".encode()).hexdigest()
    path = indexes.cache_path(str(source), kind, content_hash)
    indexes.save_cached(path, index_obj)
    return path
