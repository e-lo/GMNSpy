"""GMNS-aware CLI — extends :mod:`datagrove.cli.app` with GMNS commands.

Entry point: ``gmnspy = gmnspy.cli.app:app``. Starts from
:func:`datagrove.cli.app.build_app` (so users get every generic
command — ``validate``, ``info``, …) then layers GMNS-specific ones
on top:

* ``info`` — GMNS-aware: prints :attr:`Network.spec_version` + the
  named-table summary (links, nodes, segments, …) rather than the
  generic resource list.
* ``quality`` — runs the :mod:`gmnspy.quality` rule pack.
* ``spec list`` / ``spec diff`` — introspect vendored GMNS spec
  versions (task 4.3 / issue #85).
* ``doctor`` — environment + spec smoke checks (task 4.5 / issue #87).

Every command keeps the ``--json`` + ``--yes`` contract from
:mod:`datagrove.cli` so an agent that learned the datagrove surface
already knows the GMNS surface.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
from pathlib import Path

import typer
from datagrove.cli.app import build_app
from datagrove.cli.render import render_dict, render_issues, render_table
from datagrove.quality import RuleConfig, run_quality

from gmnspy import Network
from gmnspy.quality import register_all
from gmnspy.spec import DEFAULT_SPEC, SUPPORTED_SPECS, load_gmns_spec

__all__ = ["app"]

logger = logging.getLogger(__name__)


def _build_gmnspy_app() -> typer.Typer:
    """Return the GMNS-aware typer app, layered on top of the datagrove generic app.

    Pulled out as a private factory so tests can build a fresh app
    rather than relying on the module-level singleton.
    """
    gmnspy_app = build_app()
    # Stamp a gmnspy-flavoured help string over the datagrove default
    # so ``gmnspy --help`` introduces itself correctly.
    gmnspy_app.info.help = (
        "gmnspy — GMNS network CLI. Inherits the generic datagrove commands "
        "(validate, info) and adds GMNS-aware overrides + the data-quality "
        "rule pack. Add --json to any command for machine-readable output."
    )

    # Replace the generic ``info`` with a GMNS-aware one. typer's
    # second registration under the same name wins, so existing
    # behaviour for end users is unchanged.
    @gmnspy_app.command(name="info")
    def gmns_info(
        source: Path = typer.Argument(..., help="Path / URL to a GMNS network."),
        spec_version: str = typer.Option(None, "--spec", help="Override the default GMNS spec version."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout instead of rich panels."),
    ) -> None:
        """Print GMNS-aware metadata about ``source`` — spec version + table summary."""
        net = Network.from_source(source, spec_version=spec_version)
        data = {
            "name": net.spec.name,
            "source": str(source),
            "spec_version": net.spec_version,
            "engine": type(net.engine).__name__,
            "links": _safe_count(net, "link"),
            "nodes": _safe_count(net, "node"),
            "table_count": len(net.tables),
            "tables": sorted(net.tables.keys()),
        }
        render_dict(data, json_out=json_out, title=f"gmnspy info: {source}")

    @gmnspy_app.command(name="quality")
    def quality_cmd(
        source: Path = typer.Argument(..., help="Path / URL to a GMNS network."),
        spec_version: str = typer.Option(None, "--spec", help="Override the default GMNS spec version."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout instead of rich panels."),
    ) -> None:
        """Run the GMNS data-quality rule pack against ``source``.

        Each rule emits Severity.WARNING / INFO findings with category
        DATA_QUALITY. The output is a ValidationReport (rendered as a
        rich table or JSON document per ``--json``).
        """
        # Ensure rules are registered even when the entry point isn't
        # picked up (e.g. editable installs that skipped re-install).
        register_all()
        net = Network.from_source(source, spec_version=spec_version)
        report = run_quality(net, config={code: RuleConfig() for code in []})
        render_issues(report.issues, json_out=json_out, header=f"quality report: {source}")
        # Quality issues are WARNING/INFO by default — never exit non-zero
        # from this command. Callers wanting hard fail use --json + check
        # for non-empty issues themselves.

    # ------------------------------------------------------------------
    # spec — vendored GMNS spec introspection (task 4.3 / issue #85)
    # ------------------------------------------------------------------
    spec_app = typer.Typer(no_args_is_help=True, help="GMNS spec utilities — list and diff vendored versions.")
    gmnspy_app.add_typer(spec_app, name="spec")

    @spec_app.command(name="list")
    def spec_list(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of a rich table."),
    ) -> None:
        """List the GMNS spec versions vendored in this build of gmnspy."""
        data = {"default": DEFAULT_SPEC, "supported": list(SUPPORTED_SPECS)}
        render_dict(data, json_out=json_out, title="gmnspy spec list")

    @spec_app.command(name="diff")
    def spec_diff(
        v1: str = typer.Argument(..., help="Baseline GMNS spec version (e.g. 0.96)."),
        v2: str = typer.Argument(..., help="Comparison GMNS spec version (e.g. 0.97)."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of a rich summary."),
    ) -> None:
        """Diff two vendored GMNS spec versions resource-by-resource."""
        diff = _diff_specs(v1, v2)
        if json_out:
            render_dict(diff, json_out=True)
            return
        # Human-readable summary: one row per "changed" resource plus
        # bare lists for added/removed. Keep it compact — the JSON
        # payload is the authoritative shape.
        summary = {
            "v1": diff["v1"],
            "v2": diff["v2"],
            "added_resources": ", ".join(diff["added_resources"]) or "(none)",
            "removed_resources": ", ".join(diff["removed_resources"]) or "(none)",
            "changed_resources": ", ".join(r["name"] for r in diff["changed_resources"]) or "(none)",
        }
        render_dict(summary, json_out=False, title=f"spec diff: {v1} -> {v2}")

    # ------------------------------------------------------------------
    # doctor — environment diagnostic (task 4.5 / issue #87)
    # ------------------------------------------------------------------
    @gmnspy_app.command(name="doctor")
    def doctor(
        json_out: bool = typer.Option(False, "--json", help="Emit checks as a JSON array."),
    ) -> None:
        """Run environment + spec smoke checks. Exits non-zero on any failure."""
        checks: list[dict[str, object]] = [
            _check_python_version(),
            *_check_optional_extras(),
            *_check_spec_versions(),
            _check_leavenworth_loads(),
            _check_auto_approve_env(),
        ]
        render_table(checks, json_out=json_out, title="gmnspy doctor")
        if any(not c["ok"] for c in checks):
            raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # bench — read/validate/connectivity timing (task 4.4 / issue #86)
    # ------------------------------------------------------------------
    @gmnspy_app.command(name="bench")
    def bench(
        source: Path = typer.Argument(..., help="Path/URL to a GMNS network."),
        engine: str = typer.Option(None, "--engine", help="ibis/pandas/polars (default: ibis)."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout."),
    ) -> None:
        """Run read/validate/connectivity benchmarks; print timings.

        Phases timed (each via time.perf_counter):

        * ``load`` — :meth:`Network.from_source`.
        * ``validate`` — :meth:`Network.validate` (structural/schema only).
        * ``links_count`` + ``nodes_count`` — trivial materialisation sanity.
        * ``is_connected`` — full graph index build + component count
          (skipped silently when the ``[clean]`` extra is missing).

        Output is a dict with ``phases`` (list of ``{phase, seconds}``) and
        a ``total_seconds`` summary. ``--json`` writes the dict to stdout for
        machine consumption; otherwise rendered via the standard rich panel.
        """
        import time

        eng = _resolve_engine(engine)

        timings: list[dict] = []

        def _time(phase: str, fn):
            t0 = time.perf_counter()
            result = fn()
            timings.append({"phase": phase, "seconds": round(time.perf_counter() - t0, 4)})
            return result

        net = _time("load", lambda: Network.from_source(source, engine=eng))
        _time("validate", lambda: net.validate(foreign_keys=False, sync_state=False))
        _time("links_count", lambda: net.links.count())
        _time("nodes_count", lambda: net.nodes.count())
        # Connectivity needs the [clean] extra (igraph). Skip silently if not available.
        try:
            from gmnspy.semantics import is_connected

            _time("is_connected", lambda: is_connected(net))
        except ImportError:
            timings.append({"phase": "is_connected", "seconds": None, "skipped": "igraph not installed"})

        total = round(sum(t["seconds"] for t in timings if t.get("seconds") is not None), 4)
        data = {
            "source": str(source),
            "engine": type(eng).__name__,
            "total_seconds": total,
            "phases": timings,
        }
        render_dict(data, json_out=json_out, title=f"bench: {source}")

    # ------------------------------------------------------------------
    # server — self-hostable FastAPI app (task 4.10 / issue #91)
    # ------------------------------------------------------------------
    server_app = typer.Typer(no_args_is_help=True, help="Run the gmnspy self-hostable HTTP server.")
    gmnspy_app.add_typer(server_app, name="server")

    @server_app.command(name="run")
    def server_run(
        config: Path = typer.Option(None, "--config", "-c", help="Path to server config (YAML/JSON)."),
        bind: str = typer.Option(None, "--bind", help="Override config bind address (default 127.0.0.1)."),
        port: int = typer.Option(None, "--port", help="Override config port (default 8000)."),
    ) -> None:
        """Start the gmnspy HTTP server with config from ``--config``.

        Reads :class:`datagrove.api.ServerSettings` from the config
        file (or uses defaults — localhost, no packages, auth=bearer
        with no token, which fails fast on first request).

        The CLI ``--bind`` / ``--port`` flags override the matching
        config keys for one-off testing without editing the file.
        """
        # Optional-extra modules go through importlib so the
        # static contract `gmnspy.cli must not import gmnspy.server`
        # holds. The import-linter scans static imports only; runtime
        # discovery via importlib is the architecture-blessed way to
        # thread a CLI entry point into an optional submodule.
        try:
            server_module = importlib.import_module("gmnspy.server")
            api_module = importlib.import_module("datagrove.api")
            uvicorn = importlib.import_module("uvicorn")
        except ImportError as e:
            typer.secho(
                f"gmnspy server requires the [server] extra: pip install 'gmnspy[server]' ({e})",
                fg="red",
                err=True,
            )
            raise typer.Exit(code=1) from None

        settings = api_module.load_settings(config) if config else api_module.ServerSettings()
        if bind is not None:
            settings.bind = bind
        if port is not None:
            settings.port = port

        app_instance = server_module.build_app(settings)
        uvicorn.run(app_instance, host=settings.bind, port=settings.port)

    return gmnspy_app


def _resolve_engine(name: str | None):
    """Resolve an engine by name (``ibis`` / ``pandas`` / ``polars``).

    Mirrors the helper used by other Phase-4 commands; kept local so this
    module doesn't depend on the 4.2 helper landing first.
    """
    from datagrove.engines import get_engine

    if name is None:
        return get_engine()
    name = name.lower()
    if name == "ibis":
        from datagrove.engines.ibis_engine import IbisEngine

        return IbisEngine()
    if name == "pandas":
        from datagrove.engines.pandas_engine import PandasEngine

        return PandasEngine()
    if name == "polars":
        from datagrove.engines.polars_engine import PolarsEngine

        return PolarsEngine()
    raise typer.BadParameter(f"unknown engine {name!r}")


def _safe_count(net: Network, table_name: str) -> int | None:
    """Return ``net.tables[table_name].count()`` or ``None`` if the table is absent."""
    table = net.tables.get(table_name)
    if table is None:
        return None
    try:
        return table.count()
    except Exception:  # pragma: no cover - best effort for `info`
        return None


# ---------------------------------------------------------------------------
# spec diff helpers (task 4.3 / issue #85)
# ---------------------------------------------------------------------------


def _field_map(resource) -> dict[str, str | None]:  # type: ignore[no-untyped-def]
    """Return ``{field_name: type}`` for a resource, or ``{}`` if schemaless.

    Uses :attr:`Resource.table_schema` (the Python attribute name —
    accessing ``.schema`` directly emits a FutureWarning and returns a
    bound method, not the schema data).
    """
    schema = resource.table_schema
    if schema is None or isinstance(schema, str):
        return {}
    return {f.name: f.type for f in schema.fields}


def _diff_specs(v1: str, v2: str) -> dict[str, object]:
    """Compute a structural diff between two vendored GMNS spec versions.

    Returns a dict with ``v1``, ``v2``, ``added_resources``,
    ``removed_resources``, and ``changed_resources`` keys; see
    docstring on the CLI command for the exact shape.
    """
    pkg_v1 = load_gmns_spec(v1)
    pkg_v2 = load_gmns_spec(v2)
    res_v1 = {r.name: r for r in pkg_v1.resources}
    res_v2 = {r.name: r for r in pkg_v2.resources}
    names_v1 = set(res_v1)
    names_v2 = set(res_v2)

    changed: list[dict[str, object]] = []
    for name in sorted(names_v1 & names_v2):
        fields_v1 = _field_map(res_v1[name])
        fields_v2 = _field_map(res_v2[name])
        added_fields = sorted(set(fields_v2) - set(fields_v1))
        removed_fields = sorted(set(fields_v1) - set(fields_v2))
        changed_fields = [
            {"name": fname, "v1_type": fields_v1[fname], "v2_type": fields_v2[fname]}
            for fname in sorted(set(fields_v1) & set(fields_v2))
            if fields_v1[fname] != fields_v2[fname]
        ]
        if added_fields or removed_fields or changed_fields:
            changed.append(
                {
                    "name": name,
                    "added_fields": added_fields,
                    "removed_fields": removed_fields,
                    "changed_fields": changed_fields,
                }
            )

    return {
        "v1": v1,
        "v2": v2,
        "added_resources": sorted(names_v2 - names_v1),
        "removed_resources": sorted(names_v1 - names_v2),
        "changed_resources": changed,
    }


# ---------------------------------------------------------------------------
# doctor check helpers (task 4.5 / issue #87)
# ---------------------------------------------------------------------------


def _check_python_version() -> dict[str, object]:
    """Verify Python 3.11+ — matches pyproject ``requires-python``."""
    ver = sys.version_info
    ok = ver >= (3, 11)
    return {
        "name": "python_version",
        "ok": ok,
        "detail": f"{ver.major}.{ver.minor}.{ver.micro} ({'>=3.11' if ok else 'requires >=3.11'})",
    }


# Optional-extra → import probe. Each entry is (extra-name, module-to-import).
# The extra is informational; the import is what actually decides ok/!ok.
_EXTRA_PROBES: tuple[tuple[str, str], ...] = (
    ("clean", "shapely"),
    ("clean", "igraph"),
    ("server", "fastapi"),
    ("mcp", "mcp"),
    ("notebook", "ipywidgets"),
)


def _check_optional_extras() -> list[dict[str, object]]:
    """One check per (extra, probe-module). ``ok=False`` is informational, not fatal — see _check_leavenworth_loads."""
    out: list[dict[str, object]] = []
    for extra, module in _EXTRA_PROBES:
        try:
            importlib.import_module(module)
            out.append({"name": f"extra:{extra}[{module}]", "ok": True, "detail": "importable"})
        except ImportError as exc:
            out.append(
                {
                    "name": f"extra:{extra}[{module}]",
                    "ok": True,  # optional — absence is not a failure
                    "detail": f"not installed ({exc.__class__.__name__}); install with `uv sync --extra {extra}`",
                }
            )
    return out


def _check_spec_versions() -> list[dict[str, object]]:
    """Each vendored spec version must parse without error."""
    out: list[dict[str, object]] = []
    for version in SUPPORTED_SPECS:
        try:
            pkg = load_gmns_spec(version)
            out.append(
                {
                    "name": f"spec:{version}",
                    "ok": True,
                    "detail": f"{len(pkg.resources)} resources",
                }
            )
        except Exception as exc:  # pragma: no cover - vendored data is checked in
            out.append({"name": f"spec:{version}", "ok": False, "detail": f"{exc.__class__.__name__}: {exc}"})
    return out


def _check_leavenworth_loads() -> dict[str, object]:
    """Smoke test: the Leavenworth fixture should load + report a link table."""
    try:
        from gmnspy.fixtures import leavenworth

        net = Network.from_source(leavenworth.csv_dir())
        link_count = _safe_count(net, "link")
        return {
            "name": "fixture:leavenworth",
            "ok": link_count is not None and link_count > 0,
            "detail": f"loaded {link_count} links from csv fixture",
        }
    except Exception as exc:
        return {
            "name": "fixture:leavenworth",
            "ok": False,
            "detail": f"{exc.__class__.__name__}: {exc}",
        }


def _check_auto_approve_env() -> dict[str, object]:
    """Informational: report whether DATAGROVE_AUTO_APPROVE is set."""
    value = os.environ.get("DATAGROVE_AUTO_APPROVE")
    return {
        "name": "env:DATAGROVE_AUTO_APPROVE",
        "ok": True,  # informational only
        "detail": f"set to {value!r}" if value is not None else "unset (interactive consent required)",
    }


# Module-level app for the `gmnspy` console-script entry point.
app = _build_gmnspy_app()


if __name__ == "__main__":  # pragma: no cover - manual smoke
    app()
