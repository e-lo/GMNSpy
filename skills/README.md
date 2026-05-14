# Skills

Claude Code Skills shipped with the GMNSpy + datagrove monorepo.

## Install

Skills are loaded from this repository — no hosting required. From your terminal:

```bash
claude code skill add https://github.com/e-lo/GMNSpy.git#path=skills/gmns-validate
```

Replace `gmns-validate` with any subdirectory below.

## Available skills

- [`datagrove-validate`](datagrove-validate/SKILL.md) — generic Frictionless data-package validation guidance.
- [`gmns-author`](gmns-author/SKILL.md) — authoring and editing GMNS networks.
- [`gmns-validate`](gmns-validate/SKILL.md) — interpreting GMNS validation reports + data-quality flags.
- [`gmns-convert`](gmns-convert/SKILL.md) — converting between GMNS storage formats.
- [`gmns-clean`](gmns-clean/SKILL.md) — safely cleaning networks with rollback.
