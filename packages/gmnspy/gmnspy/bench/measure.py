"""Time and peak-memory capture primitives for the benchmark harness.

Dependency-light by design: wall-clock / CPU time and the Python-heap peak
come from the stdlib (:mod:`time`, :mod:`tracemalloc`); process-resident-set
size (RSS) uses :mod:`psutil` when it is installed and degrades to ``None``
when it is not.

Timing and memory are captured in **separate passes** — ``tracemalloc`` and
RSS sampling perturb wall-clock, so :func:`time_call` and :func:`memory_call`
are never combined in one measurement. The DuckDB engine keeps data in its own
buffer manager (out of the Python heap), so ``tracemalloc`` reports close to
zero for it and RSS is the only honest memory signal; see the suite's emitted
notes.
"""

from __future__ import annotations

import gc
import statistics
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

__all__ = [
    "MemorySample",
    "TimeSample",
    "frame_memory_mb",
    "maxrss_to_mb",
    "memory_call",
    "repeat_wall_seconds",
    "summarize_seconds",
    "time_call",
]

T = TypeVar("T")

try:  # psutil is optional — the harness still works (RSS reported as None) without it.
    import psutil

    _PROCESS: Any | None = psutil.Process()
except Exception:  # pragma: no cover - exercised only on installs without psutil
    _PROCESS = None


@dataclass(frozen=True)
class TimeSample:
    """Wall-clock and CPU seconds for a single timed call.

    The gap between ``wall_seconds`` and ``cpu_seconds`` reveals I/O wait
    (e.g. an OSM fetch) and work done on DuckDB's own threads.
    """

    wall_seconds: float
    cpu_seconds: float


@dataclass(frozen=True)
class MemorySample:
    """Peak memory for a single call; ``None`` where a source is unavailable.

    ``py_heap_peak_mb`` is the ``tracemalloc`` high-water mark (Python
    allocations only); ``peak_rss_mb`` is the process-RSS delta around the
    call (the only metric that sees DuckDB's out-of-heap arena), or ``None``
    when :mod:`psutil` is absent.
    """

    py_heap_peak_mb: float | None
    peak_rss_mb: float | None


def time_call(fn: Callable[[], T]) -> tuple[T, TimeSample]:
    """Run ``fn`` once and return ``(result, TimeSample)``.

    A :func:`gc.collect` runs first so a prior test's garbage does not land
    in this measurement. Uses :func:`time.perf_counter` (monotonic wall) and
    :func:`time.process_time` (CPU).

    Args:
        fn: A zero-argument callable to time.

    Returns:
        The callable's return value paired with its :class:`TimeSample`.

    Examples:
        >>> result, sample = time_call(lambda: sum(range(1000)))
        >>> result
        499500
        >>> sample.wall_seconds >= 0.0 and sample.cpu_seconds >= 0.0
        True
    """
    gc.collect()
    wall0 = time.perf_counter()
    cpu0 = time.process_time()
    result = fn()
    wall = time.perf_counter() - wall0
    cpu = time.process_time() - cpu0
    return result, TimeSample(round(wall, 6), round(cpu, 6))


def memory_call(fn: Callable[[], T]) -> tuple[T, MemorySample]:
    """Run ``fn`` once under memory instrumentation; return ``(result, MemorySample)``.

    Captures the ``tracemalloc`` Python-heap peak and the process-RSS delta
    (via :mod:`psutil` when available). This perturbs wall-clock, so it must
    be a *separate* pass from :func:`time_call`.

    Args:
        fn: A zero-argument callable to measure.

    Returns:
        The callable's return value paired with its :class:`MemorySample`.

    Examples:
        >>> result, sample = memory_call(lambda: [0] * 1_000_000)
        >>> sample.py_heap_peak_mb > 0.0
        True
    """
    gc.collect()
    rss_before = _rss_mb()
    tracemalloc.start()
    result = fn()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_after = _rss_mb()
    rss_delta = round(rss_after - rss_before, 2) if rss_before is not None and rss_after is not None else None
    return result, MemorySample(round(peak / 1e6, 3), rss_delta)


def _rss_mb() -> float | None:
    """Current process RSS in MB, or ``None`` when psutil is unavailable."""
    if _PROCESS is None:
        return None
    try:
        return _PROCESS.memory_info().rss / 1e6
    except Exception:  # pragma: no cover - psutil edge (process gone)
        return None


def repeat_wall_seconds(fn: Callable[[], Any], repeats: int = 5) -> list[float]:
    """Return a list of wall-clock seconds from running ``fn`` ``repeats`` times.

    Args:
        fn: A zero-argument callable to time repeatedly.
        repeats: Number of repetitions (must be >= 1).

    Returns:
        One wall-clock figure per repetition, in call order.

    Raises:
        ValueError: If ``repeats`` is less than 1.

    Examples:
        >>> samples = repeat_wall_seconds(lambda: None, repeats=3)
        >>> len(samples)
        3
    """
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    return [time_call(fn)[1].wall_seconds for _ in range(repeats)]


def summarize_seconds(samples: list[float]) -> dict[str, float]:
    """Summarize wall-clock samples into median / min / mean / n.

    The stable macro signal is ``min`` (least-contended run) and ``median``
    (outlier-resistant); absolute numbers are noisy, so callers lead with
    these rather than a single reading.

    Args:
        samples: One or more wall-clock readings in seconds.

    Returns:
        A dict with ``median``, ``min``, ``mean`` (seconds) and integer ``n``.

    Raises:
        ValueError: If ``samples`` is empty.

    Examples:
        >>> summarize_seconds([0.2, 0.1, 0.3])
        {'median': 0.2, 'min': 0.1, 'mean': 0.2, 'n': 3}
    """
    if not samples:
        raise ValueError("summarize_seconds requires at least one sample")
    return {
        "median": round(statistics.median(samples), 6),
        "min": round(min(samples), 6),
        "mean": round(statistics.fmean(samples), 6),
        "n": len(samples),
    }


def maxrss_to_mb(ru_maxrss: int, *, platform_system: str) -> float:
    """Normalize :func:`resource.getrusage` ``ru_maxrss`` to MB across platforms.

    ``ru_maxrss`` is bytes on macOS (``Darwin``) but KiB on Linux — a classic
    cross-platform footgun. This converts either to MB.

    Args:
        ru_maxrss: The raw ``ru_maxrss`` value from ``resource.getrusage``.
        platform_system: ``platform.system()`` (e.g. ``"Darwin"``, ``"Linux"``).

    Returns:
        The high-water mark in MB.

    Examples:
        >>> maxrss_to_mb(1_000_000, platform_system="Darwin")
        1.0
        >>> maxrss_to_mb(1024, platform_system="Linux")
        1.049
    """
    if platform_system == "Darwin":
        return round(ru_maxrss / 1e6, 3)
    return round(ru_maxrss * 1024 / 1e6, 3)


def frame_memory_mb(frame: Any) -> float | None:
    """Return the materialized in-RAM size of a dataframe in MB.

    Engine-comparable "how big is the network in RAM" number. pandas uses
    ``memory_usage(deep=True)`` (``deep`` is required or object / WKT-geometry
    columns undercount by ~10x); polars uses ``estimated_size``; an Arrow
    table uses ``nbytes``. Returns ``None`` for an unrecognized frame type.

    Args:
        frame: A pandas / polars dataframe or a pyarrow table.

    Returns:
        Size in MB, or ``None`` if the frame type is not recognized.

    Examples:
        >>> import pandas as pd
        >>> frame_memory_mb(pd.DataFrame({"a": range(100_000)})) > 0.0
        True
    """
    if hasattr(frame, "memory_usage"):
        try:
            return round(float(frame.memory_usage(deep=True).sum()) / 1e6, 3)
        except Exception:  # pragma: no cover - defensive against exotic frames
            return None
    if hasattr(frame, "estimated_size"):
        try:
            return round(float(frame.estimated_size()) / 1e6, 3)
        except Exception:  # pragma: no cover
            return None
    if hasattr(frame, "nbytes"):
        try:
            return round(float(frame.nbytes) / 1e6, 3)
        except Exception:  # pragma: no cover
            return None
    return None
