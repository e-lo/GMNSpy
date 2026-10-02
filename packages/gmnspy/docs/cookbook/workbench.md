---
title: Explore networks in the GMNSpy Workbench
audience: users
kind: howto
summary: Open one or more GMNS networks in a local browser app. The map and tables are linked, natural-language selection is built in, and every action can be replayed as Python.
---

# Explore networks in the GMNSpy Workbench

## When to use this

You want to look around a network interactively. That means panning the map, browsing tables, checking
what a selection phrase resolves to, and copying the exact Python that reproduces what you did.
For a single self-contained HTML file to send someone, see [View a network on a map](view-your-network.md).

## Quick start

```bash
uv run gmnspy app ./my-network
```

Open <http://127.0.0.1:8850>. You can open more networks from the header (a path or URL) and switch between
them with the network picker. `gmnspy viz` and `gmnspy select-serve` are aliases of `gmnspy app`.

```bash
uv run gmnspy app ./base ./build --port 8900 --basemap esri --provider claude
```

The server binds `127.0.0.1` by default and, while bound to a loopback host, only accepts requests whose
`Host` header names that same loopback address. `--host 0.0.0.0` exposes it to the rest of the network —
there's no authentication in front of it, so don't do that on a shared network.

## Settings

The workbench reads layered settings. From lowest to highest precedence:

1. built-in defaults
2. `~/.config/gmnspy/config.toml`
3. `./gmnspy.toml`
4. `GMNSPY_<SECTION>__<FIELD>` environment variables
5. command-line flags

```toml
# ./gmnspy.toml
[app]
port = 8900

[viz]
basemap = "esri"

[select]
provider = "claude"
```

## Every action is replayable

Everything you do in the browser is a typed action: open, select, style, navigate, change a setting.
The strip at the bottom shows the last action as Python. **Session as Python** shows the whole session as
a script you can copy.
