"""Session job actions: OpenNetwork / BuildNetwork run off the session lock, with approval and cancel."""

import threading

import pytest
from gmnspy import Network
from gmnspy.select.parse import StubParser
from gmnspy.workbench.actions import OpenNetwork
from gmnspy.workbench.errors import ActionError, PathNotAllowed
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


def test_file_url_is_rejected_not_a_roots_bypass(make_session, tmp_path_factory):
    session = make_session()
    elsewhere = tmp_path_factory.mktemp("not-allowed")
    with pytest.raises(ActionError, match="use a local path"):
        session.dispatch(OpenNetwork(source=elsewhere.as_uri()))
    assert session.history[-1].error_type == "ActionError" and len(session.registry) == 0


def test_open_bundled_zip(make_session):
    from importlib import resources

    source = str(resources.files("gmnspy.fixtures.leavenworth").joinpath("leavenworth.csv.zip"))
    session = make_session()
    net_id = session.dispatch(OpenNetwork(source=source))["net_id"]
    assert len(session.registry.get(net_id).links_df()) > 0
