"""The ``BuildNetwork`` pipeline, staged for a background job: plan → estimate → query → convert → write.

The session's job function calls these in order and owns the final open + register (which needs the
session lock). Each stage boundary is a :class:`~gmnspy.workbench.jobs.JobContext` checkpoint, so a
cancel stops the build between stages. Query, convert, and write run on a private
:class:`~datagrove.engines.ibis_engine.IbisEngine` that the caller closes afterwards, so a build never
shares a DuckDB connection with the networks the browser is reading.

A build never leaves a partial output behind and never overwrites one: it writes into a hidden
staging sibling of the destination (:func:`staging`), and only :func:`promote` moves the finished
output to its final name. The staging path is removed on any failure, including a cancel.

The OSM/Overture modules are imported at run time via :func:`~gmnspy.workbench.extras.optional_module`:
they need the ``[osm]`` / ``[overture]`` extras.
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from datagrove.engines.ibis_engine import IbisEngine

from gmnspy._network_build import network_from_records
from gmnspy.config import Settings
from gmnspy.network import Network
from gmnspy.overture.layout import LOCAL_SNAPSHOT_FILES, is_local_snapshot

from .actions import BuildNetwork
from .errors import ActionError
from .estimate import Estimate, SourceKind, count_osm, count_overture, estimate_build
from .extras import optional_module
from .jobs import JobContext
from .paths import classify_source

__all__ = [
    "WORLD_BBOX",
    "BuildPlan",
    "estimate_for",
    "fetch_and_convert",
    "plan_build",
    "promote",
    "staging",
    "write_output",
]

#: The whole world: the Overture read bbox when a local snapshot is imported in full.
WORLD_BBOX = (-180.0, -90.0, 180.0, 90.0)
_SUFFIX = {"parquet": "", "csv": "", "duckdb": ".duckdb", "zip": ".zip"}
_FILE_KIND: dict[str, SourceKind] = {"osm": "osm_file", "overture": "overture_file"}
_OSM_FILE_SUFFIXES = (".osm", ".json")
Records = tuple[list[dict[str, Any]], list[dict[str, Any]]]
Tick = Callable[[str, float], None]


@dataclass(frozen=True)
class BuildPlan:
    """Resolved, checked locations for one build."""

    kind: SourceKind
    dest: Path
    input_path: Path | None


def _local(path: str, what: str, settings: Settings) -> Path:
    """``path`` resolved inside ``io.allowed_roots``; a remote URL is an :class:`ActionError`."""
    kind, target = classify_source(path, settings)
    if kind == "remote":
        raise ActionError(f"{what} must be a local path, not a URL: {path}")
    return Path(target)


def plan_build(action: BuildNetwork, settings: Settings) -> BuildPlan:
    """Check the action against the filesystem before any work: allowed roots, inputs, a free destination.

    Raises:
        PathNotAllowed: the output folder or input file is outside ``io.allowed_roots``.
        ActionError: missing output folder, existing destination, or an input of the wrong kind.
    """
    out_dir = _local(action.output_dir, "output_dir", settings)
    if not out_dir.is_dir():
        raise ActionError(f"output folder does not exist: {action.output_dir}")
    dest = out_dir / f"{action.name}{_SUFFIX[action.output_format]}"
    if dest.exists():
        raise ActionError(f"{dest} already exists; choose another name (builds never overwrite)")
    if action.input_file is None:
        return BuildPlan(kind=action.source, dest=dest, input_path=None)
    src = _local(action.input_file, "input_file", settings)
    if action.source == "osm" and not (src.is_file() and src.suffix.lower() in _OSM_FILE_SUFFIXES):
        raise ActionError(f"{action.input_file} is not a local .osm or Overpass .json file")
    if action.source == "overture" and not is_local_snapshot(src):
        raise ActionError(f"{action.input_file} is not a local Overture snapshot ({' + '.join(LOCAL_SNAPSHOT_FILES)})")
    return BuildPlan(kind=_FILE_KIND[action.source], dest=dest, input_path=src)


def _osm_options(settings: Settings) -> dict[str, Any]:
    osm_query = optional_module("gmnspy.osm.query", "osm")
    return {
        "endpoint": settings.osm.endpoint or osm_query.OVERPASS_URL,
        "user_agent": settings.osm.user_agent or osm_query.USER_AGENT,
    }


def _overture_read(action: BuildNetwork, plan: BuildPlan, settings: Settings) -> dict[str, Any]:
    """bbox, release, and data root for an Overture read (a local snapshot is read in full)."""
    overture_query = optional_module("gmnspy.overture.query", "overture")
    if plan.input_path is not None:
        bbox, data_root = WORLD_BBOX, str(plan.input_path)
    else:
        assert action.area is not None  # guaranteed by BuildNetwork's validator
        bbox, data_root = action.area.to_bbox(), settings.overture.data_root
    release = action.overture_release or settings.overture.release or overture_query.OVERTURE_RELEASE
    return {"bbox": bbox, "overture_release": release, "data_root": data_root}


def _count(action: BuildNetwork, plan: BuildPlan, settings: Settings, http: Any, engine: Any) -> int:
    if plan.input_path is not None and plan.kind == "osm_file":
        return plan.input_path.stat().st_size
    if plan.kind == "osm":
        assert action.area is not None
        return count_osm(action.area, network_type=action.network_type, http=http, **_osm_options(settings))
    read = _overture_read(action, plan, settings)
    return count_overture(read.pop("bbox"), network_type=action.network_type, engine=engine, **read)


def estimate_for(
    action: BuildNetwork, plan: BuildPlan, settings: Settings, *, http: Any = None, engine: Any = None
) -> Estimate:
    """Pre-query + cost model. Any failure becomes ``Estimate(seconds=None, basis="unavailable: ...")``."""
    own_engine = engine is None and plan.kind in ("overture", "overture_file")
    if own_engine:
        engine = IbisEngine()
    try:
        n = _count(action, plan, settings, http, engine)
    except Exception as exc:  # boundary: a failed pre-query is reported; the user may still choose to run
        return Estimate(
            seconds=None, out_bytes=None, n_elements=None, basis=f"unavailable: {type(exc).__name__}: {exc}"
        )
    finally:
        if own_engine:
            engine.close()
    return estimate_build(plan.kind, n, output_format=action.output_format)


def _osm_records(action: BuildNetwork, plan: BuildPlan, settings: Settings, http: Any, tick: Tick) -> Records:
    convert = optional_module("gmnspy.osm.convert", "osm")
    local = optional_module("gmnspy.osm.local", "osm")
    query = optional_module("gmnspy.osm.query", "osm")
    if plan.input_path is not None:
        nodes, ways = local.read_osm_file(plan.input_path, network_type=action.network_type)
    else:
        assert action.area is not None
        q = query.build_overpass_query(
            bbox=action.area.to_bbox(),
            polygon=action.area.to_polygon(),
            network_type=action.network_type,
            timeout=settings.osm.timeout,
        )
        options = {"timeout": settings.osm.timeout, "retries": settings.osm.retries, **_osm_options(settings)}
        nodes, ways = query.parse_overpass_elements(query.fetch_osm(q, session=http, **options))
    tick("convert", 0.5)
    return convert.build_node_link_tables(nodes, ways, extra_tags=action.extra_tags)


def _overture_records(action: BuildNetwork, plan: BuildPlan, settings: Settings, engine: Any, tick: Tick) -> Records:
    convert = optional_module("gmnspy.overture.convert", "overture")
    query = optional_module("gmnspy.overture.query", "overture")
    read = _overture_read(action, plan, settings)
    bbox = read.pop("bbox")
    segments = query.read_segments(
        bbox, network_type=action.network_type, extra_tags=action.extra_tags, engine=engine, **read
    )
    connectors = query.read_connectors(bbox, engine=engine, **read)
    tick("convert", 0.5)
    return convert.build_node_link_tables(segments, connectors, extra_tags=action.extra_tags)


def fetch_and_convert(
    action: BuildNetwork,
    plan: BuildPlan,
    settings: Settings,
    ctx: JobContext,
    *,
    estimate: Estimate,
    http: Any,
    engine: Any,
) -> Network:
    """Stages ``query`` and ``convert``: read the source and assemble the GMNS network on ``engine``.

    Raises:
        ActionError: the fetch/read failed, or nothing matched ``network_type`` in the area.
    """
    started = time.time()

    def tick(stage: str, progress: float) -> None:
        eta = None if estimate.seconds is None else max(estimate.seconds - (time.time() - started), 0.0)
        ctx.stage(stage, progress=progress, eta_s=eta)

    try:
        tick("query", 0.1)
        if action.source == "osm":
            node_records, link_records = _osm_records(action, plan, settings, http, tick)
        else:
            node_records, link_records = _overture_records(action, plan, settings, engine, tick)
    except (ValueError, LookupError, OSError) as exc:
        # The same set `gmnspy build` reports: bad network_type / malformed input / missing connector
        # (ValueError, LookupError) and Overpass or object-store I/O (requests' errors subclass OSError).
        raise ActionError(f"build failed: {exc}") from exc
    if not link_records:
        raise ActionError(f"nothing in this {action.source} area matched network_type={action.network_type!r}")
    return network_from_records(
        node_records,
        link_records,
        spec_version=action.spec_version or settings.io.spec_version,
        engine=engine,
        dataset_name=f"{action.source}_export",
    )


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists() or path.is_symlink():
        path.unlink(missing_ok=True)


@contextmanager
def staging(dest: Path) -> Iterator[Path]:
    """Yield a hidden sibling of ``dest`` to write into; it is removed on exit unless :func:`promote` moved it.

    The staging name keeps ``dest``'s suffix (``.partial-<id>-tiny.duckdb``), so format detection still works.
    """
    tmp = dest.with_name(f".partial-{uuid.uuid4().hex[:8]}-{dest.name}")
    try:
        yield tmp
    finally:
        _remove(tmp)


def write_output(net: Network, tmp: Path, output_format: str, ctx: JobContext) -> None:
    """Stage ``write``: persist ``net`` at the staging path ``tmp`` (from :func:`staging`).

    Raises:
        ActionError: the write failed with an ``OSError`` (the caller's :func:`staging` cleans up).
    """
    ctx.stage("write", progress=0.75)
    try:
        net.write(tmp, format=output_format)
    except OSError as exc:  # disk full, permissions: user-facing, not an internal error
        raise ActionError(f"could not write the {output_format} output: {exc}") from exc


def promote(tmp: Path, dest: Path) -> None:
    """Move the finished staging output to ``dest``; refuses (:class:`ActionError`) if ``dest`` appeared meanwhile."""
    if dest.exists() or dest.is_symlink():
        raise ActionError(f"{dest} already exists; choose another name (builds never overwrite)")
    os.replace(tmp, dest)
