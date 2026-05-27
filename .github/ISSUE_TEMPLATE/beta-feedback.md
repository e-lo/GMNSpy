---
name: Beta feedback
about: Tell us how the v1.0 beta is working for you — bugs, friction, surprises, or wins
title: '🧪  '
labels: ['🧪beta', 'triage']
assignees: ''

---

> Thanks for trying the v1.0 beta! This template captures the context we need to act on your feedback quickly. **You don't have to fill every section** — anything you can give us beats a silent fail.

## What did you try to do?

<!-- One or two sentences. Examples:
     - "Load a 200 MB GMNS parquet network and run validation"
     - "Convert our CSV-format network to DuckDB"
     - "Run `gmnspy mcp serve` from Claude Desktop and call describe_network"
     - "Self-host the HTTP server behind our nginx proxy"
-->

## What happened?

<!-- The actual outcome. Paste error messages, screenshots, or HTML reports if relevant.
     If it's a wrong answer rather than a crash, say what you expected vs got. -->

## Reproduction

<!-- The shortest command sequence that reproduces it. If the data is sensitive,
     describe the SHAPE of the network (table counts, row counts, format) and we'll
     reproduce against the Leavenworth fixture or generate synthetic data. -->

```bash
# Example:
uv run gmnspy validate /path/to/network
```

## Environment

Run `gmnspy doctor --json` and paste the output:

```json
```

If `doctor` won't run, please tell us:

- Package versions: `pip show datagrove gmnspy | grep -E 'Name|Version'`
- Python version: `python --version`
- OS / arch (macOS 14 / Linux x86_64 / etc.)
- Install method (`uv add gmnspy`, `pip install`, Docker image, …)

## What would have made this easier?

<!-- Optional. The shape of feedback we love most:
     - "I expected `gmnspy <command>` to do X but it does Y"
     - "The error message didn't tell me which file/column was bad"
     - "I had to read the source to figure out how to <thing>"
     - "Docs say X works but it doesn't" (paste the doc link if you can)
-->

## Anything else?

<!-- Optional: surprise wins, near-misses, ideas for v1.1, comparisons to other
     tools you've used (gmns-tools, tntp, custom scripts, GTFS workflows, etc.). -->

---

<details>
<summary>What happens after you submit this</summary>

- A maintainer triages within a few days and either: opens a follow-up bug/feature issue, asks for more reproduction info, or rolls the feedback into the v1.0 changelog.
- We do NOT promise turnaround SLAs during beta — this is volunteer time.
- **If your issue is blocking you and you need a workaround**, mention it in the body and we'll prioritise a response.

Thanks for helping shape v1.0. 💚
</details>
