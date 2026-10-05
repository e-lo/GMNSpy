"""Foreign-key relations between a network's tables, read from its spec (never hard-coded).

The related-records view tints rows that are a foreign key away from what is focused or
highlighted: the lanes of a link (``lane.link_id`` points *in*), the nodes a link references
(``link.from_node_id`` points *out*), and so on. Every relation is a predicate
``<column> IN (<values>)`` on the related table, with ``values`` bounded by the highlight: an
inbound key reuses the highlighted ids as they are; an outbound key costs one query for the
distinct key values of the highlighted rows. It is a read-only view: nothing here is recorded.

Only single-column keys between two *different* tables are followed: self-references
(``link.parent_link_id``) and composite keys are out of scope for now.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from netstead.viz.tables import columns_of, primary_key

__all__ = [
    "MAX_MAP_IDS",
    "MAX_SOURCE_IDS",
    "ForeignKey",
    "Match",
    "Relation",
    "RelationGraph",
    "foreign_keys",
    "primary_keys",
    "relation_graph",
]

#: Highlighted ids accepted per request (and the cap on a hop-2 frontier).
MAX_SOURCE_IDS = 10_000
#: Link/node ids returned for map tinting; beyond this the answer says ``truncated``.
MAX_MAP_IDS = 50_000


@dataclass(frozen=True)
class ForeignKey:
    """One single-column foreign key: ``table.column`` references ``ref_table.ref_column``."""

    table: str
    column: str
    ref_table: str
    ref_column: str

    @property
    def label(self) -> str:
        """How the UI names the relation, e.g. ``lane.link_id → link``."""
        return f"{self.table}.{self.column} → {self.ref_table}"


@dataclass(frozen=True)
class Match:
    """Rows whose ``column`` is in ``values``, reached through the relation named ``via``."""

    column: str
    values: tuple[Any, ...]
    via: str


@dataclass
class Relation:
    """Everything related in one table: the OR of its matches, at the hop it was first reached."""

    table: str
    hop: int
    matches: list[Match] = field(default_factory=list)
    partial: bool = False  # derived from a frontier capped at MAX_SOURCE_IDS

    @property
    def via(self) -> list[str]:
        """The distinct relation labels that reach this table, sorted."""
        return sorted({m.via for m in self.matches})


@dataclass(frozen=True)
class RelationGraph:
    """A network's browsable tables, their primary keys, and the foreign keys between them."""

    tables: Mapping[str, Any]
    fks: tuple[ForeignKey, ...]
    pks: Mapping[str, str | None]


def _single(fields: str | list[str]) -> str | None:
    if isinstance(fields, str):
        return fields
    return fields[0] if len(fields) == 1 else None


def _schemas(spec: Any) -> dict[str, Any]:
    return {
        r.name: r.table_schema
        for r in spec.resources
        if r.table_schema is not None and not isinstance(r.table_schema, str)
    }


def foreign_keys(spec: Any, columns: Mapping[str, Sequence[str]]) -> list[ForeignKey]:
    """Single-column FKs between two different tables in ``columns``, both columns present."""
    out: list[ForeignKey] = []
    for name, schema in _schemas(spec).items():
        if name not in columns:
            continue
        for fk in schema.foreign_keys:
            ref_table = fk.reference.resource or name
            column, ref_column = _single(fk.fields), _single(fk.reference.fields)
            if ref_table == name or ref_table not in columns or column is None or ref_column is None:
                continue
            if column in columns[name] and ref_column in columns[ref_table]:
                out.append(ForeignKey(name, column, ref_table, ref_column))
    return out


def primary_keys(spec: Any, columns: Mapping[str, Sequence[str]]) -> dict[str, str | None]:
    """Each table's key: the spec's single-column ``primaryKey`` when present, else the ``*_id`` heuristic."""
    declared = {name: schema.primary_key for name, schema in _schemas(spec).items()}
    out: dict[str, str | None] = {}
    for name, cols in columns.items():
        pk = declared.get(name)
        out[name] = pk if isinstance(pk, str) and pk in cols else primary_key(name, list(cols))
    return out


def relation_graph(spec: Any, tables: Mapping[str, Any]) -> RelationGraph:
    """The :class:`RelationGraph` over ``tables`` (pandas frames or lazy corral tables)."""
    columns = {name: columns_of(src) for name, src in tables.items()}
    return RelationGraph(tables=tables, fks=tuple(foreign_keys(spec, columns)), pks=primary_keys(spec, columns))
