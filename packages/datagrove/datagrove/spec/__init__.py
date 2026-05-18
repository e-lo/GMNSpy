"""Pydantic models + loader for Frictionless data packages, table schemas, and shared categories.

Three groups of names live behind this package:

* **Models** — Pydantic v2 dataclasses for the Frictionless object graph
  (:class:`DataPackage`, :class:`Resource`, :class:`Schema`,
  :class:`Field`, :class:`ForeignKey`, :class:`ForeignKeyReference`,
  :class:`Constraints`, :class:`SharedCategory`, :data:`MissingValues`).
* **Loader** — file/URL/dict → validated model pipeline
  (:func:`load_package`, :func:`load_schema`) plus the
  :class:`SpecLoadError` / :class:`InvalidSpecVersionError` exception
  hierarchy.
* **Version** — :class:`SpecVersion` and helpers
  (:func:`compatible`, :func:`parse_version_dir`) for comparing spec
  releases and discovering vendored versions on disk.
"""

from .errors import InvalidSpecVersionError, SpecLoadError
from .loader import load_package, load_schema
from .model import (
    Constraints,
    DataPackage,
    Field,
    ForeignKey,
    ForeignKeyReference,
    MissingValues,
    Resource,
    Schema,
    SharedCategory,
)
from .version import SpecVersion, compatible, parse_version_dir

# Grouped by source module — see module docstring for the three groups.
# Order is intentional (groups > alphabetical within group); RUF022's
# whole-list sort would erase the grouping.
__all__ = [  # noqa: RUF022 — grouped re-exports, not strict alpha
    # --- Models (datagrove/spec/model.py) ---
    "Constraints",
    "DataPackage",
    "Field",
    "ForeignKey",
    "ForeignKeyReference",
    "MissingValues",
    "Resource",
    "Schema",
    "SharedCategory",
    # --- Loader + errors (datagrove/spec/loader.py, errors.py) ---
    "InvalidSpecVersionError",
    "SpecLoadError",
    "load_package",
    "load_schema",
    # --- Version (datagrove/spec/version.py) ---
    "SpecVersion",
    "compatible",
    "parse_version_dir",
]
