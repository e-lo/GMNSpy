# Skills

Claude Code Skills shipped with the GMNSpy + datagrove monorepo.

## What's a Skill?

A Skill is a single markdown file (`SKILL.md`) with YAML frontmatter that
teaches Claude Code *when* and *how* to use a specific tool or workflow.
Each skill below covers one focused capability — validation, authoring,
conversion, or cleaning — with concrete examples that work against the
installed packages.

Skills are read by both humans and AI. Reading them top-to-bottom is the
fastest way to learn the corresponding feature.

## Install

Skills are loaded directly from this repository — no separate hosting.
Install one at a time:

```bash
claude code skill add https://github.com/e-lo/GMNSpy.git#path=skills/gmns-validate
```

Replace `gmns-validate` with any subdirectory listed below.

## Available skills

| Skill                                              | Use when…                                                                 |
| -------------------------------------------------- | ------------------------------------------------------------------------- |
| [`datagrove-validate`](datagrove-validate/SKILL.md) | Validating any Frictionless data package — generic, not GMNS-specific.    |
| [`gmns-author`](gmns-author/SKILL.md)               | Authoring or editing a GMNS network from scratch.                         |
| [`gmns-validate`](gmns-validate/SKILL.md)           | Interpreting `gmnspy validate` and `gmnspy quality` reports.              |
| [`gmns-convert`](gmns-convert/SKILL.md)             | Converting GMNS data between CSV, Parquet, DuckDB, and zip-CSV formats.   |
| [`gmns-clean`](gmns-clean/SKILL.md)                 | Simplifying geometries, merging nodes, dropping orphans — with rollback.  |

## License

All skills are licensed under Apache-2.0, the same as the rest of this
repository. See [LICENSE](../LICENSE) for the full text.
