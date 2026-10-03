"""Session job actions: OpenNetwork / BuildNetwork run off the session lock, with approval and cancel."""

import os
import sys
import threading
import time
from pathlib import Path

import pytest
from gmnspy import Network
from gmnspy.select.parse import StubParser
from gmnspy.workbench import build
from gmnspy.workbench.actions import BuildNetwork, OpenNetwork
from gmnspy.workbench.errors import ActionError, ApprovalRequired, JobCancelled, PathNotAllowed
from gmnspy.workbench.registry import _extra_tables
from gmnspy.workbench.session import Session

WAIT = 10.0


@pytest.fixture
def make_session(tmp_path, isolated_env):
    def make(**kwargs):
        return Session(project_dir=tmp_path, environ=isolated_env, parser=StubParser(), **kwargs)

    return make


# ------------------------------------------------------------------ OpenNetwork as a job


def test_open_outside_allowed_roots_is_recorded_path_not_allowed(make_session, tmp_path_factory):
    session = make_session()
    elsewhere = tmp_path_factory.mktemp("not-allowed")
    with pytest.raises(PathNotAllowed, match="outside the allowed folders"):
        session.dispatch(OpenNetwork(source=str(elsewhere)))
    assert session.history[-1].error_type == "PathNotAllowed" and len(session.registry) == 0


def test_url_sources_skip_the_roots_check(make_session, monkeypatch):
    def fake_from_source(source, **kw):
        raise OSError(f"offline: {source}")

    monkeypatch.setattr(Network, "from_source", fake_from_source)
    with pytest.raises(ActionError, match="could not open s3://bucket/net: offline"):
        make_session().dispatch(OpenNetwork(source="s3://bucket/net"))


def test_submit_returns_at_once_and_records_on_finish(make_session, rdu_source):
    session = make_session()
    events = []
    session.events.publish = events.append
    job = session.submit(OpenNetwork(source=rdu_source))
    assert job.wait(WAIT)
    snap = session.jobs.snapshot(job)
    assert snap["status"] == "done" and snap["result"] == {"net_id": "rdu-i40"} and snap["history_seq"] == 1
    assert session.history[0].ok and session.active == "rdu-i40"
    kinds = [e["type"] for e in events]
    assert kinds[0] == "job" and kinds.index("history") < kinds.index("state") and kinds[-1] == "job"


def test_submit_rejects_non_job_actions(make_session):
    with pytest.raises(ValueError, match="not a job action"):
        make_session().submit({"type": "clear_selection"})


def test_load_runs_without_holding_the_session_lock(make_session, rdu_source, monkeypatch):
    session = make_session()
    loading, release = threading.Event(), threading.Event()
    real = Network.from_source

    def slow_from_source(source, **kw):
        loading.set()
        release.wait(WAIT)
        return real(source, **kw)

    monkeypatch.setattr(Network, "from_source", slow_from_source)
    job = session.submit(OpenNetwork(source=rdu_source))
    assert loading.wait(WAIT)
    got = []
    reader = threading.Thread(target=lambda: got.append(session.state()))
    reader.start()
    reader.join(2.0)
    assert got and got[0]["networks"] == []  # state() took the lock while the open was mid-load
    release.set()
    assert job.wait(WAIT) and session.active == "rdu-i40"


def test_cancel_open_before_register(make_session, rdu_source, monkeypatch):
    session = make_session()
    loading, release = threading.Event(), threading.Event()
    real = Network.from_source

    def slow_from_source(source, **kw):
        loading.set()
        release.wait(WAIT)
        return real(source, **kw)

    monkeypatch.setattr(Network, "from_source", slow_from_source)
    job = session.submit(OpenNetwork(source=rdu_source))
    assert loading.wait(WAIT)
    session.jobs.cancel(job.id)
    release.set()
    assert job.wait(WAIT)
    assert session.jobs.snapshot(job)["status"] == "cancelled"
    assert session.history[-1].error_type == "JobCancelled" and len(session.registry) == 0


def test_dispatch_from_python_blocks_until_the_open_job_finishes(make_session, rdu_source):
    session = make_session()
    assert session.dispatch(OpenNetwork(source=rdu_source)) == {"net_id": "rdu-i40"}
    assert session.active == "rdu-i40" and session.history[-1].ok
    assert session.jobs.snapshots()[0]["history_seq"] == session.history[-1].seq
    assert len(session.registry.get("rdu-i40").links_df()) > 0  # frames were primed by the job


@pytest.mark.parametrize("prefix", ["file://", "duckdb://"])
def test_local_scheme_urls_are_checked_against_allowed_roots(make_session, tmp_path_factory, prefix):
    session = make_session()
    elsewhere = tmp_path_factory.mktemp("not-allowed") / "net.duckdb"
    with pytest.raises(PathNotAllowed, match="outside the allowed folders"):
        session.dispatch(OpenNetwork(source=f"{prefix}{elsewhere}"))
    assert session.history[-1].error_type == "PathNotAllowed" and len(session.registry) == 0


def test_unsupported_scheme_is_path_not_allowed(make_session):
    session = make_session()
    with pytest.raises(PathNotAllowed, match="unsupported URL scheme"):
        session.dispatch(OpenNetwork(source="local:///etc/net"))
    assert session.history[-1].error_type == "PathNotAllowed"


def test_dispatching_a_job_action_under_the_session_lock_raises(make_session, rdu_source):
    session = make_session()
    with session._lock, pytest.raises(RuntimeError, match="would deadlock"):
        session.dispatch(OpenNetwork(source=rdu_source))
    assert session.history == [] and len(session.registry) == 0


def test_open_bundled_zip(make_session):
    from importlib import resources

    source = str(resources.files("gmnspy.fixtures.leavenworth").joinpath("leavenworth.csv.zip"))
    session = make_session()
    net_id = session.dispatch(OpenNetwork(source=source))["net_id"]
    assert len(session.registry.get(net_id).links_df()) > 0


# ------------------------------------------------------------------ concurrent opens (shared DuckDB connection)

LEAVENWORTH_PARQUET = str(Path(__file__).resolve().parents[1] / "gmnspy" / "fixtures" / "leavenworth" / "parquet")


def test_simultaneous_opens_both_succeed(make_session, rdu_source):
    """Two open jobs share datagrove's default DuckDB connection; neither may corrupt the other."""
    session = make_session()
    for _ in range(20):
        jobs = [session.submit(OpenNetwork(source=src)) for src in (rdu_source, LEAVENWORTH_PARQUET)]
        for job in jobs:
            assert job.wait(WAIT)
        snaps = [session.jobs.snapshot(job) for job in jobs]
        assert [s["status"] for s in snaps] == ["done", "done"], [s["error"] for s in snaps]
    assert len(session.registry) == 40


def test_http_like_reads_during_open_do_not_fail(make_session, rdu_source):
    """Lazy reads from other threads (extra tables, add_network summaries) race an open job safely."""
    session = make_session()
    session.add_network(Network.from_source(LEAVENWORTH_PARQUET), label="python")  # summary() is lazy
    errors: list[BaseException] = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                for handle in session.registry:
                    handle.roadway.links.count()
                    _extra_tables(handle.roadway)
                session.state()
            except BaseException as exc:  # asserted on below
                errors.append(exc)
                return

    readers = [threading.Thread(target=reader) for _ in range(3)]
    for t in readers:
        t.start()
    try:
        for _ in range(5):
            jobs = [session.submit(OpenNetwork(source=src)) for src in (rdu_source, LEAVENWORTH_PARQUET)]
            for job in jobs:
                assert job.wait(WAIT)
                assert session.jobs.snapshot(job)["status"] == "done", session.jobs.snapshot(job)["error"]
    finally:
        stop.set()
        for t in readers:
            t.join(WAIT)
    assert errors == []


# ------------------------------------------------------------------ BuildNetwork

FIXTURES = Path(__file__).resolve().parent / "fixtures"
OSM_FILE = str(FIXTURES / "osm" / "tiny.osm")
OVERTURE_DIR = str(FIXTURES / "overture")
#: What Overpass returns for the tiny area: its server-side highway filter already dropped the footway.
OVERPASS_BODY = [
    {"type": "node", "id": 1, "lat": 42.000, "lon": -71.000},
    {"type": "node", "id": 2, "lat": 42.001, "lon": -71.000},
    {"type": "node", "id": 3, "lat": 42.002, "lon": -71.000},
    {"type": "way", "id": 100, "nodes": [1, 2, 3], "tags": {"highway": "residential", "name": "Main St"}},
]


class _Resp:
    def __init__(self, payload):
        self.status_code, self._payload = 200, payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class FakeOverpass:
    """Answers the count pre-query and the body query; never touches the network."""

    def __init__(self, ways=10, fail_count=False):
        self.ways, self.fail_count, self.queries = ways, fail_count, []

    def post(self, url, data=None, headers=None, timeout=None):
        self.queries.append(data)
        if data.endswith("out count;"):
            if self.fail_count:
                raise OSError("overpass unreachable")
            return _Resp({"elements": [{"type": "count", "id": 0, "tags": {"ways": str(self.ways)}}]})
        return _Resp({"elements": OVERPASS_BODY})


@pytest.fixture
def out_dir(tmp_path):
    path = tmp_path / "out"
    path.mkdir()
    return str(path)


def _bbox_build(out_dir, **kw):
    return BuildNetwork(
        source="osm",
        area={"kind": "bbox", "bbox": (-71.01, 41.99, -70.99, 42.01)},
        output_dir=out_dir,
        output_format="parquet",
        name="tiny",
        **kw,
    )


def test_build_from_local_osm_writes_then_opens_from_disk(make_session, out_dir):
    session = make_session()
    result = session.dispatch(
        BuildNetwork(source="osm", input_file=OSM_FILE, output_dir=out_dir, output_format="parquet", name="tiny")
    )
    dest = Path(out_dir) / "tiny"
    assert result["output"] == str(dest.resolve()) and (dest / "link.parquet").is_file()
    assert sorted(p.name for p in Path(out_dir).iterdir()) == ["tiny"]  # no staging leftovers
    assert result["estimate"]["basis"].startswith("osm_file:") and result["estimate"]["seconds"] > 0
    handle = session.registry.get(result["net_id"])
    assert handle.source == str(dest.resolve()) and handle.label == "tiny" and len(handle.links_df()) == 2
    entry = session.history[-1]
    assert entry.ok and entry.result["estimate"] == result["estimate"]
    assert result["threshold_s"] == 90 and result["approval"] == "not_needed"
    assert "approved=True" in entry.python and "input_file=" in entry.python
    assert session.jobs.snapshots()[0]["label"] == "build tiny"


def test_build_from_local_overture_snapshot_to_duckdb(make_session, out_dir):
    session = make_session()
    result = session.dispatch(
        BuildNetwork(source="overture", input_file=OVERTURE_DIR, output_dir=out_dir, output_format="duckdb", name="ovt")
    )
    assert Path(result["output"]).name == "ovt.duckdb" and Path(result["output"]).is_file()
    assert sorted(p.name for p in Path(out_dir).iterdir()) == ["ovt.duckdb"]  # no staging or .wal leftovers
    assert result["estimate"]["basis"].startswith("overture_file:")
    assert len(session.registry.get(result["net_id"]).links_df()) > 0


def test_build_from_local_osm_to_zip_reopens(make_session, out_dir):
    session = make_session()
    result = session.dispatch(
        BuildNetwork(source="osm", input_file=OSM_FILE, output_dir=out_dir, output_format="zip", name="z")
    )
    dest = Path(out_dir) / "z.zip"
    assert result["output"] == str(dest.resolve()) and dest.is_file()
    assert sorted(p.name for p in Path(out_dir).iterdir()) == ["z.zip"]
    assert len(session.registry.get(result["net_id"]).links_df()) == 2


def test_build_by_area_uses_count_then_body_query(make_session, out_dir):
    http = FakeOverpass(ways=10)
    session = make_session(http=http)
    result = session.dispatch(_bbox_build(out_dir))
    assert [q.endswith("out count;") for q in http.queries] == [True, False]
    assert result["estimate"]["n_elements"] == 10
    assert len(session.registry.get(result["net_id"]).links_df()) == 2


def test_over_threshold_needs_approval_and_writes_nothing(make_session, out_dir):
    session = make_session(http=FakeOverpass(ways=10), overrides={"app.approve_above_s": 1})
    with pytest.raises(ApprovalRequired) as caught:
        session.dispatch(_bbox_build(out_dir))
    assert caught.value.estimate.seconds > 1 and caught.value.threshold_s == 1
    entry = session.history[-1]
    assert entry.error_type == "ApprovalRequired" and entry.result["estimate"]["n_elements"] == 10
    assert list(Path(out_dir).iterdir()) == [] and len(session.registry) == 0


def test_approved_build_runs_over_threshold(make_session, out_dir):
    session = make_session(http=FakeOverpass(ways=10), overrides={"app.approve_above_s": 1})
    result = session.dispatch(_bbox_build(out_dir, approved=True))
    assert result["net_id"] and result["approval"] == "given" and result["threshold_s"] == 1


def test_unavailable_estimate_needs_approval(make_session, out_dir):
    session = make_session(http=FakeOverpass(fail_count=True))
    with pytest.raises(ApprovalRequired, match="unavailable") as caught:
        session.dispatch(_bbox_build(out_dir))
    assert caught.value.estimate.seconds is None and "overpass unreachable" in caught.value.estimate.basis


def test_existing_destination_is_never_overwritten(make_session, out_dir):
    (Path(out_dir) / "tiny").mkdir()
    with pytest.raises(ActionError, match="already exists"):
        make_session().dispatch(
            BuildNetwork(source="osm", input_file=OSM_FILE, output_dir=out_dir, output_format="csv", name="tiny")
        )


def test_destination_appearing_mid_build_is_not_overwritten(make_session, out_dir, monkeypatch):
    real_write = build.write_output

    def write_then_race(net, tmp, output_format, ctx):
        real_write(net, tmp, output_format, ctx)
        (Path(out_dir) / "tiny").mkdir()  # someone else claimed the name while we were writing

    monkeypatch.setattr(build, "write_output", write_then_race)
    with pytest.raises(ActionError, match="already exists"):
        make_session().dispatch(
            BuildNetwork(source="osm", input_file=OSM_FILE, output_dir=out_dir, output_format="parquet", name="tiny")
        )
    assert [p.name for p in Path(out_dir).iterdir()] == ["tiny"] and not any((Path(out_dir) / "tiny").iterdir())


def test_failed_write_leaves_no_partial_output(make_session, out_dir, monkeypatch):
    def broken_write(self, dest, **kw):
        Path(dest).mkdir()
        (Path(dest) / "link.parquet").write_text("half")
        raise OSError("disk full")

    monkeypatch.setattr(Network, "write", broken_write)
    session = make_session()
    with pytest.raises(ActionError, match="disk full"):
        session.dispatch(
            BuildNetwork(source="osm", input_file=OSM_FILE, output_dir=out_dir, output_format="parquet", name="tiny")
        )
    assert list(Path(out_dir).iterdir()) == []
    assert session.history[-1].result["estimate"]["basis"].startswith("osm_file:")


def test_output_outside_roots_rejected(make_session, tmp_path_factory):
    elsewhere = str(tmp_path_factory.mktemp("not-allowed"))
    with pytest.raises(PathNotAllowed):
        make_session().dispatch(
            BuildNetwork(source="osm", input_file=OSM_FILE, output_dir=elsewhere, output_format="csv", name="x")
        )


def test_remote_output_dir_rejected(make_session):
    with pytest.raises(ActionError, match="must be a local path"):
        make_session().dispatch(
            BuildNetwork(source="osm", input_file=OSM_FILE, output_dir="s3://bucket/out", output_format="csv", name="x")
        )


def test_wrong_input_kind_rejected(make_session, out_dir):
    with pytest.raises(ActionError, match="not a local Overture snapshot"):
        make_session().dispatch(
            BuildNetwork(source="overture", input_file=OSM_FILE, output_dir=out_dir, output_format="csv", name="x")
        )


def test_cancel_build_during_query_leaves_no_output(make_session, out_dir):
    entered, release = threading.Event(), threading.Event()

    class SlowOverpass(FakeOverpass):
        def post(self, url, data=None, headers=None, timeout=None):
            if not data.endswith("out count;"):
                entered.set()
                release.wait(WAIT)
            return super().post(url, data, headers, timeout)

    session = make_session(http=SlowOverpass(ways=10))
    raised = []

    def blocking_dispatch():
        try:
            session.dispatch(_bbox_build(out_dir))
        except ActionError as exc:
            raised.append(exc)

    caller = threading.Thread(target=blocking_dispatch)
    caller.start()
    assert entered.wait(WAIT)
    (job,) = session.jobs.snapshots()
    session.jobs.cancel(job["id"])
    release.set()
    caller.join(WAIT)
    assert len(raised) == 1 and isinstance(raised[0], JobCancelled)  # dispatch re-raises the recorded type
    assert session.history[-1].error_type == "JobCancelled" and list(Path(out_dir).iterdir()) == []
    assert session.history[-1].result["estimate"]["n_elements"] == 10  # the estimate survives the cancel


def test_cancel_during_write_removes_the_staged_output(make_session, out_dir, monkeypatch):
    writing, release = threading.Event(), threading.Event()
    real_write = Network.write

    def slow_write(self, dest, **kw):
        real_write(self, dest, **kw)
        writing.set()
        release.wait(WAIT)

    monkeypatch.setattr(Network, "write", slow_write)
    session = make_session()
    job = session.submit(
        BuildNetwork(source="osm", input_file=OSM_FILE, output_dir=out_dir, output_format="parquet", name="tiny")
    )
    assert writing.wait(WAIT)
    assert len(list(Path(out_dir).iterdir())) == 1  # the hidden staging folder, fully written
    session.jobs.cancel(job.id)
    release.set()
    assert job.wait(WAIT) and session.jobs.snapshot(job)["status"] == "cancelled"
    assert list(Path(out_dir).iterdir()) == [] and len(session.registry) == 0


def test_open_duckdb_url_without_duckdb_extension(make_session, tmp_path):
    import shutil
    from importlib import resources

    db = tmp_path / "net.db"
    shutil.copy(str(resources.files("gmnspy.fixtures.leavenworth").joinpath("leavenworth.duckdb")), db)
    session = make_session()
    net_id = session.dispatch(OpenNetwork(source=f"duckdb://{db}"))["net_id"]
    assert len(session.registry.get(net_id).links_df()) > 0
    assert session.registry.get(net_id).source == f"duckdb://{db.resolve()}"


def test_promote_never_clobbers_a_file_that_appeared(tmp_path):
    tmp, dest = tmp_path / ".partial-1-net.zip", tmp_path / "net.zip"
    tmp.write_text("new")
    dest.write_text("theirs")
    with pytest.raises(ActionError, match="already exists"):
        build.promote(tmp, dest)
    assert dest.read_text() == "theirs" and tmp.read_text() == "new"  # staging() removes tmp afterwards
    dest.unlink()
    build.promote(tmp, dest)
    assert dest.read_text() == "new" and not tmp.exists()


def test_promote_never_replaces_an_empty_folder(tmp_path):
    tmp, dest = tmp_path / ".partial-1-net", tmp_path / "net"
    tmp.mkdir()
    dest.mkdir()
    with pytest.raises(ActionError, match="already exists"):
        build.promote(tmp, dest)
    assert tmp.is_dir() and dest.is_dir()


def test_reopen_failure_reports_the_written_output(make_session, out_dir, monkeypatch):
    session = make_session()

    def broken_load(source, spec_version):
        raise ActionError(f"could not open {source}: corrupt")

    monkeypatch.setattr(session, "_load", broken_load)
    with pytest.raises(ActionError, match=r"written to .* but could not be opened .* OpenNetwork"):
        session.dispatch(
            BuildNetwork(source="osm", input_file=OSM_FILE, output_dir=out_dir, output_format="zip", name="z")
        )
    dest = (Path(out_dir) / "z.zip").resolve()
    result = session.history[-1].result
    assert result["output"] == str(dest) and dest.is_file() and "estimate" in result
    assert len(session.registry) == 0


def test_missing_extra_is_an_error_not_an_approval(make_session, out_dir, monkeypatch):
    monkeypatch.setitem(sys.modules, "gmnspy.osm.query", None)  # import now raises ImportError
    session = make_session(http=FakeOverpass(ways=10))
    with pytest.raises(ActionError, match=r"gmnspy\[osm\]") as caught:
        session.dispatch(_bbox_build(out_dir))
    assert not isinstance(caught.value, ApprovalRequired) and session.history[-1].error_type == "ActionError"


def test_matching_name_suffix_is_not_doubled(make_session, out_dir):
    result = make_session().dispatch(
        BuildNetwork(source="osm", input_file=OSM_FILE, output_dir=out_dir, output_format="zip", name="tiny.zip")
    )
    assert Path(result["output"]).name == "tiny.zip"


def test_stale_partials_are_cleaned_fresh_ones_kept(make_session, out_dir):
    stale, fresh = Path(out_dir) / ".partial-aaaa-old", Path(out_dir) / ".partial-bbbb-new.zip"
    stale.mkdir()
    (stale / "link.parquet").write_text("x")
    fresh.write_text("in progress")
    old = time.time() - build.STALE_PARTIAL_S - 60
    os.utime(stale, (old, old))
    make_session().dispatch(
        BuildNetwork(source="osm", input_file=OSM_FILE, output_dir=out_dir, output_format="parquet", name="tiny")
    )
    assert sorted(p.name for p in Path(out_dir).iterdir()) == [fresh.name, "tiny"]


def test_staging_cleanup_removes_a_duckdb_wal(tmp_path):
    with pytest.raises(RuntimeError), build.staging(tmp_path / "net.duckdb") as tmp:
        tmp.write_text("db")
        tmp.with_name(f"{tmp.name}.wal").write_text("wal")
        raise RuntimeError("boom")
    assert list(tmp_path.iterdir()) == []
