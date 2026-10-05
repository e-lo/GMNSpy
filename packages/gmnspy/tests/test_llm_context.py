"""Tests for gmnspy.llm.context — the shipped assistant guide and project notes.

Project-note discovery follows a coordinator override of the original plan (see Task 12 of
docs/design/2026-10-02-nl-providers-plan.md): prefer a dedicated ``GMNSPY.md``, else fall back to
ONLY the ``## gmnspy`` section of ``AGENTS.md``, then of ``CLAUDE.md``. Coding-assistant files
carry instructions for a coding agent, not for the network's language-model features, so the rest
of either file must never be sent as network notes.
"""

import json

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
    (project / "AGENTS.md").write_text("## gmnspy\nproject agents notes\n")
    assert find_project_context(str(network), project) == project / "AGENTS.md"
    (network / "GMNSPY.md").write_text("network gmnspy notes")
    assert find_project_context(str(network), project) == network / "GMNSPY.md"
    (project / "GMNSPY.md").write_text("project gmnspy notes")
    assert find_project_context(str(network), project) == network / "GMNSPY.md"  # network wins


def test_agents_md_gmnspy_section_is_extracted(tmp_path):
    notes = tmp_path / "AGENTS.md"
    notes.write_text(
        "# Repo instructions\n\nGeneral coding rules that must never be sent.\n\n"
        "## gmnspy\n\nSR-520 = Evergreen Point Bridge\nthe Beltline = I 440\n\n"
        "## another tool\n\nunrelated instructions\n"
    )
    assert find_project_context(str(tmp_path), tmp_path) == notes
    text = read_capped(notes, 10_000)
    assert "SR-520 = Evergreen Point Bridge" in text
    assert "General coding rules" not in text
    assert "unrelated instructions" not in text


def test_agents_md_heading_matches_case_insensitively_any_level_up_to_h4(tmp_path):
    notes = tmp_path / "AGENTS.md"
    notes.write_text("#### GmnSpy\ncase-insensitive, level-4 heading\n### next heading\nstop here\n")
    assert find_project_context(str(tmp_path), tmp_path) == notes
    text = read_capped(notes, 10_000)
    assert "case-insensitive, level-4 heading" in text
    assert "stop here" not in text


def test_agents_md_without_a_gmnspy_section_yields_none(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# Repo instructions\n\nNo relevant section here.\n")
    assert find_project_context(str(tmp_path), tmp_path) is None


def test_claude_md_fallback_when_agents_md_has_no_section(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# Repo instructions\n\nNo relevant section here.\n")
    claude = tmp_path / "CLAUDE.md"
    claude.write_text("## gmnspy\nCLAUDE.md notes\n")
    assert find_project_context(str(tmp_path), tmp_path) == claude
    assert "CLAUDE.md notes" in read_capped(claude, 10_000)


def test_remote_sources_fall_back_to_the_project_dir(tmp_path):
    assert find_project_context("s3://bucket/net", tmp_path) is None
    (tmp_path / "AGENTS.md").write_text("## gmnspy\nproject notes only\n")
    assert find_project_context("s3://bucket/net", tmp_path) == tmp_path / "AGENTS.md"


def test_read_capped_names_the_file_and_caps_the_extracted_section(tmp_path):
    notes = tmp_path / "AGENTS.md"
    notes.write_text("## gmnspy\n" + "SR-520 = Evergreen Point Bridge\n" * 50)
    text = read_capped(notes, 80)
    assert text.startswith("Project notes from AGENTS.md:") and text.endswith("[… truncated at 80 characters …]")
    assert read_capped(notes, 0) == ""


def test_read_capped_caps_a_gmnspy_md_sent_whole(tmp_path):
    notes = tmp_path / "GMNSPY.md"
    notes.write_text("SR-520 = Evergreen Point Bridge\n" * 50)
    text = read_capped(notes, 80)
    assert text.startswith("Project notes from GMNSPY.md:") and text.endswith("[… truncated at 80 characters …]")
