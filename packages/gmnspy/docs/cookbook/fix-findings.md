---
title: Triage findings, propose fixes, apply them
audience: users
kind: howto
summary: Use the interactive viewer to propose fixes on individual validation findings, download them as a YAML edit log, and replay the log against your network in Python — with overwrite or save-as.
---

# Triage findings, propose fixes, apply them

## When to use this

You ran `gmnspy validate` and you have findings to address. You want to
triage them visually, propose fixes one at a time without writing
Python for each, then apply them deterministically and save. The flow
splits cleanly into two halves:

1. **Browser** — open the HTML report, click each finding's "Propose
   fix" button, accumulate an edit log.
2. **Python** — load the log, replay it against your network, save
   (overwrite or save-as).

The split lets you triage clickwise but always end up with a structured,
replay-able record of what changed.

## Quick example

```bash
# 1. Generate the validation report
uv run gmnspy validate ./my-net --html /tmp/report.html
open /tmp/report.html
```

In the browser:

- Each finding marker → click → popup with `Propose fix` button
- Click `Propose fix` → inline editor with the column pre-filled and
  the current value loaded → enter new value + reason → `Add to edit log`
- Bottom-right floating sidebar tracks your edits — `Download YAML`
  when done

Then back in Python:

```python
from gmnspy import Network
from gmnspy.map.edits import apply_edits, load_edit_log

net = Network.from_source("./my-net")
log = load_edit_log("/path/to/edits-2026-06-30T19-00-00.yaml")
result = apply_edits(net, log)

print(result.summary())                # "12 applied, 2 skipped"
for s in result.skipped:               # inspect anything that didn't apply
    print(s.edit.id, "→", s.reason)

# Save either way
result.net.save()                      # overwrite the source
result.net.save_as("./my-net-v2")      # write to a new directory
```

## The edit log shape

A YAML file under a top-level `edit_log:` key. Each entry is one fix
proposal, identified by table + primary key (not by positional row
index — PKs survive row reordering / partial reloads):

```yaml
edit_log:
  schema_version: '1'
  created_at: 2026-06-30T19:00:00Z
  client: gmnspy.map (browser)
  edits:
    - id: el7f9c3a
      kind: fix
      table: link
      pk:
        link_id: 42
      column: free_speed
      from: null
      to: 25
      reason: 'schema.required: free_speed missing'
      issue_id: i0
      timestamp: 2026-06-30T19:01:23Z
```

`from:` is the value the browser-side editor *thought* was there when
you proposed the fix. The applier uses it for a drift check — if the
table's current value differs, the edit is skipped (with a reason)
rather than silently clobbering a concurrent change. Use `from: null`
to disable the drift check.

## Variations

??? note "Pass the log to a colleague (review workflow)"
    Don't apply anything locally. Download the YAML, email it (or open
    a PR with it). They run `apply_edits` against their copy of the
    network when they're ready.

??? note "Replay against a newer version of the same network"
    The vendor sent you v2 of the network. Run `apply_edits(v2_net, log)`
    — every edit whose PK still exists and whose `from:` still matches
    applies cleanly. Anything that drifted shows up in `result.skipped`
    with a precise reason.

??? note "Bulk fixes from Python"
    `Edit` is a plain dataclass — build a `list[Edit]` programmatically
    for "every residential link with free_speed > 25 should be set to
    25" and apply with the same `apply_edits` path. No browser needed.

??? note "Clear the log mid-session"
    The browser persists edits in `sessionStorage`. A page refresh
    keeps them. The sidebar's `Clear` button drops them (with a confirm
    prompt).

## Pitfalls

- **The browser-side log is per-session.** It lives in `sessionStorage`,
  so opening the report in a different tab gives you a fresh log. Always
  Download YAML before closing the tab if you want to keep the work.
- **Edits identify rows by PK, not row index.** That's deliberate — row
  index isn't stable across reloads. If your edit log carries
  `pk: { link_id: 42 }` and link_id 42 no longer exists in the
  destination network, the applier skips with `pk not found`.
- **Drift checks compare values pre-cast.** When the source column is a
  number, the editor coerces the new value to a number too. When in
  doubt, look at the YAML — `from: 40` vs `from: '40'` matter for
  the strict drift check.

## See also

* [View a network on a map](view-your-network.md) — the embedding the
  edit-log UI lives on top of.
* [Validate a network](validate-network.md) — produces the findings the
  Propose-fix flow targets.
* `gmnspy.map.NetworkMap` — the embeddable component itself.
