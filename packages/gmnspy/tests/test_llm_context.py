"""Tests for gmnspy.llm.context — the shipped assistant guide and project notes.

Project-note discovery follows a coordinator override of the original plan (see Task 12 of
docs/design/2026-10-02-nl-providers-plan.md): prefer a dedicated ``GMNSPY.md``, else fall back to
ONLY the ``## gmnspy`` section of ``AGENTS.md``, then of ``CLAUDE.md``. Coding-assistant files
carry instructions for a coding agent, not for the network's language-model features, so the rest
of either file must never be sent as network notes.

Every candidate is also resolved and checked against caller-supplied ``roots`` before it is read,
so a symlink cannot be used to smuggle an arbitrary file on disk into a prompt.
"""

import json
import sys

import pytest
from gmnspy.llm.context import assistant_context, find_project_context, read_capped
from gmnspy.select.parse import INTENT_TOOL


def test_guide_covers_every_tool_field_and_its_examples_are_valid_tool_input():
    guide = assistant_context(100_000)
    for field in INTENT_TOOL["input_schema"]["properties"]:
        assert f"`{field}`" in guide, field
    examples = [line.removeprefix("Tool input: ") for line in guide.splitlines() if line.startswith("Tool input: ")]
    assert len(examples) >= 5
    for example in examples:
        assert set(json.loads(example)) <= set(INTENT_TOOL["input_schema"]["properties"])


def test_guide_is_capped():
    capped = assistant_context(200)
    assert capped.startswith("# GMNS assistant guide") and capped.endswith("[… truncated at 200 characters …]")


def test_gmnspy_md_takes_precedence_over_agents_and_claude(tmp_path):
    network, project = tmp_path / "net", tmp_path / "proj"
    network.mkdir()
    project.mkdir()
    roots = [tmp_path]
    (project / "AGENTS.md").write_text("## gmnspy\nproject agents notes\n")
    assert find_project_context(str(network), project, roots) == project / "AGENTS.md"
    (network / "GMNSPY.md").write_text("network gmnspy notes")
    assert find_project_context(str(network), project, roots) == network / "GMNSPY.md"
    (project / "GMNSPY.md").write_text("project gmnspy notes")
    assert find_project_context(str(network), project, roots) == network / "GMNSPY.md"  # network wins


def test_agents_md_gmnspy_section_is_extracted(tmp_path):
    notes = tmp_path / "AGENTS.md"
    notes.write_text(
        "# Repo instructions\n\nGeneral coding rules that must never be sent.\n\n"
        "## gmnspy\n\nSR-520 = Evergreen Point Bridge\nthe Beltline = I 440\n\n"
        "## another tool\n\nunrelated instructions\n"
    )
    roots = [tmp_path]
    assert find_project_context(str(tmp_path), tmp_path, roots) == notes
    text = read_capped(notes, 10_000, roots)
    assert "SR-520 = Evergreen Point Bridge" in text
    assert "General coding rules" not in text
    assert "unrelated instructions" not in text


def test_agents_md_heading_matches_case_insensitively_any_level_up_to_h4(tmp_path):
    notes = tmp_path / "AGENTS.md"
    notes.write_text("#### GmnSpy\ncase-insensitive, level-4 heading\n### next heading\nstop here\n")
    roots = [tmp_path]
    assert find_project_context(str(tmp_path), tmp_path, roots) == notes
    text = read_capped(notes, 10_000, roots)
    assert "case-insensitive, level-4 heading" in text
    assert "stop here" not in text


def test_agents_md_without_a_gmnspy_section_yields_none(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# Repo instructions\n\nNo relevant section here.\n")
    assert find_project_context(str(tmp_path), tmp_path, [tmp_path]) is None


def test_claude_md_fallback_when_agents_md_has_no_section(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# Repo instructions\n\nNo relevant section here.\n")
    claude = tmp_path / "CLAUDE.md"
    claude.write_text("## gmnspy\nCLAUDE.md notes\n")
    roots = [tmp_path]
    assert find_project_context(str(tmp_path), tmp_path, roots) == claude
    assert "CLAUDE.md notes" in read_capped(claude, 10_000, roots)


def test_remote_sources_fall_back_to_the_project_dir(tmp_path):
    roots = [tmp_path]
    assert find_project_context("s3://bucket/net", tmp_path, roots) is None
    (tmp_path / "AGENTS.md").write_text("## gmnspy\nproject notes only\n")
    assert find_project_context("s3://bucket/net", tmp_path, roots) == tmp_path / "AGENTS.md"


def test_read_capped_names_the_file_and_caps_the_extracted_section(tmp_path):
    notes = tmp_path / "AGENTS.md"
    notes.write_text("## gmnspy\n" + "SR-520 = Evergreen Point Bridge\n" * 50)
    roots = [tmp_path]
    text = read_capped(notes, 80, roots)
    assert text.startswith("Project notes from AGENTS.md:") and text.endswith("[… truncated at 80 characters …]")
    assert read_capped(notes, 0, roots) == ""


def test_read_capped_caps_a_gmnspy_md_sent_whole(tmp_path):
    notes = tmp_path / "GMNSPY.md"
    notes.write_text("SR-520 = Evergreen Point Bridge\n" * 50)
    roots = [tmp_path]
    text = read_capped(notes, 80, roots)
    assert text.startswith("Project notes from GMNSPY.md:") and text.endswith("[… truncated at 80 characters …]")


# --- Symlink / allowed-roots -------------------------------------------------------------------

requires_symlink = pytest.mark.skipif(
    sys.platform == "win32", reason="symlink creation needs elevated privileges on Windows"
)


@requires_symlink
def test_gmnspy_md_symlink_escaping_the_roots_is_skipped(tmp_path):
    network, project, outside = tmp_path / "net", tmp_path / "proj", tmp_path / "outside"
    network.mkdir()
    project.mkdir()
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("not a project note")
    (network / "GMNSPY.md").symlink_to(secret)
    roots = [network, project]  # outside/ is deliberately not an allowed root
    # The symlinked GMNSPY.md is skipped; there's nothing else, so no notes are found.
    assert find_project_context(str(network), project, roots) is None
    # It falls through to the next candidate when one exists.
    (project / "AGENTS.md").write_text("## gmnspy\nfallback notes\n")
    assert find_project_context(str(network), project, roots) == project / "AGENTS.md"


@requires_symlink
def test_agents_md_symlink_escaping_the_roots_is_skipped(tmp_path):
    network, outside = tmp_path / "net", tmp_path / "outside"
    network.mkdir()
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("## gmnspy\nsecret notes that must never be read\n")
    (network / "AGENTS.md").symlink_to(secret)
    roots = [network]
    assert find_project_context(str(network), None, roots) is None


@requires_symlink
def test_read_capped_refuses_a_path_outside_the_roots(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "GMNSPY.md"
    secret.write_text("secret notes")
    assert read_capped(secret, 10_000, [tmp_path / "net"]) == ""


# --- Fence-aware heading matching ---------------------------------------------------------------


def test_heading_only_inside_a_fence_does_not_match(tmp_path):
    notes = tmp_path / "AGENTS.md"
    notes.write_text("```\n## gmnspy\nnot a real heading\n```\n")
    assert find_project_context(str(tmp_path), tmp_path, [tmp_path]) is None


def test_fenced_hash_comment_inside_the_section_does_not_end_it(tmp_path):
    notes = tmp_path / "AGENTS.md"
    notes.write_text(
        "## gmnspy\n\nbefore the fence\n\n```python\n# comment\nstill_code = True\n```\n\nafter the fence\n\n"
        "## next section\n\nnot included\n"
    )
    roots = [tmp_path]
    assert find_project_context(str(tmp_path), tmp_path, roots) == notes
    text = read_capped(notes, 10_000, roots)
    assert "before the fence" in text
    assert "# comment" in text
    assert "after the fence" in text
    assert "not included" not in text


def test_tilde_fence_is_also_respected(tmp_path):
    notes = tmp_path / "AGENTS.md"
    notes.write_text("## gmnspy\nkept\n~~~\n## not a heading\n~~~\n## next\nskipped\n")
    roots = [tmp_path]
    text = read_capped(notes, 10_000, roots)
    assert "kept" in text
    assert "## not a heading" in text  # the fenced line's text is kept verbatim, just not parsed as a heading
    assert "skipped" not in text


# --- No cwd fallback ------------------------------------------------------------------------


def test_project_dir_none_never_falls_back_to_the_current_working_directory(tmp_path, monkeypatch):
    network = tmp_path / "net"
    network.mkdir()
    cwd = tmp_path / "cwd_with_notes"
    cwd.mkdir()
    (cwd / "GMNSPY.md").write_text("notes that live only in the cwd")
    monkeypatch.chdir(cwd)
    # roots deliberately include the cwd, to prove it's project_dir=None (not an allowed-roots
    # rejection) that keeps it out of the search.
    assert find_project_context(str(network), None, [network, cwd]) is None


# --- Size guard -----------------------------------------------------------------------------


def test_oversized_gmnspy_md_is_skipped_by_discovery(tmp_path):
    network, project = tmp_path / "net", tmp_path / "proj"
    network.mkdir()
    project.mkdir()
    (network / "GMNSPY.md").write_text("x" * 1_100_000)
    (project / "AGENTS.md").write_text("## gmnspy\nsmall fallback notes\n")
    assert find_project_context(str(network), project, [tmp_path]) == project / "AGENTS.md"


def test_oversized_project_notes_are_truncated_not_read_whole(tmp_path):
    notes = tmp_path / "AGENTS.md"
    notes.write_text("## gmnspy\n" + "x" * 1_100_000)
    text = read_capped(notes, 50, [tmp_path])
    assert text.endswith("[… truncated at 50 characters …]")
    assert len(text) < 1_100_000


# --- Minor regressions ------------------------------------------------------------------------


def test_trailing_hashes_on_the_heading_are_stripped(tmp_path):
    notes = tmp_path / "AGENTS.md"
    notes.write_text("## gmnspy ##\nnotes under a closed ATX heading\n")
    roots = [tmp_path]
    assert find_project_context(str(tmp_path), tmp_path, roots) == notes
    assert "notes under a closed ATX heading" in read_capped(notes, 10_000, roots)


def test_a_leading_byte_order_mark_does_not_hide_the_heading(tmp_path):
    notes = tmp_path / "AGENTS.md"
    notes.write_bytes("## gmnspy\nnotes right after a BOM\n".encode("utf-8-sig"))
    roots = [tmp_path]
    assert find_project_context(str(tmp_path), tmp_path, roots) == notes
    assert "notes right after a BOM" in read_capped(notes, 10_000, roots)
