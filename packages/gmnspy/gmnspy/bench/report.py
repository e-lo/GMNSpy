"""Result records and output rendering for the benchmark suite.

One canonical JSON document per run (the regression format), plus two rendered
views derived from it: a flat CSV and an advertising Markdown table. Every
document carries an ``env`` block — a benchmark without its machine is
marketing, not data.
"""

from __future__ import annotations

import csv
import io
import json
import platform
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any

__all__ = [
    "SCHEMA_VERSION",
    "BenchResult",
    "build_document",
    "env_block",
    "render_csv",
    "render_json",
    "render_markdown",
]

#: Canonical-document schema version. Bump when the JSON shape changes.
SCHEMA_VERSION = "1"

#: The honesty caveats printed with every advertising table (see the scope doc).
CAVEATS = (
    "DuckDB memory lives in its own buffer manager (out of the Python heap) and can "
    "spill to disk; `peak_rss_mb` is a partial, non-comparable signal — not pandas "
    "in-heap memory.",
    "Selection and viz-pack operate on materialized pandas frames, so their cost is "
    "the DuckDB->pandas materialize tax plus the pure-Python work, not a compute-engine "
    "comparison (DuckDB is the only compute engine).",
    "Absolute numbers are machine- and noise-dependent; compare only same-machine runs.",
)

#: Map a module name to its installed-distribution name for version probing.
_DIST_NAMES = {
    "duckdb": "duckdb",
    "ibis": "ibis-framework",
    "polars": "polars",
    "pandas": "pandas",
    "pyarrow": "pyarrow",
    "numpy": "numpy",
    "gmnspy": "gmnspy",
    "datagrove": "datagrove",
}


@dataclass
class BenchResult:
    """One measured benchmark cell.

    Attributes:
        operation: ``network_create`` / ``selection`` / ``viz_pack``.
        size: Size tier (``S`` / ``M`` / ``L``).
        label: Human key for the cell, e.g. ``"rdu_i40:parquet"`` or a case name.
        metrics: Timing figures (seconds), e.g. ``{"total_seconds": ...}``.
        mem: Memory figures, e.g. ``{"peak_rss_mb": ..., "py_heap_peak_mb": ...}``.
        counts: Correctness co-assertions, e.g. ``{"links": ..., "nodes": ...}``.
        extra: Anything else (``payload_bytes``, breakdowns, notes).
    """

    operation: str
    size: str
    label: str
    metrics: dict[str, Any] = field(default_factory=dict)
    mem: dict[str, Any] = field(default_factory=dict)
    counts: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        """Flatten this result into a single JSON-friendly record dict.

        Returns:
            A dict with ``operation`` / ``size`` / ``label`` first, the metric
            keys hoisted to the top level, and ``counts`` / ``mem`` / the extra
            keys nested or hoisted so the regression format stays readable.

        Examples:
            >>> r = BenchResult("viz_pack", "S", "leavenworth",
            ...                 metrics={"seconds_min": 0.01},
            ...                 extra={"payload_bytes": 1234})
            >>> rec = r.to_record()
            >>> rec["operation"], rec["payload_bytes"]
            ('viz_pack', 1234)
        """
        record: dict[str, Any] = {"operation": self.operation, "size": self.size, "label": self.label}
        record.update(self.metrics)
        if self.counts:
            record["counts"] = self.counts
        if self.mem:
            record["mem"] = self.mem
        record.update(self.extra)
        return record


def _probe_version(module_name: str) -> str | None:
    """Return the installed version of ``module_name``'s distribution, or ``None``."""
    dist = _DIST_NAMES.get(module_name, module_name)
    try:
        return version(dist)
    except PackageNotFoundError:
        return None


def env_block(commit: str | None = None) -> dict[str, Any]:
    """Build the environment-provenance block stamped onto every run.

    Args:
        commit: Optional git commit SHA to record.

    Returns:
        A dict with machine / processor / python / os / host, a ``versions``
        map of the key compute + I/O libraries, the ``commit``, and a UTC
        ``timestamp``.

    Examples:
        >>> env = env_block(commit="abc123")
        >>> env["commit"]
        'abc123'
        >>> "python" in env and "versions" in env
        True
    """
    return {
        "machine": platform.machine(),
        "processor": platform.processor() or platform.machine(),
        "python": platform.python_version(),
        "os": platform.platform(terse=True),
        "host": socket.gethostname(),
        "versions": {name: _probe_version(name) for name in _DIST_NAMES},
        "commit": commit,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def build_document(
    results: list[BenchResult], *, env: dict[str, Any] | None = None, commit: str | None = None
) -> dict[str, Any]:
    """Assemble the canonical run document from measured results.

    Args:
        results: The measured benchmark cells.
        env: A pre-built env block; when ``None`` one is generated.
        commit: Git SHA passed through to :func:`env_block` (ignored if ``env``
            is given).

    Returns:
        ``{"schema_version", "env", "results": [...]}``.

    Examples:
        >>> doc = build_document([], env={"host": "ci"})
        >>> doc["schema_version"], doc["results"]
        ('1', [])
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "env": env if env is not None else env_block(commit),
        "results": [r.to_record() for r in results],
    }


def render_json(document: dict[str, Any]) -> str:
    """Render the canonical document as indented JSON text.

    Args:
        document: A document from :func:`build_document`.

    Returns:
        A JSON string (2-space indent), newline-terminated.

    Examples:
        >>> import json
        >>> text = render_json({"schema_version": "1", "results": []})
        >>> json.loads(text)["schema_version"]
        '1'
    """
    return json.dumps(document, indent=2, default=str) + "\n"


def _flatten(record: dict[str, Any], *, parent: str = "") -> dict[str, Any]:
    """Flatten one record's nested dicts into dotted keys for CSV columns."""
    flat: dict[str, Any] = {}
    for key, value in record.items():
        dotted = f"{parent}.{key}" if parent else key
        if isinstance(value, dict):
            flat.update(_flatten(value, parent=dotted))
        elif isinstance(value, (list, tuple)):
            flat[dotted] = json.dumps(value, default=str)
        else:
            flat[dotted] = value
    return flat


def render_csv(records: list[dict[str, Any]]) -> str:
    """Render flattened result records as CSV text.

    The header is the union of all flattened (dotted) keys across records, in
    first-seen order; missing cells are blank.

    Args:
        records: The ``results`` list from a document (each a record dict).

    Returns:
        CSV text including a header row. Empty input yields an empty string.

    Examples:
        >>> csv_text = render_csv([{"operation": "viz_pack", "size": "S"}])
        >>> csv_text.splitlines()[0]
        'operation,size'
    """
    if not records:
        return ""
    flattened = [_flatten(r) for r in records]
    columns: list[str] = []
    for row in flattened:
        for key in row:
            if key not in columns:
                columns.append(key)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    for row in flattened:
        writer.writerow(row)
    return buffer.getvalue()


def _env_stamp(env: dict[str, Any]) -> str:
    """One-line machine + key-version stamp for the advertising table."""
    versions = env.get("versions", {})
    key_versions = ", ".join(f"{name} {versions[name]}" for name in ("gmnspy", "duckdb", "ibis") if versions.get(name))
    return f"{env.get('processor', '?')} / {env.get('os', '?')} / python {env.get('python', '?')}" + (
        f" / {key_versions}" if key_versions else ""
    )


def render_markdown(document: dict[str, Any]) -> str:
    """Render the advertising Markdown view (tables per operation + caveats).

    Args:
        document: A document from :func:`build_document`.

    Returns:
        Markdown text with one table per operation, an environment stamp, and
        the standing honesty caveats.

    Examples:
        >>> doc = {"env": {}, "results": [
        ...     {"operation": "viz_pack", "size": "S", "label": "leavenworth",
        ...      "seconds_min": 0.01, "payload_bytes": 1234}]}
        >>> md = render_markdown(doc)
        >>> "## viz_pack" in md and "leavenworth" in md
        True
    """
    env = document.get("env", {})
    results = document.get("results", [])
    lines = ["# gmnspy benchmark results", "", f"_Environment: {_env_stamp(env)}_", ""]

    by_operation: dict[str, list[dict[str, Any]]] = {}
    for record in results:
        by_operation.setdefault(record.get("operation", "?"), []).append(record)

    for operation, rows in by_operation.items():
        lines.append(f"## {operation}")
        lines.append("")
        lines.extend(_markdown_table(rows))
        lines.append("")

    lines.append("## Caveats")
    lines.append("")
    lines.extend(f"- {caveat}" for caveat in CAVEATS)
    lines.append("")
    return "\n".join(lines)


def _markdown_table(rows: list[dict[str, Any]]) -> list[str]:
    """Build a Markdown table (header + separator + rows) from flattened records."""
    flattened = [_flatten(r) for r in rows]
    columns: list[str] = []
    for row in flattened:
        for key in row:
            if key not in columns:
                columns.append(key)
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join("" if row.get(col) is None else str(row.get(col)) for col in columns) + " |"
        for row in flattened
    ]
    return [header, separator, *body]
