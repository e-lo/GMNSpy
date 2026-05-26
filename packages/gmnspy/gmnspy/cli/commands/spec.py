"""``gmnspy spec`` sub-app — list + diff vendored GMNS spec versions (issue #85)."""

from __future__ import annotations

import typer
from datagrove.cli.render import render_dict

from gmnspy.spec import DEFAULT_SPEC, SUPPORTED_SPECS, load_gmns_spec

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Register the ``spec`` sub-app on ``app``."""
    spec_app = typer.Typer(no_args_is_help=True, help="GMNS spec utilities — list and diff vendored versions.")
    app.add_typer(spec_app, name="spec")

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
