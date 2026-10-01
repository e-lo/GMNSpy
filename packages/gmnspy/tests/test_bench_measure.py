"""Unit tests for the benchmark capture primitives (gmnspy.bench.measure)."""

from __future__ import annotations

import pandas as pd
import pytest
from gmnspy.bench import measure


def test_time_call_returns_result_and_nonnegative_sample():
    result, sample = measure.time_call(lambda: sum(range(100)))
    assert result == 4950
    assert sample.wall_seconds >= 0.0
    assert sample.cpu_seconds >= 0.0


def test_memory_call_reports_python_heap_peak():
    result, sample = measure.memory_call(lambda: [0] * 500_000)
    assert len(result) == 500_000
    assert sample.py_heap_peak_mb is not None
    assert sample.py_heap_peak_mb > 0.0
    # peak_rss_mb may be None when psutil is absent, but must be numeric otherwise.
    assert sample.peak_rss_mb is None or isinstance(sample.peak_rss_mb, float)


def test_repeat_wall_seconds_count_and_validation():
    samples = measure.repeat_wall_seconds(lambda: None, repeats=4)
    assert len(samples) == 4
    assert all(s >= 0.0 for s in samples)
    with pytest.raises(ValueError):
        measure.repeat_wall_seconds(lambda: None, repeats=0)


def test_summarize_seconds_statistics():
    summary = measure.summarize_seconds([0.3, 0.1, 0.2])
    assert summary == {"median": 0.2, "min": 0.1, "mean": 0.2, "n": 3}


def test_summarize_seconds_requires_samples():
    with pytest.raises(ValueError):
        measure.summarize_seconds([])


@pytest.mark.parametrize(
    ("raw", "system", "expected"),
    [
        (1_000_000, "Darwin", 1.0),  # macOS ru_maxrss is bytes
        (1024, "Linux", 1.049),  # Linux ru_maxrss is KiB
    ],
)
def test_maxrss_to_mb_platform_normalization(raw, system, expected):
    assert measure.maxrss_to_mb(raw, platform_system=system) == expected


def test_frame_memory_mb_pandas_deep():
    frame = pd.DataFrame({"name": ["a" * 100] * 1000, "x": range(1000)})
    size = measure.frame_memory_mb(frame)
    assert size is not None and size > 0.0


def test_frame_memory_mb_unrecognized_returns_none():
    assert measure.frame_memory_mb(object()) is None
