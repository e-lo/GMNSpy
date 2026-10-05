"""Benchmark fixture registry (size tiers S / M / L) plus selection cases.

Fixture *definitions* are externalized to ``benchmarks/fixtures.toml`` at the
repo root (a maintained data file, discovered by walking up from the current
directory or this module). When that file is absent — e.g. in an installed
wheel with no checkout — a built-in default covering the two bundled fixtures
is used, so the suite still runs.

The S/M fixtures ship inside the wheel (``netstead.fixtures.leavenworth`` /
``rdu_i40``); their on-disk paths are resolved from the package. The L tier is
never committed: it is resolved from the ``NETSTEAD_BENCH_LARGE`` environment
variable (a GMNS package dir or ``.duckdb``) or ``NETSTEAD_BENCH_LARGE_BBOX``
(an OSM bbox for a live build).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "FixtureSpec",
    "SelectionCase",
    "default_registry",
    "load_registry",
    "resolve_fixtures",
]

#: Env var naming a committed-free large (L) GMNS package dir or .duckdb file.
LARGE_ENV_VAR = "NETSTEAD_BENCH_LARGE"
#: Env var naming an OSM bbox ("west,south,east,north") for a live L build.
LARGE_BBOX_ENV_VAR = "NETSTEAD_BENCH_LARGE_BBOX"


@dataclass(frozen=True)
class SelectionCase:
    """A versioned selection utterance plus its short case name."""

    case: str
    utterance: str


@dataclass(frozen=True)
class FixtureSpec:
    """A resolved fixture: a tier, its storage formats, and selection cases.

    Attributes:
        id: Fixture id (``leavenworth`` / ``rdu_i40`` / ``large``).
        tier: Size tier (``S`` / ``M`` / ``L``).
        formats: Storage formats available for the network-create sweep.
        source_dirs: Resolved ``{format: path}`` for file-based loads (may be
            empty for an OSM-only L entry).
        bbox: OSM bounding box for a live build, or ``None``.
        expected_links: Expected link count (correctness co-assertion) or ``None``.
        expected_nodes: Expected node count or ``None``.
        selections: The versioned selection cases to resolve.
    """

    id: str
    tier: str
    formats: tuple[str, ...]
    source_dirs: dict[str, Path] = field(default_factory=dict)
    bbox: tuple[float, ...] | None = None
    expected_links: int | None = None
    expected_nodes: int | None = None
    selections: tuple[SelectionCase, ...] = ()

    def primary_source(self) -> Path | None:
        """Return the preferred load path (parquet > duckdb > csv), or ``None``."""
        for preferred in ("parquet", "duckdb", "csv"):
            if preferred in self.source_dirs:
                return self.source_dirs[preferred]
        return next(iter(self.source_dirs.values()), None)


def default_registry() -> dict:
    """Return the built-in fixture registry (fallback when no toml is found).

    Returns:
        A dict mirroring ``benchmarks/fixtures.toml`` for the two bundled
        fixtures plus the L-tier env-var config.

    Examples:
        >>> reg = default_registry()
        >>> [f["id"] for f in reg["fixture"]]
        ['leavenworth', 'rdu_i40']
    """
    return {
        "schema_version": "1",
        "fixture": [
            {
                "id": "leavenworth",
                "tier": "S",
                "formats": ["csv", "parquet", "duckdb"],
                "expected_links": 339,
                "expected_nodes": 121,
                "selections": [
                    {"case": "name_match", "utterance": "Benton Street"},
                    {"case": "name_match_2", "utterance": "Ski Hill Drive"},
                    {"case": "no_match", "utterance": "Nonexistent Road 999"},
                ],
            },
            {
                "id": "rdu_i40",
                "tier": "M",
                "formats": ["csv", "parquet"],
                "expected_links": 178,
                "expected_nodes": 143,
                "selections": [
                    {"case": "ref_match", "utterance": "I 40"},
                    {"case": "direction", "utterance": "I 40 EB"},
                    {
                        "case": "between_anchors",
                        "utterance": "I 40 between South Miami Boulevard and Page Road",
                    },
                    {"case": "no_match", "utterance": "Nonexistent Road 999"},
                ],
            },
        ],
        "large": {
            "id": "large",
            "tier": "L",
            "env_var": LARGE_ENV_VAR,
            "bbox_env_var": LARGE_BBOX_ENV_VAR,
            "selections": [
                {"case": "ref_match", "utterance": "I 40"},
                {"case": "no_match", "utterance": "Nonexistent Road 999"},
            ],
        },
    }


def _find_fixtures_toml() -> Path | None:
    """Walk up from cwd and this module looking for ``benchmarks/fixtures.toml``."""
    starts = [Path.cwd(), Path(__file__).resolve().parent]
    for start in starts:
        for directory in (start, *start.parents):
            candidate = directory / "benchmarks" / "fixtures.toml"
            if candidate.is_file():
                return candidate
    return None


def load_registry(path: str | Path | None = None) -> dict:
    """Load the fixture registry from a toml file, or the built-in default.

    Args:
        path: Explicit path to a ``fixtures.toml``; when ``None`` the repo-root
            file is searched for, falling back to :func:`default_registry`.

    Returns:
        The parsed registry dict.

    Examples:
        >>> reg = load_registry()
        >>> "fixture" in reg
        True
    """
    toml_path = Path(path) if path is not None else _find_fixtures_toml()
    if toml_path is None:
        return default_registry()
    with toml_path.open("rb") as handle:
        return tomllib.load(handle)


def _bundled_source_dirs(fixture_id: str, formats: tuple[str, ...]) -> dict[str, Path]:
    """Resolve on-disk paths for a bundled fixture's requested formats."""
    from netstead import fixtures as _fixtures  # local import: keep module import cheap

    root = Path(_fixtures.__file__).resolve().parent / fixture_id
    resolved: dict[str, Path] = {}
    for fmt in formats:
        candidate = root / f"{fixture_id}.duckdb" if fmt == "duckdb" else root / fmt
        if candidate.exists():
            resolved[fmt] = candidate
    return resolved


def _parse_bbox(raw: str) -> tuple[float, ...]:
    """Parse a 'west,south,east,north' env value into a float tuple."""
    return tuple(float(part) for part in raw.split(","))


def _selection_cases(entry: dict) -> tuple[SelectionCase, ...]:
    """Build the SelectionCase tuple from a registry entry."""
    return tuple(SelectionCase(case=s["case"], utterance=s["utterance"]) for s in entry.get("selections", []))


def _resolve_large(entry: dict) -> FixtureSpec | None:
    """Resolve the L-tier spec from env vars, or ``None`` when unconfigured."""
    env_var = entry.get("env_var", LARGE_ENV_VAR)
    bbox_env_var = entry.get("bbox_env_var", LARGE_BBOX_ENV_VAR)
    source_dirs: dict[str, Path] = {}
    formats: tuple[str, ...] = ()
    raw_path = os.environ.get(env_var)
    if raw_path:
        path = Path(raw_path)
        if path.exists():
            fmt = "duckdb" if path.suffix == ".duckdb" else "dir"
            source_dirs = {fmt: path}
            formats = (fmt,)
    bbox = None
    raw_bbox = os.environ.get(bbox_env_var)
    if raw_bbox:
        bbox = _parse_bbox(raw_bbox)
    if not source_dirs and bbox is None:
        return None
    return FixtureSpec(
        id=entry.get("id", "large"),
        tier=entry.get("tier", "L"),
        formats=formats,
        source_dirs=source_dirs,
        bbox=bbox,
        selections=_selection_cases(entry),
    )


def resolve_fixtures(sizes: tuple[str, ...] = ("S", "M"), *, path: str | Path | None = None) -> list[FixtureSpec]:
    """Resolve the requested size tiers into concrete :class:`FixtureSpec`s.

    Fixtures whose source cannot be resolved (e.g. an L tier with no env var
    configured) are skipped cleanly, mirroring how the OSM smoke test skips
    engines whose extra is absent.

    Args:
        sizes: The tiers to include (any of ``S`` / ``M`` / ``L``).
        path: Optional explicit ``fixtures.toml`` path.

    Returns:
        A list of resolved specs, in registry order.

    Examples:
        >>> specs = resolve_fixtures(("S",))
        >>> [s.id for s in specs]
        ['leavenworth']
    """
    registry = load_registry(path)
    wanted = {size.upper() for size in sizes}
    specs: list[FixtureSpec] = []

    for entry in registry.get("fixture", []):
        if entry.get("tier") not in wanted:
            continue
        formats = tuple(entry.get("formats", []))
        source_dirs = _bundled_source_dirs(entry["id"], formats)
        if not source_dirs:
            continue  # bundled fixture files missing — skip cleanly
        specs.append(
            FixtureSpec(
                id=entry["id"],
                tier=entry["tier"],
                formats=tuple(source_dirs),
                source_dirs=source_dirs,
                expected_links=entry.get("expected_links"),
                expected_nodes=entry.get("expected_nodes"),
                selections=_selection_cases(entry),
            )
        )

    large_entry = registry.get("large")
    if large_entry and large_entry.get("tier", "L") in wanted:
        large_spec = _resolve_large(large_entry)
        if large_spec is not None:
            specs.append(large_spec)

    return specs
