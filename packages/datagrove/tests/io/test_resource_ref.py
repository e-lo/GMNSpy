"""Tests for the ResourceRef pydantic model and ResourceListing alias."""

from __future__ import annotations

import pytest
from datagrove.io import ResourceListing, ResourceRef


def test_resource_ref_round_trip() -> None:
    ref = ResourceRef(name="link", path="net/link.parquet", format="parquet")
    payload = ref.model_dump()
    assert payload == {"name": "link", "path": "net/link.parquet", "format": "parquet"}
    parsed = ResourceRef.model_validate(payload)
    assert parsed == ref


def test_resource_ref_json_round_trip() -> None:
    ref = ResourceRef(name="node", path="s3://bucket/node.csv", format="csv")
    payload = ref.model_dump_json()
    parsed = ResourceRef.model_validate_json(payload)
    assert parsed == ref


def test_resource_ref_is_frozen() -> None:
    ref = ResourceRef(name="link", path="x", format="csv")
    with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
        ref.name = "node"  # type: ignore[misc]


def test_resource_listing_is_list_alias() -> None:
    listing: ResourceListing = [
        ResourceRef(name="link", path="link.parquet", format="parquet"),
        ResourceRef(name="node", path="node.parquet", format="parquet"),
    ]
    assert isinstance(listing, list)
    assert len(listing) == 2
    assert all(isinstance(r, ResourceRef) for r in listing)
