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


def test_header_has_open_import_recent_and_jobs_not_the_path_box():
    html = (STATIC_DIR / "index.html").read_text()
    for element_id in ("open-wizard", "recent", "jobs-btn", "jobs-panel", "wizard"):
        assert f'id="{element_id}"' in html
    assert 'id="open-src"' not in html and 'id="open-go"' not in html


def test_wizard_modules_exist_and_are_wired_from_main():
    names = {p.name for p in JS_DIR.glob("*.js")}
    assert {"wizard.js", "filebrowser.js", "areapicker.js", "jobs.js"} <= names
    main = (JS_DIR / "main.js").read_text()
    assert 'from "./wizard.js"' in main and 'from "./jobs.js"' in main


def test_llm_module_never_persists_or_stores_key_text():
    src = (JS_DIR / "llm.js").read_text()
    for banned in ("localStorage", "sessionStorage", "indexedDB", "document.cookie", "./store.js"):
        assert banned not in src, f"llm.js must not use {banned}"


def test_llm_key_field_is_write_only():
    src = (JS_DIR / "llm.js").read_text()
    assert 'type="password"' in src and 'autocomplete="new-password"' in src
    assert "data-1p-ignore" in src and 'data-lpignore="true"' in src and "data-bwignore" in src
    assert "X-GMNSpy-Secrets" in src  # key writes and tests carry the secrets header


def test_header_has_the_llm_picker_and_panel():
    html = (STATIC_DIR / "index.html").read_text()
    for marker in ('id="nl-provider"', 'id="nl-model"', 'id="nl-dot"', 'id="nl-default"', 'id="nl-manage"'):
        assert marker in html
    assert 'id="llm-panel"' in html
    # The picker sits right after the utterance box (P1b may reflow the header; keep this adjacency).
    assert html.index('id="utterance"') < html.index('id="nl-picker"') < html.index('id="go"')
    main = (JS_DIR / "main.js").read_text()
    assert 'from "./llm.js"' in main and "llm:" in main  # wired, and subscribed to the `llm` SSE event


def test_ollama_setup_links_point_at_the_published_guide():
    from pathlib import Path

    from gmnspy.llm.providers.ollama import SETUP_DOCS_URL

    pkg = Path(__file__).resolve().parents[1]
    site_url = next(
        line.split(":", 1)[1].strip()
        for line in (pkg / "mkdocs.yml").read_text().splitlines()
        if line.startswith("site_url:")
    )
    assert f"{site_url.rstrip('/')}/cookbook/local-llm-ollama/" == SETUP_DOCS_URL
    assert (pkg / "docs" / "cookbook" / "local-llm-ollama.md").is_file()
    src = (JS_DIR / "llm.js").read_text()
    assert f'const OLLAMA_GUIDE = "{SETUP_DOCS_URL}"' in src
    assert '"/api/llm/ollama/pull", { model }, SECRETS' in src  # the pull carries the write-guard header
