"""Loader for Frictionless data-package and table-schema JSON.

Reads ``datapackage.json`` (or any equivalent top-level descriptor) from
a local path, a remote URL (via ``fsspec``), or an already-parsed
``dict``; resolves relative ``schema`` references on each resource;
resolves intra-document and ``shared_categories.json`` ``$ref`` JSON
pointers; and returns a :class:`~datagrove.spec.model.DataPackage`.

The loader is intentionally generic: it knows nothing about GMNS or
any other domain. The ``shared_categories.json`` convention it
understands is widely useful for any pre-1.0 data package that wants
to reuse named enums across multiple schemas.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import fsspec
from pydantic import ValidationError

from .model import DataPackage, Schema

__all__ = ["SpecLoadError", "load_package", "load_schema"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SpecLoadError(Exception):
    """Raised when a data-package or schema cannot be loaded.

    The message always includes the source identifier (path, URL, or
    ``"<dict>"``) and a short description of what went wrong. Where
    relevant, the underlying exception is chained as ``__cause__``.

    Examples:
        >>> try:
        ...     raise SpecLoadError("oops at /tmp/missing.json")
        ... except SpecLoadError as e:
        ...     "missing.json" in str(e)
        True
    """


# ---------------------------------------------------------------------------
# Source classification + reading
# ---------------------------------------------------------------------------


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme) and parsed.scheme not in {"", "file"} and len(parsed.scheme) > 1


def _source_label(source: str | Path | dict[str, Any]) -> str:
    if isinstance(source, dict):
        return "<dict>"
    return str(source)


def _read_json_text(source: str | Path) -> tuple[str, str]:
    """Read raw JSON text from a local path or URL.

    Returns:
        A ``(text, base_uri)`` tuple where ``base_uri`` is the directory
        used to resolve relative references (a local directory path or
        a URL with a trailing slash).
    """
    src = str(source)
    if isinstance(source, Path) or not _is_url(src):
        path = Path(src).expanduser()
        if not path.exists():
            raise SpecLoadError(f"Spec source does not exist: {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            raise SpecLoadError(f"Failed to read spec from {path}: {e}") from e
        return text, str(path.parent)

    # Remote URL via fsspec. ``fsspec.open`` returns an OpenFile whose
    # context manager yields a file-like object; type stubs are loose so
    # we explicitly read as text.
    try:
        with fsspec.open(src, mode="rt", encoding="utf-8") as fh:
            raw = fh.read()  # type: ignore[union-attr]
        text = raw if isinstance(raw, str) else raw.decode("utf-8")
    except Exception as e:  # fsspec raises a wide variety of errors
        raise SpecLoadError(f"Failed to read spec from {src}: {e}") from e
    base = src.rsplit("/", 1)[0] + "/"
    return text, base


def _parse_json(text: str, label: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise SpecLoadError(f"Invalid JSON in {label}: {e.msg} (line {e.lineno}, col {e.colno})") from e


def _read_json(source: str | Path) -> tuple[Any, str]:
    text, base = _read_json_text(source)
    return _parse_json(text, _source_label(source)), base


def _join(base: str, relative: str) -> str:
    """Join a base URI/path with a relative reference."""
    if _is_url(relative):
        return relative
    if _is_url(base):
        if base.endswith("/"):
            return base + relative
        return base + "/" + relative
    return os.path.join(base, relative)


# ---------------------------------------------------------------------------
# JSON pointer / $ref resolution
# ---------------------------------------------------------------------------


def _resolve_pointer(doc: Any, pointer: str) -> Any:
    """Resolve a RFC-6901 JSON pointer against ``doc``.

    Supports the empty pointer (returns ``doc``) and the standard
    ``~0`` / ``~1`` escapes for ``~`` and ``/``.
    """
    if pointer in ("", "#"):
        return doc
    if pointer.startswith("#"):
        pointer = pointer[1:]
    if not pointer.startswith("/"):
        raise SpecLoadError(f"Invalid JSON pointer (must start with '/'): {pointer!r}")
    cur: Any = doc
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            try:
                idx = int(token)
            except ValueError as e:
                raise SpecLoadError(f"Invalid list index in pointer: {token!r}") from e
            try:
                cur = cur[idx]
            except IndexError as e:
                raise SpecLoadError(f"Pointer index out of range: {token!r}") from e
        elif isinstance(cur, dict):
            if token not in cur:
                raise SpecLoadError(f"Pointer token not found: {token!r}")
            cur = cur[token]
        else:
            raise SpecLoadError(f"Cannot descend into {type(cur).__name__} for token {token!r}")
    return cur


def _resolve_refs(
    obj: Any,
    *,
    base: str,
    cache: dict[str, Any],
    self_doc: Any,
) -> Any:
    """Recursively resolve ``$ref`` references in ``obj``.

    A ``$ref`` value of the form ``"file.json#/path/to/thing"`` loads
    ``file.json`` (relative to ``base``) and returns the value at the
    JSON pointer fragment. A ``$ref`` of just ``"#/path"`` resolves
    against ``self_doc``. External docs are cached by absolute path/URL.

    Returns the (possibly transformed) value with refs replaced.
    """
    if isinstance(obj, dict):
        if "$ref" in obj and isinstance(obj["$ref"], str):
            return _resolve_one_ref(obj["$ref"], base=base, cache=cache, self_doc=self_doc)
        return {k: _resolve_refs(v, base=base, cache=cache, self_doc=self_doc) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_refs(v, base=base, cache=cache, self_doc=self_doc) for v in obj]
    return obj


def _resolve_one_ref(
    ref: str,
    *,
    base: str,
    cache: dict[str, Any],
    self_doc: Any,
) -> Any:
    if ref.startswith("#"):
        return _resolve_pointer(self_doc, ref)
    if "#" in ref:
        file_part, pointer = ref.split("#", 1)
    else:
        file_part, pointer = ref, ""
    target = _join(base, file_part)
    if target not in cache:
        try:
            doc, _ = _read_json(target)
        except SpecLoadError as e:
            raise SpecLoadError(f"Failed to resolve $ref {ref!r}: {e}") from e
        cache[target] = doc
    doc = cache[target]
    if not pointer:
        return doc
    return _resolve_pointer(doc, "#" + pointer if not pointer.startswith("#") else pointer)


# ---------------------------------------------------------------------------
# Shared categories inlining
# ---------------------------------------------------------------------------


def _category_values(categories: Any) -> list[Any] | None:
    """Extract the scalar values from a ``categories`` payload.

    Accepts either:
        * a list of scalar values (returned as-is), or
        * a list of ``{"value": ..., "label": ...}`` objects (returns
          the ``value`` column).

    Returns ``None`` if the shape is unrecognized.
    """
    if not isinstance(categories, list):
        return None
    if all(isinstance(c, dict) and "value" in c for c in categories):
        return [c["value"] for c in categories]
    if all(not isinstance(c, (dict, list)) for c in categories):
        return list(categories)
    return None


def _inline_shared_categories(schema_obj: dict[str, Any]) -> None:
    """Promote resolved ``categories`` payloads onto ``constraints.enum``.

    Mutates ``schema_obj`` in place. After ``$ref`` resolution any field
    that has a ``categories`` payload but no explicit ``constraints.enum``
    gets ``constraints.enum`` populated with the scalar values, so that
    downstream validators see a concrete enum regardless of where the
    values originally came from.
    """
    fields = schema_obj.get("fields")
    if not isinstance(fields, list):
        return
    for field in fields:
        if not isinstance(field, dict):
            continue
        cats = field.get("categories")
        if cats is None:
            continue
        values = _category_values(cats)
        if values is None:
            continue
        constraints = field.setdefault("constraints", {})
        if not isinstance(constraints, dict):
            continue
        if "enum" not in constraints:
            constraints["enum"] = values


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_schema(
    source: str | Path | dict[str, Any],
    *,
    shared_categories: dict[str, Any] | None = None,
    base: str | None = None,
) -> Schema:
    """Load a single Frictionless table schema.

    Args:
        source: A path, URL, or already-parsed dict.
        shared_categories: Optional pre-loaded ``shared_categories.json``
            content keyed by category name. When provided, any
            ``categories`` payload referencing it via ``$ref`` is
            resolved before parsing.
        base: Optional base directory for resolving relative ``$ref``s.
            Required when ``source`` is a dict and the schema contains
            external references.

    Returns:
        A parsed :class:`Schema` with all references resolved and
        shared-category enums inlined into ``constraints.enum``.

    Raises:
        SpecLoadError: If the source cannot be read, parsed, or
            validated against the schema model.

    Examples:
        >>> from datagrove.spec import load_schema
        >>> s = load_schema({"fields": [{"name": "id", "type": "integer"}]})
        >>> [f.name for f in s.fields]
        ['id']
    """
    label = _source_label(source)
    if isinstance(source, dict):
        doc: Any = source
        resolved_base = base or "."
    else:
        doc, resolved_base = _read_json(source)

    cache: dict[str, Any] = {}
    if shared_categories is not None:
        # Make the shared categories addressable as if it lived next to
        # the schema. This lets a caller pre-load it once and reuse it.
        cache[_join(resolved_base, "shared_categories.json")] = shared_categories

    if not isinstance(doc, dict):
        raise SpecLoadError(f"Schema in {label} must be a JSON object, got {type(doc).__name__}")

    try:
        resolved = _resolve_refs(doc, base=resolved_base, cache=cache, self_doc=doc)
    except SpecLoadError as e:
        raise SpecLoadError(f"Failed resolving references in {label}: {e}") from e

    if not isinstance(resolved, dict):
        raise SpecLoadError(f"Schema in {label} resolved to non-object: {type(resolved).__name__}")

    _inline_shared_categories(resolved)

    try:
        return Schema.model_validate(resolved)
    except ValidationError as e:
        raise SpecLoadError(f"Invalid table schema in {label}: {e}") from e


def load_package(source: str | Path | dict[str, Any]) -> DataPackage:
    """Load a Frictionless data package.

    The package descriptor is read, all resource ``schema`` string
    references are resolved relative to the descriptor's directory,
    and any ``$ref`` references (including those into a sibling
    ``shared_categories.json``) are resolved before validation. Shared
    categories are additionally inlined into each
    :class:`~datagrove.spec.model.Field` ``constraints.enum`` list so
    downstream code sees concrete enum values.

    Args:
        source: Path to a local ``datapackage.json``, a URL, or an
            already-parsed dict. When passing a dict that uses relative
            schema references, the current working directory is used as
            the base.

    Returns:
        A parsed :class:`DataPackage`.

    Raises:
        SpecLoadError: If the source cannot be read, the JSON is
            invalid, the document is not a Frictionless data package
            (e.g. missing ``resources``), or a referenced schema fails
            to load.

    Examples:
        >>> from pathlib import Path
        >>> root = Path(__file__).resolve().parents[3] / "gmnspy" / "gmnspy" / "spec" / "0.97"
        >>> pkg = load_package(root / "datapackage.json")
        >>> pkg.name
        'gmns'
        >>> len(pkg.resources) > 20
        True
    """
    label = _source_label(source)
    if isinstance(source, dict):
        doc: Any = source
        base = "."
    else:
        doc, base = _read_json(source)

    if not isinstance(doc, dict):
        raise SpecLoadError(f"Data package in {label} must be a JSON object, got {type(doc).__name__}")

    if "resources" not in doc:
        raise SpecLoadError(f"Data package in {label} is missing required 'resources' key")
    if not isinstance(doc["resources"], list):
        raise SpecLoadError(f"Data package in {label}: 'resources' must be a list")

    # Pre-load shared_categories.json if it sits next to the descriptor so
    # the ref-resolution cache reuses one parse for all schemas.
    cache: dict[str, Any] = {}
    shared_path = _join(base, "shared_categories.json")
    try:
        shared_doc, _ = _read_json(shared_path)
    except SpecLoadError:
        shared_doc = None
    if shared_doc is not None:
        cache[shared_path] = shared_doc

    # Resolve schemas resource by resource so error messages can name the
    # offending resource.
    resources_out: list[dict[str, Any]] = []
    for idx, raw_resource in enumerate(doc["resources"]):
        if not isinstance(raw_resource, dict):
            raise SpecLoadError(f"{label}: resources[{idx}] is not a JSON object")
        resource = dict(raw_resource)
        schema_ref = resource.get("schema")
        if isinstance(schema_ref, str):
            schema_path = _join(base, schema_ref)
            try:
                schema_doc, schema_base = _read_json(schema_path)
            except SpecLoadError as e:
                rname = resource.get("name", f"<index {idx}>")
                raise SpecLoadError(f"{label}: failed to load schema for resource {rname!r}: {e}") from e
            resolved_schema = _resolve_refs(schema_doc, base=schema_base, cache=cache, self_doc=schema_doc)
            if isinstance(resolved_schema, dict):
                _inline_shared_categories(resolved_schema)
            resource["schema"] = resolved_schema
        elif isinstance(schema_ref, dict):
            resolved_schema = _resolve_refs(schema_ref, base=base, cache=cache, self_doc=schema_ref)
            if isinstance(resolved_schema, dict):
                _inline_shared_categories(resolved_schema)
            resource["schema"] = resolved_schema
        # else: schema is None or already a Schema instance — leave alone
        resources_out.append(resource)

    package_doc = dict(doc)
    package_doc["resources"] = resources_out

    try:
        return DataPackage.model_validate(package_doc)
    except ValidationError as e:
        raise SpecLoadError(f"Invalid data package in {label}: {e}") from e
