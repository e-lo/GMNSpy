---
title: Drive the CLI from an AI agent loop
audience: users
kind: howto
summary: Every gmnspy command emits one parseable JSON document on stdout — wire it into a tool-call loop with --json and DATAGROVE_AUTO_APPROVE.
---

# Drive the CLI from an AI agent loop

## When to use this

You're building an agent loop (Claude Code, a LangChain tool, a one-off shell harness) that needs to call `gmnspy` and parse the result. You don't want to spin up MCP for a stateless one-shot call.

## Quick example

```python
import json, subprocess

def validate(source: str) -> dict:
    """Tool function an LLM agent can call."""
    result = subprocess.run(
        ["gmnspy", "validate", "--json", source],
        capture_output=True, text=True, check=False,
    )
    report = json.loads(result.stdout)
    return {
        "ok": result.returncode == 0,
        "error_count": sum(1 for i in report["issues"] if i["severity"] == "error"),
        "spec_version": report["spec_version"],
        "issues": report["issues"][:5],   # cap context cost
    }

print(validate("packages/gmnspy/gmnspy/fixtures/leavenworth/csv"))
```

## Step-by-step

### 1. Every command supports `--json`

```shell-session
$ gmnspy info     --json <source>
$ gmnspy validate --json <source>
$ gmnspy quality  --json <source>
$ gmnspy scope from-nodes --json <source> 1 25 50
$ gmnspy clean    --json <source>
$ gmnspy bench    --json <source>
```

The `--json` contract: exactly one parseable JSON document on stdout, no log prefix, no progress bars, no trailing whitespace. `json.loads(proc.stdout)` always works on a successful run.

### 2. Stderr stays separate

Rich output (panels, tables, progress, approval prompts) goes to stderr. With `--json` on stdout the parser stays clean even when an approval prompt fires on stderr — the agent loop can either suppress stderr or surface it as side-channel feedback.

```python
result = subprocess.run(
    ["gmnspy", "validate", "--json", source],
    capture_output=True, text=True,
)
data = json.loads(result.stdout)        # always parseable
diagnostics = result.stderr             # human-readable, optional to display
```

### 3. Pre-approve gated operations

Mutating commands (`clean`, edit sessions) prompt for confirmation by default. In an agent loop, set the env var once instead of repeating `--yes` per call:

```python
import os, subprocess
env = {**os.environ, "DATAGROVE_AUTO_APPROVE": "1"}
subprocess.run(["gmnspy", "clean", "--json", source], env=env, check=False)
```

`--yes` on the command line works too. The env var is preferable for agents because it scopes to the process tree and survives `subprocess` calls from inside the loop.

### 4. Schema stability

The JSON shapes are stable inside a major version. Three types your loop is most likely to parse:

| Type | Shape (abridged) | Returned by |
|---|---|---|
| `ValidationReport` | `{issues: [{severity, category, code, message, table, column, row, fix_hint}], spec_version}` | `validate`, `quality` |
| `EditResult` | `{success, table, rows_changed, history_entry_id, dry_run, issues}` | `clean`, edit ops |
| Command summary | per-command `{source, ...}` dict, documented in API ref | `info`, `bench`, `scope` |

Full details: [API reference](../../gmnspy/reference/api.md).

### 5. Exit codes

| Command | Exit 0 | Exit 1 | Exit 2 |
|---|---|---|---|
| `validate` | no ERROR-severity issues | ≥1 ERROR issue | CLI usage error |
| `quality` | always (issues are WARNING/INFO) | — | CLI usage error |
| `clean` / edit | success or pure dry-run | failed precondition | CLI usage error |
| others | success | unhandled error | CLI usage error |

In agent loops, check `returncode` *and* parse the JSON — `returncode != 0` plus an `issues` array tells the model what went wrong.

## Common variations

| You want... | Pipe through |
|---|---|
| Quick filter on the shell | `gmnspy validate --json src \| jq '.issues[] \| select(.severity=="error")'` |
| One-liner in Python | `json.loads(subprocess.check_output(["gmnspy", "info", "--json", src]))` |
| Stateful flow (sessions, history) | use MCP — see [Wire the MCP server](../../gmnspy/cookbook/serve-mcp.md) |
| Streaming output | not supported; commands emit one document on completion |

## Pitfalls

* **Don't parse stderr.** It's intentionally human-formatted (rich panels, colour, prompts). Mixing it into your parser breaks on the next release.
* **Don't mix `--json` and non-`--json` calls in the same loop.** Pick one and stick to it — the model gets confused when half the tool outputs are JSON and half are panels.
* **Auto-approve makes destructive ops silent.** `DATAGROVE_AUTO_APPROVE=1` skips every confirmation including ones the user might *want* to be asked about. Scope the env var to the agent subprocess; don't export it shell-wide.

## See also

* [MCP tools reference](../../gmnspy/ai/mcp-tools.md) — richer, stateful surface for agents that can speak MCP.
* [AI surface](../ai/index.md) — how `--json` fits with `llms.txt`, `api-index.json`, and the Claude Code Skills.
