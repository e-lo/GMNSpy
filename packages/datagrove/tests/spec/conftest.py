"""Test fixtures for the datagrove.spec test suite.

The vendored GMNS spec under ``packages/gmnspy/gmnspy/spec/`` is used as
real-world fixture data. Datagrove itself never imports gmnspy; the
test suite only reads its files from disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
GMNS_SPEC_ROOT = REPO_ROOT / "packages" / "gmnspy" / "gmnspy" / "spec"


@pytest.fixture(scope="session")
def gmns_spec_root() -> Path:
    """Absolute path to the vendored GMNS spec root."""
    assert GMNS_SPEC_ROOT.exists(), f"vendored GMNS spec not found at {GMNS_SPEC_ROOT}"
    return GMNS_SPEC_ROOT


@pytest.fixture(scope="session")
def spec_097_dir(gmns_spec_root: Path) -> Path:
    return gmns_spec_root / "0.97"


@pytest.fixture(scope="session")
def spec_096_dir(gmns_spec_root: Path) -> Path:
    return gmns_spec_root / "0.96"


@pytest.fixture(scope="session")
def spec_095_dir(gmns_spec_root: Path) -> Path:
    return gmns_spec_root / "0.95"
