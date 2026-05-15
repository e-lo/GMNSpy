"""Pydantic models + loader for Frictionless data packages, table schemas, and shared categories."""

from .loader import SpecLoadError, load_package, load_schema
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

__all__ = [
    "Constraints",
    "DataPackage",
    "Field",
    "ForeignKey",
    "ForeignKeyReference",
    "MissingValues",
    "Resource",
    "Schema",
    "SharedCategory",
    "SpecLoadError",
    "SpecVersion",
    "compatible",
    "load_package",
    "load_schema",
    "parse_version_dir",
]
