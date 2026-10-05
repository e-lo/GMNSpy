"""The local Overture snapshot layout, dependency-free so the workbench's file browser can detect it.

A **local snapshot** (``data_root=`` on the builder, the ``overture.data_root`` setting, or a
folder picked in the workbench's Open / Import wizard) is one flat folder holding exactly
:data:`LOCAL_SNAPSHOT_FILES`:

* ``segment.parquet``: Overture ``transportation/segment`` features, as published (GeoParquet with
  WKB ``geometry`` and the ``bbox`` struct column);
* ``connector.parquet``: the matching ``transportation/connector`` features.

Any bbox subset of one release works (for example the output of the ``overturemaps`` CLI or a
DuckDB ``COPY`` of a release filtered on ``bbox``). Remote ``s3://`` / ``az://`` / ``https://``
roots use the release's hive layout instead (``theme=transportation/type=<type>/*``).
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["LOCAL_SNAPSHOT_FILES", "is_local_snapshot"]

#: Files a flat local Overture snapshot folder must hold.
LOCAL_SNAPSHOT_FILES: tuple[str, ...] = ("segment.parquet", "connector.parquet")


def is_local_snapshot(path: str | Path) -> bool:
    """Whether ``path`` is a folder laid out as a local Overture snapshot."""
    folder = Path(path)
    return folder.is_dir() and all((folder / name).is_file() for name in LOCAL_SNAPSHOT_FILES)
