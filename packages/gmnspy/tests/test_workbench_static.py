"""Static front-end checks: served, module graph consistent, JS syntax valid."""

import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from gmnspy.workbench import Session, build_app
from gmnspy.workbench.server import STATIC_DIR

JS_DIR = STATIC_DIR / "js"
_IMPORT = re.compile(r'import\s*\{([^}]*)\}\s*from\s*"\./([\w-]+\.js)"')
_EXPORT = re.compile(r"export\s+(?:async\s+)?(?:function|const|let)\s+([\w$]+)")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("wb")
    return TestClient(build_app(Session(project_dir=tmp, environ={"GMNSPY_CONFIG_DIR": str(tmp / "u")})))


def test_index_loads_main_module(client):
    html = client.get("/").text
    assert '<script type="module" src="/static/js/main.js">' in html
    assert "/static/app.css" in html


@pytest.mark.parametrize("name", sorted(p.name for p in JS_DIR.glob("*.js")))
def test_every_module_is_served_as_javascript(client, name):
    r = client.get(f"/static/js/{name}")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]


def test_relative_imports_resolve_to_real_exports():
    exports = {p.name: set(_EXPORT.findall(p.read_text())) for p in JS_DIR.glob("*.js")}
    for path in JS_DIR.glob("*.js"):
        for names, target in _IMPORT.findall(path.read_text()):
            assert target in exports, f"{path.name} imports missing module {target}"
            for name in (n.strip() for n in names.split(",") if n.strip()):
                assert name in exports[target], f"{path.name} imports {name!r} not exported by {target}"


def test_every_element_id_used_by_js_exists_in_index():
    html = (STATIC_DIR / "index.html").read_text()
    ids = set(re.findall(r'id="([\w-]+)"', html))
    for path in JS_DIR.glob("*.js"):
        for used in re.findall(r'\$\("([\w-]+)"\)', path.read_text()):
            assert used in ids, f"{path.name} uses #{used} which index.html lacks"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_syntax(tmp_path):
    for path in JS_DIR.glob("*.js"):
        target = tmp_path / (path.stem + ".mjs")
        target.write_text(path.read_text())
        proc = subprocess.run(["node", "--check", str(target)], capture_output=True, text=True)
        assert proc.returncode == 0, f"{path.name}: {proc.stderr}"
