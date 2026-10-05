"""Unit tests for the benchmark fixture registry (netstead.bench.fixtures)."""

from __future__ import annotations

from pathlib import Path

from netstead.bench import fixtures


def test_default_registry_has_both_bundled_fixtures():
    reg = fixtures.default_registry()
    ids = [f["id"] for f in reg["fixture"]]
    assert ids == ["leavenworth", "rdu_i40"]
    assert reg["large"]["tier"] == "L"


def test_load_registry_from_explicit_toml(tmp_path: Path):
    toml = tmp_path / "fixtures.toml"
    toml.write_text(
        'schema_version = "1"\n'
        "[[fixture]]\n"
        'id = "leavenworth"\n'
        'tier = "S"\n'
        'formats = ["csv"]\n'
        "expected_links = 339\n"
        'selections = [{ case = "x", utterance = "Benton Street" }]\n',
        encoding="utf-8",
    )
    reg = fixtures.load_registry(toml)
    assert reg["fixture"][0]["formats"] == ["csv"]


def test_resolve_fixtures_small_tier():
    specs = fixtures.resolve_fixtures(("S",))
    assert [s.id for s in specs] == ["leavenworth"]
    spec = specs[0]
    assert spec.tier == "S"
    assert "csv" in spec.source_dirs
    assert spec.source_dirs["csv"].exists()
    assert spec.expected_links == 339
    assert spec.selections[0].utterance == "Benton Street"


def test_resolve_fixtures_small_and_medium():
    specs = fixtures.resolve_fixtures(("S", "M"))
    assert {s.id for s in specs} == {"leavenworth", "rdu_i40"}


def test_resolve_fixtures_large_skipped_without_env(monkeypatch):
    monkeypatch.delenv(fixtures.LARGE_ENV_VAR, raising=False)
    monkeypatch.delenv(fixtures.LARGE_BBOX_ENV_VAR, raising=False)
    specs = fixtures.resolve_fixtures(("L",))
    assert specs == []


def test_resolve_fixtures_large_from_env_dir(monkeypatch):
    # Point the L tier at the bundled rdu_i40 csv dir just to prove env wiring.
    from netstead import fixtures as bundled

    rdu_csv = Path(bundled.__file__).resolve().parent / "rdu_i40" / "csv"
    monkeypatch.setenv(fixtures.LARGE_ENV_VAR, str(rdu_csv))
    monkeypatch.delenv(fixtures.LARGE_BBOX_ENV_VAR, raising=False)
    specs = fixtures.resolve_fixtures(("L",))
    assert len(specs) == 1
    assert specs[0].tier == "L"
    assert specs[0].primary_source() == rdu_csv


def test_resolve_fixtures_large_from_bbox_env(monkeypatch):
    monkeypatch.delenv(fixtures.LARGE_ENV_VAR, raising=False)
    monkeypatch.setenv(fixtures.LARGE_BBOX_ENV_VAR, "-78.95,35.74,-78.56,35.94")
    specs = fixtures.resolve_fixtures(("L",))
    assert len(specs) == 1
    assert specs[0].bbox == (-78.95, 35.74, -78.56, 35.94)


def test_fixture_spec_primary_source_prefers_parquet():
    spec = fixtures.FixtureSpec(
        id="x",
        tier="S",
        formats=("csv", "parquet"),
        source_dirs={"csv": Path("/a/csv"), "parquet": Path("/a/parquet")},
    )
    assert spec.primary_source() == Path("/a/parquet")
