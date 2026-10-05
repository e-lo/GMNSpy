"""Secrets never leave the workbench through a message, a label, a summary, or the Recent list."""

import json
import re
import shutil

import pytest
from gmnspy import Network
from gmnspy.select.parse import StubParser
from gmnspy.workbench.actions import OpenNetwork
from gmnspy.workbench.errors import ActionError
from gmnspy.workbench.redact import scrub
from gmnspy.workbench.registry import default_label
from gmnspy.workbench.server import STATIC_DIR
from gmnspy.workbench.session import Session

SIGNED = "https://bucket.s3.amazonaws.com/nets/lw?X-Amz-Signature=SECRET&X-Amz-Credential=AKIA#frag"


def test_scrub_keeps_scheme_host_path_and_leaves_local_paths_alone():
    assert scrub(f"could not open {SIGNED} (boom)", limit=None) == (
        "could not open https://bucket.s3.amazonaws.com/nets/lw (boom)"
    )
    assert scrub("az://u:p@acct/c/x?sig=S") == "az://acct/c/x"
    assert scrub("/data/net?odd name#1", limit=None) == "/data/net?odd name#1"
    assert len(scrub("x" * 500)) == 200 and len(scrub("x" * 500, limit=None)) == 500


@pytest.mark.parametrize(
    ("source", "label"),
    [
        (SIGNED, "lw"),
        ("https://h.example/net.parquet?sig=S", "net"),
        ("s3://b/k/rdu/parquet?v=1", "rdu"),
        ("https:/nohost?sig=S", "nohost"),  # malformed: the URL scrubber alone would miss it
        ("/data/odd?name/net", "net"),  # a local path keeps its '?'
    ],
)
def test_default_label_never_keeps_a_query_string(source, label):
    assert default_label(source) == label
    assert OpenNetwork(source=source).job_label() == f"open {label}"


@pytest.fixture
def session(tmp_path, isolated_env):
    return Session(project_dir=tmp_path, environ=isolated_env, parser=StubParser())


def test_open_failure_message_and_job_are_scrubbed(session, monkeypatch):
    def offline(source, **kw):
        raise OSError(f"HTTP 403 for {source}")

    monkeypatch.setattr(Network, "from_source", offline)
    with pytest.raises(ActionError) as exc:
        session.dispatch(OpenNetwork(source=SIGNED))
    assert str(exc.value) == (
        "could not open https://bucket.s3.amazonaws.com/nets/lw: HTTP 403 for https://bucket.s3.amazonaws.com/nets/lw"
    )
    job = session.jobs.snapshots()[0]
    assert "SECRET" not in json.dumps(job) and "AKIA" not in json.dumps(job)
    assert "SECRET" not in session.history[-1].error


def test_summary_source_is_scrubbed(session, rdu_source):
    session.add_network(Network.from_source(rdu_source), source=SIGNED)
    summary = session.state()["networks"][0]
    assert summary["source"] == "https://bucket.s3.amazonaws.com/nets/lw"
    assert session.registry.get(summary["id"]).source == SIGNED  # the handle keeps what it opened


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_recent_list_drops_query_strings_from_urls_only(tmp_path, run_node):
    header = (STATIC_DIR / "js" / "header.js").read_text()
    fn = re.search(r"function withoutSecrets\(source\) \{.*?\n\}", header, re.S)
    assert fn, "header.js must define withoutSecrets(source)"
    cases = {
        SIGNED: "https://bucket.s3.amazonaws.com/nets/lw",
        "s3://b/k?versionId=1": "s3://b/k",
        "/data/odd?name": "/data/odd?name",
        "duckdb:///data/x.duckdb": "duckdb:///data/x.duckdb",
    }
    script = tmp_path / "check.mjs"
    script.write_text(f"{fn.group(0)}\nconsole.log(JSON.stringify({json.dumps(list(cases))}.map(withoutSecrets)));\n")
    proc = run_node([str(script)])
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == list(cases.values())
