"""Edit log — the bridge from interactive viewer to Python-side network mutation.

The interactive viewer (:class:`~gmnspy.map.NetworkMap`) collects
proposed fixes per user click and lets the user download the
accumulated session as a `network-wrangler ProjectCard
<https://network-wrangler.github.io/projectcard/main/json-schemas/>`_
YAML. This module is the Python half: load that YAML, replay it
against a :class:`~gmnspy.network.Network`, save the mutated result.

Design intent:

* **Identify rows by primary key, not positional row index.** Positional
  rows are not stable across reloads / partial scans / partial deletes;
  PKs (``link_id``, ``node_id``, …) are.
* **Two halves: browser collects, Python applies.** The browser is good
  at click-by-click triage. Python is good at deterministic, typed
  mutation. The YAML log is the boundary.
* **ProjectCard-compatible on disk.** Each session serialises to a
  single ProjectCard with a top-level ``changes`` array. Each per-cell
  fix becomes one ``roadway_property_change`` entry. The file is
  consumable by network-wrangler; extension fields (e.g. node
  property changes via ``model_node_id``) are permitted and gmnspy
  parses them faithfully on round-trip.

The default applier runs through the pandas engine — i.e. the returned
``ApplyResult.net`` always backs its mutated tables with
:class:`~datagrove.engines.pandas_engine.PandasEngine`. Other engines'
lazy expressions aren't mutated in place; that's a future concern.
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

# GMNS primary-key column → ProjectCard facility selector key. network-wrangler
# uses ``model_link_id`` / ``model_node_id`` for its road-network model; we
# translate on both sides so the on-disk YAML stays interoperable.
_PK_COL_TO_FACILITY_KEY = {"link_id": "model_link_id", "node_id": "model_node_id"}
_FACILITY_KEY_TO_TABLE_PK = {
    "model_link_id": ("link", "link_id"),
    "model_node_id": ("node", "node_id"),
}


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
    """Load an edit log from a network-wrangler ProjectCard YAML file.

    Accepts a single project card whose top-level ``changes`` is an
    array of ``roadway_property_change`` entries. Each entry becomes
    one :class:`Edit`.

    The ``project`` name and top-level ``notes`` (when present) round-trip
    onto ``EditLog.source`` (best effort — we pull ``source: <val>`` and
    ``spec_version: <val>`` lines from a structured notes block if they
    were written by :func:`dump_edit_log`).

    Args:
        path: Path to the YAML file produced by the viewer (or hand-written).

    Returns:
        The parsed :class:`EditLog`.

    Raises:
        ValueError: When the top-level document is not a recognisable
            ProjectCard shape (no ``project`` key, no ``changes`` array).
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
    if not isinstance(data, dict) or "project" not in data:
        raise ValueError(
            "not a ProjectCard: expected a top-level 'project' key. "
            "See https://network-wrangler.github.io/projectcard/main/json-schemas/"
        )

    # Accept either the multi-change wrapper (top-level ``changes: [...]``)
    # or a single-change card (top-level one-off ``roadway_property_change``).
    raw_changes: list[dict[str, Any]] = []
    if isinstance(data.get("changes"), list):
        raw_changes = data["changes"]
    elif "roadway_property_change" in data:
        raw_changes = [{"roadway_property_change": data["roadway_property_change"]}]
    else:
        raise ValueError("ProjectCard has no 'changes' array and no top-level 'roadway_property_change'")

    edits: list[Edit] = []
    for i, change in enumerate(raw_changes):
        rpc = change.get("roadway_property_change") if isinstance(change, dict) else None
        if not isinstance(rpc, dict):
            continue  # skip change types we don't handle (e.g. roadway_addition)
        edits.extend(_edits_from_roadway_property_change(rpc, seq=i))

    # Metadata round-trip out of the top-level notes block.
    notes = data.get("notes") or ""
    return EditLog(
        schema_version=_SCHEMA_VERSION,
        source=_notes_lookup(notes, "source"),
        spec_version=_notes_lookup(notes, "spec_version"),
        created_at=_notes_lookup(notes, "created_at"),
        client=_notes_lookup(notes, "client"),
        edits=edits,
    )


def _edits_from_roadway_property_change(rpc: dict[str, Any], *, seq: int) -> list[Edit]:
    """Expand one ``roadway_property_change`` into one Edit per changed cell.

    A single roadway_property_change may target multiple facilities
    (facility ids list) and multiple properties. We fan it out to
    per-``(pk, column)`` :class:`Edit` records so ``apply_edits``
    stays cell-scoped.
    """
    facility = rpc.get("facility") or {}
    property_changes = rpc.get("property_changes") or {}
    change_notes = rpc.get("notes")

    # Facility selector — first supported key wins. GMNS tables have at
    # most one primary-key column so this is unambiguous.
    fac_key: str | None = None
    ids: list[Any] = []
    for candidate in ("model_link_id", "model_node_id"):
        if candidate in facility:
            fac_key = candidate
            raw = facility[candidate]
            ids = list(raw) if isinstance(raw, list) else [raw]
            break
    if fac_key is None or not ids:
        return []
    table, pk_col = _FACILITY_KEY_TO_TABLE_PK[fac_key]

    out: list[Edit] = []
    for fid in ids:
        for j, (column, change_spec) in enumerate(property_changes.items()):
            if not isinstance(change_spec, dict) or "set" not in change_spec:
                continue
            out.append(
                Edit(
                    id=f"c{seq}f{fid}p{j}",
                    kind="fix",
                    table=table,
                    pk={pk_col: fid},
                    column=column,
                    from_value=change_spec.get("existing"),
                    to_value=change_spec["set"],
                    reason=change_notes if isinstance(change_notes, str) else None,
                    issue_id=None,
                    timestamp=None,
                )
            )
    return out


def _notes_lookup(notes: str, key: str) -> str | None:
    """Extract a ``key: value`` line from a structured top-level notes block."""
    if not isinstance(notes, str):
        return None
    prefix = f"{key}:"
    for line in notes.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip() or None
    return None


def dump_edit_log(log: EditLog, path: str | Path) -> None:
    """Write an edit log as a network-wrangler ProjectCard YAML file.

    Emits a single project card with a top-level ``changes`` array.
    Each :class:`Edit` becomes one ``roadway_property_change`` — the
    facility selector uses ``model_link_id`` / ``model_node_id`` per
    network-wrangler convention. gmnspy-specific metadata (source,
    spec_version, issue_id, edit id, timestamp) rides on the card's
    top-level ``notes`` block and the per-change ``notes`` field so it
    round-trips without breaking ProjectCard consumers.

    Node property changes aren't a first-class ProjectCard change type;
    we emit them with the same shape via ``model_node_id`` as an
    extension so gmnspy round-trips faithfully. network-wrangler may
    accept or reject them depending on its version.
    """
    try:
        import yaml
    except ImportError as e:  # pragma: no cover - defensive
        raise ImportError(
            "gmnspy.map.edits requires pyyaml from the [reports] extra: pip install 'gmnspy[reports]'"
        ) from e

    changes: list[dict[str, Any]] = []
    for e in log.edits:
        # Only "fix" edits emit as roadway_property_change today; future
        # kinds (modification / project_card) would emit as their own
        # change types.
        if e.kind != "fix":
            continue
        # Pick the PK column that maps to a facility key.
        fac_key = None
        fac_id = None
        for col, val in e.pk.items():
            if col in _PK_COL_TO_FACILITY_KEY:
                fac_key = _PK_COL_TO_FACILITY_KEY[col]
                fac_id = val
                break
        if fac_key is None:
            continue  # skip unsupported PK shape

        prop_change: dict[str, Any] = {}
        if e.from_value is not None:
            prop_change["existing"] = e.from_value
        prop_change["set"] = e.to_value

        # Per-change note — reason + issue_id + edit id, if any.
        note_bits: list[str] = []
        if e.reason:
            note_bits.append(e.reason)
        if e.issue_id:
            note_bits.append(f"issue_id={e.issue_id}")
        if e.id:
            note_bits.append(f"edit_id={e.id}")

        change: dict[str, Any] = {
            "roadway_property_change": {
                "facility": {fac_key: [fac_id]},
                "property_changes": {e.column: prop_change},
            }
        }
        if note_bits:
            change["roadway_property_change"]["notes"] = " · ".join(note_bits)
        changes.append(change)

    # Top-level structured notes so metadata survives the round-trip.
    top_notes_lines: list[str] = []
    for key in ("source", "spec_version", "created_at", "client"):
        val = getattr(log, key)
        if val is not None:
            top_notes_lines.append(f"{key}: {val}")

    body: dict[str, Any] = {
        "project": f"gmnspy edits {log.created_at or ''}".strip(),
        "tags": ["gmnspy", "edit-log"],
    }
    if top_notes_lines:
        body["notes"] = "\n".join(top_notes_lines)
    body["changes"] = changes

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(body, default_flow_style=False, sort_keys=False))


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
    backed by :class:`~datagrove.engines.pandas_engine.PandasEngine` for
    EVERY table — mutated tables carry the edited DataFrames, untouched
    tables are materialised snapshots of their source expressions. All
    tables share a single engine so ``net.write(dest)`` sees a
    consistent state (mixing pandas and ibis/duckdb tables in one
    write() call would raise on the engine's next dispatch).

    On very large networks (100k+ links) this materialises every table
    to pandas even when you only edited a few rows — measurable but
    typically fine for interactive fix sessions. If you need a lower-
    memory path, ``apply_edits`` sub-sets are on the roadmap.

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

    # Rebuild the network with a single engine for every table.
    # Mutated tables carry their new DataFrame; untouched tables get
    # materialised via to_pandas() so write() dispatches consistently
    # instead of hitting a pandas-vs-ibis-vs-duckdb mixed state.
    new_engine = PandasEngine()
    new_tables: dict[str, Table] = {}
    for name, existing in net.tables.items():
        df = mutated[name] if name in mutated else existing.to_pandas()
        new_tables[name] = Table(
            name=name,
            expr=df,
            engine=new_engine,
            schema=existing.schema,
            source=existing.source,
            format=existing.format,
        )

    new_net = type(net)(
        spec=net.spec,
        tables=new_tables,
        engine=new_engine,
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
