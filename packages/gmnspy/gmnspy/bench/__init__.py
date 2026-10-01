"""Benchmark harness for gmnspy (time + peak memory across the DuckDB path).

Three layers, kept dependency-light (stdlib capture + optional ``psutil``):

- :mod:`gmnspy.bench.measure` — time / memory capture primitives (pure).
- :mod:`gmnspy.bench.report` — result records + JSON / CSV / Markdown renderers (pure).
- :mod:`gmnspy.bench.fixtures` — the size-tier (S/M/L) fixture + selection-case registry.
- :mod:`gmnspy.bench.suite` — the macro runner over network-create / selection / viz-pack.

Run it via the CLI: ``gmnspy bench-suite`` (see :mod:`gmnspy.cli.commands.bench`).

DuckDB (via ibis) is the single compute engine; pandas / polars / pyarrow are
I/O formats, so there is no engine axis — the suite measures the DuckDB path and
the binary network store format.
"""

from __future__ import annotations

from .measure import (
    MemorySample,
    TimeSample,
    frame_memory_mb,
    memory_call,
    repeat_wall_seconds,
    summarize_seconds,
    time_call,
)
from .report import (
    BenchResult,
    build_document,
    env_block,
    render_csv,
    render_json,
    render_markdown,
)

__all__ = [
    "BenchResult",
    "MemorySample",
    "TimeSample",
    "build_document",
    "env_block",
    "frame_memory_mb",
    "memory_call",
    "render_csv",
    "render_json",
    "render_markdown",
    "repeat_wall_seconds",
    "summarize_seconds",
    "time_call",
]
