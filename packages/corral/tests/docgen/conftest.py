"""Fixtures for docgen tests.

Reuses the vendored GMNS 0.97 spec under ``packages/netstead/netstead/spec/``
the same way the corral.spec tests do — corral itself never
imports netstead, the test suite only reads its files from disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
GMNS_SPEC_ROOT = REPO_ROOT / "packages" / "netstead" / "netstead" / "spec"


@pytest.fixture(scope="session")
def spec_097_dir() -> Path:
    p = GMNS_SPEC_ROOT / "0.97"
    assert p.exists(), f"vendored GMNS 0.97 spec not found at {p}"
    return p


@pytest.fixture(scope="session")
def snapshots_dir() -> Path:
    return Path(__file__).parent / "snapshots"
