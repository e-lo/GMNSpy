"""Edit log — the bridge from interactive viewer to Python-side network mutation.

Phase 1 of the editing story. The interactive viewer
(:class:`~gmnspy.map.NetworkMap`) collects proposed fixes per user click
and lets the user download the accumulated log as YAML. This module is
the Python half: load that YAML, replay it against a
:class:`~gmnspy.network.Network`, save the mutated result.

Design intent (per the user-driven workflow):

* **Identify rows by primary key, not positional row index.** Positional
  rows are not stable across reloads / partial scans / partial deletes;
  PKs (``link_id``, ``node_id``, …) are.
* **Two halves: browser collects, Python applies.** The browser is good
  at click-by-click triage. Python is good at deterministic, typed
  mutation. Keep them cleanly separated; the YAML log is the boundary.
* **Forward-compatible with ProjectCard.** Phase 1 only handles
  ``kind: fix`` (per-cell value changes). The schema reserves
  ``kind: modification`` for future ProjectCard payloads so the on-disk
  log format doesn't need migration when modifications land.

The default applier runs through the pandas engine — i.e. the returned
``ApplyResult.net`` always backs its mutated tables with
:class:`~datagrove.engines.pandas_engine.PandasEngine`. Other engines'
lazy expressions aren't mutated in place; that's a Phase-2 concern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from gmnspy.network import Network

__all__ = [
    "AppliedEdit",
    "ApplyResult",
    "Edit",
    "EditLog",
    "SkippedEdit",
    "apply_edits",
    "dump_edit_log",
    "load_edit_log",
]


# The on-disk schema version we accept. Bumping this is a breaking change
# — load_edit_log rejects anything else loud and clear.
_SCHEMA_VERSION = "1"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class Edit:
    """One proposed change to a single cell.

    Identified by ``(table, pk, column)``. ``pk`` is a dict of
    primary-key columns to values so the edit survives row reordering /
    partial reload — see module docstring.

    ``from_value`` is the value the editor *believed* was there when the
    edit was proposed. The applier uses it for a drift check: if the
    table's current value at ``(table, pk, column)`` doesn't match
    ``from_value``, the edit is skipped (with a reason) rather than
    silently clobbering a concurrent change. Pass ``from_value=None`` to
    disable the drift check (the most common JS-side case where the
    editor has no reliable prior).
    """

    id: str
    kind: str  # "fix" | "modification" — modifications reserved for Phase 2
    table: str
    pk: dict[str, Any]
    column: str
    from_value: Any = None
    to_value: Any = None
    reason: str | None = None
    issue_id: str | None = None
    timestamp: str | None = None


@dataclass
class EditLog:
    """Container for a session's worth of edits + metadata.

    The on-disk YAML wraps this dict under a top-level ``edit_log:`` key
    so future tooling can stash multiple logs in the same file if it
    ever needs to.
    """

    schema_version: str = _SCHEMA_VERSION
    source: str | None = None
    spec_version: str | None = None
    created_at: str | None = None
    client: str | None = None
    edits: list[Edit] = field(default_factory=list)


@dataclass
class AppliedEdit:
    """One edit that the applier successfully wrote to the in-memory table."""

    edit: Edit
    applied_at: str


@dataclass
class SkippedEdit:
    """One edit the applier did NOT write — with a human-readable reason.

    Reasons include: ``pk not found``, ``value drift`` (current value
    differs from ``from_value``), ``table not in network``, ``column
    not in table``, ``pk matched multiple rows``. The viewer surfaces
    these so the user can decide whether to update the log or push past.
    """

    edit: Edit
    reason: str


@dataclass
class ApplyResult:
    """Outcome of :func:`apply_edits` — the mutated network + counts."""

    net: Network
    applied: list[AppliedEdit] = field(default_factory=list)
    skipped: list[SkippedEdit] = field(default_factory=list)

    def summary(self) -> str:
        """One-line human-readable summary: ``N applied, M skipped``."""
        return f"{len(self.applied)} applied, {len(self.skipped)} skipped"


# ---------------------------------------------------------------------------
# YAML round-trip
# ---------------------------------------------------------------------------


def load_edit_log(path: str | Path) -> EditLog:
    """Load an edit log from a YAML file.

    Args:
        path: Path to the YAML file produced by the viewer (or hand-written).

    Returns:
        The parsed :class:`EditLog`.

    Raises:
        ValueError: When the file's ``schema_version`` is not supported.
        ImportError: When ``pyyaml`` is not installed (it ships in the
            ``[reports]`` extra).
    """
    try:
        import yaml
    except ImportError as e:  # pragma: no cover - defensive
        raise ImportError(
            "gmnspy.map.edits requires pyyaml from the [reports] extra: pip install 'gmnspy[reports]'"
        ) from e

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if isinstance(data, dict) and "edit_log" in data:
        data = data["edit_log"]

    version = str(data.get("schema_version", ""))
    if version != _SCHEMA_VERSION:
        raise ValueError(
            f"unsupported edit-log schema_version {version!r}; this version of "
            f"gmnspy.map.edits expects {_SCHEMA_VERSION!r}"
        )

    edits = [
        Edit(
            id=e["id"],
            kind=e["kind"],
            table=e["table"],
            pk=dict(e["pk"]),
            column=e["column"],
            from_value=e.get("from"),
            to_value=e.get("to"),
            reason=e.get("reason"),
            issue_id=e.get("issue_id"),
            timestamp=e.get("timestamp"),
        )
        for e in data.get("edits", [])
    ]
    return EditLog(
        schema_version=version,
        source=data.get("source"),
        spec_version=data.get("spec_version"),
        created_at=data.get("created_at"),
        client=data.get("client"),
        edits=edits,
    )


def dump_edit_log(log: EditLog, path: str | Path) -> None:
    """Write an edit log to a YAML file.

    The ``from_value`` / ``to_value`` dataclass fields are written under
    their YAML-natural ``from:`` / ``to:`` keys (``from`` is reserved in
    Python so we can't name the field that, but the on-disk shape stays
    natural).
    """
    try:
        import yaml
    except ImportError as e:  # pragma: no cover - defensive
        raise ImportError(
            "gmnspy.map.edits requires pyyaml from the [reports] extra: pip install 'gmnspy[reports]'"
        ) from e

    body = {
        "schema_version": log.schema_version,
        **{
            k: v
            for k, v in {
                "source": log.source,
                "spec_version": log.spec_version,
                "created_at": log.created_at,
                "client": log.client,
            }.items()
            if v is not None
        },
        "edits": [
            {
                "id": e.id,
                "kind": e.kind,
                "table": e.table,
                "pk": e.pk,
                "column": e.column,
                "from": e.from_value,
                "to": e.to_value,
                **{
                    k: v
                    for k, v in {
                        "reason": e.reason,
                        "issue_id": e.issue_id,
                        "timestamp": e.timestamp,
                    }.items()
                    if v is not None
                },
            }
            for e in log.edits
        ],
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump({"edit_log": body}, default_flow_style=False, sort_keys=False))


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_edits(net: Network, log: EditLog) -> ApplyResult:
    """Apply ``log``'s edits to ``net`` in memory; return the result.

    For each edit:

    1. Look up the table — skip with reason if it isn't on the network.
    2. Materialise it to a pandas DataFrame the first time we touch it.
    3. Find the row by the edit's primary-key dict — skip if missing or
       ambiguous (multiple matches).
    4. If ``from_value`` is not ``None``, compare against the current
       value at that ``(row, column)``. Skip on drift.
    5. Write ``to_value`` into the cell.

    The returned ``ApplyResult.net`` is a fresh :class:`~gmnspy.network.Network`
    backed by :class:`~datagrove.engines.pandas_engine.PandasEngine` —
    tables you didn't touch are carried through as-is; tables you DID
    touch are now pandas-backed snapshots of the mutated state.

    Args:
        net: The source network. Not mutated in-place.
        log: The edits to apply.

    Returns:
        :class:`ApplyResult` with the mutated network, the list of
        successfully-applied edits (with ISO timestamps), and the list
        of skipped edits (each with a reason).
    """
    try:
        import pandas as pd
        from datagrove.dataset import Table
        from datagrove.engines.pandas_engine import PandasEngine
    except ImportError as e:  # pragma: no cover - defensive
        raise ImportError("gmnspy.map.edits.apply_edits requires pandas + datagrove (transitive).") from e

    applied: list[AppliedEdit] = []
    skipped: list[SkippedEdit] = []
    mutated: dict[str, pd.DataFrame] = {}

    for edit in log.edits:
        table = net.tables.get(edit.table)
        if table is None:
            skipped.append(SkippedEdit(edit, f"table {edit.table!r} not in network"))
            continue
        if edit.table not in mutated:
            mutated[edit.table] = table.to_pandas().copy()
        df = mutated[edit.table]

        if edit.column not in df.columns:
            skipped.append(SkippedEdit(edit, f"column {edit.column!r} not in {edit.table!r}"))
            continue

        mask = _pk_mask(df, edit.pk)
        if mask is None:
            skipped.append(SkippedEdit(edit, f"pk column missing from {edit.table!r}"))
            continue
        n_match = int(mask.sum())
        if n_match == 0:
            skipped.append(SkippedEdit(edit, f"pk {edit.pk} not found in {edit.table!r}"))
            continue
        if n_match > 1:
            skipped.append(SkippedEdit(edit, f"pk {edit.pk} matched {n_match} rows in {edit.table!r}"))
            continue

        if edit.from_value is not None:
            current = df.loc[mask, edit.column].iloc[0]
            if not _values_equal(current, edit.from_value):
                skipped.append(
                    SkippedEdit(
                        edit,
                        f"value drift in {edit.table!r}.{edit.column}: expected {edit.from_value!r}, found {current!r}",
                    )
                )
                continue

        df.loc[mask, edit.column] = edit.to_value
        applied.append(AppliedEdit(edit, applied_at=datetime.now(UTC).isoformat()))

    # Rebuild the network with the mutated tables. Untouched tables ride
    # through as-is (their lazy expressions are preserved); mutated tables
    # become pandas-backed snapshots wrapping the new DataFrame.
    new_engine = PandasEngine()
    new_tables = dict(net.tables)
    for name, df in mutated.items():
        new_tables[name] = Table(
            name=name,
            expr=df,
            engine=new_engine,
            schema=net.tables[name].schema,
            source=net.tables[name].source,
            format=net.tables[name].format,
        )

    new_net = type(net)(
        spec=net.spec,
        tables=new_tables,
        engine=net.engine,
        source=net.source,
        dirty_tracker=net.dirty_tracker,
        metadata=dict(net.metadata),
        spec_version=net.spec_version,
    )
    return ApplyResult(net=new_net, applied=applied, skipped=skipped)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pk_mask(df, pk: dict[str, Any]):
    """Build a boolean Series selecting rows where every PK column matches.

    Returns ``None`` when any of the PK columns is missing from ``df`` —
    a structurally invalid lookup the caller should skip.
    """
    import pandas as pd

    mask = pd.Series([True] * len(df), index=df.index)
    for key, value in pk.items():
        if key not in df.columns:
            return None
        mask &= df[key] == value
    return mask


def _values_equal(a: Any, b: Any) -> bool:
    """Compare two values with NaN-aware semantics.

    Pandas reads missing CSV cells as ``NaN`` which never compares equal
    to anything (even itself). For edit-log drift checks we treat
    ``NaN`` and ``None`` as the same "missing" value.
    """
    import math

    a_missing = a is None or (isinstance(a, float) and math.isnan(a))
    b_missing = b is None or (isinstance(b, float) and math.isnan(b))
    if a_missing and b_missing:
        return True
    if a_missing != b_missing:
        return False
    return a == b
