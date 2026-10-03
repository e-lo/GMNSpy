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

Open <http://127.0.0.1:8850>. Open more networks with **Open / Import…** in the header (see below) or
the **Recent** list, and switch between them with the network picker. `gmnspy viz` and `gmnspy select-serve`
are aliases of `gmnspy app`.

```bash
uv run gmnspy app ./base ./build --port 8900 --basemap esri --provider claude
```

The server binds `127.0.0.1` by default. While bound to a local host (`127.0.0.1`, `localhost`, or `[::1]`),
it only accepts requests whose `Host` header names that same local address, and it rejects any cross-origin
write (a POST from a page with a different origin, or flagged `Sec-Fetch-Site: cross-site`). `--host 0.0.0.0`
exposes it to the rest of the network — there's no authentication in front of it, so don't do that on a
shared network.

> **Known issue.** Running with `--host 0.0.0.0` while `io.allowed_roots` is empty (the default) lets anyone
> on your network browse your home folder through the server-side file browser described below, with no
> authentication. Set `io.allowed_roots` to the specific folders you want exposed before binding to
> `0.0.0.0`, or don't use `--host 0.0.0.0` on a shared network. This is a known limitation, not something
> a future release has silently fixed — check the current docs before relying on it.

## Open or import a network

**Open / Import…** opens a wizard with four sources:

- **GMNS on this machine**: a server-side file browser. Entries are tagged (GMNS folder, `.zip`, `.duckdb`,
  `datapackage.json`); pick one and it opens in place. Nothing is uploaded.
- **GMNS at a URL** (`s3://`, `gs://`, `az://`, `https://`): **Check** says whether the URL is reachable, which
  credential source would be used (`env`, `keyring`, `netrc`, or `none`; never the secret), and which tables it found.
- **Build from OpenStreetMap** or **Build from Overture**: choose an area by drawing a rectangle (drag its corners
  to adjust), typing `W,S,E,N` or a point plus a buffer, or searching for a place and picking one of the
  outlines. You can instead pick a local file: a `.osm` XML file or an Overpass JSON export for OSM, or an
  Overture snapshot folder holding `segment.parquet` + `connector.parquet` (see `gmnspy.overture.layout`).

A build always writes to the output folder and format you choose (Parquet, CSV, DuckDB, or Zip) and then opens
the result from disk, so what you see is what was saved. It never overwrites an existing output; a leftover
hidden `.partial-*` staging folder from a crashed build is cleaned up automatically once it's more than 24
hours old. The output `name` must be a plain file name — no path separators, no trailing dot — and if it ends
in a format suffix (`.zip`, `.duckdb`, `.csv`, `.parquet`), that suffix must match the format you chose.

Before a build runs, the wizard shows an estimate of its time and size, from a quick count (Overpass
`out count`, or a DuckDB `COUNT(*)` over Overture) and a simple cost model. When the estimate is over
`app.approve_above_s` (90 s by default), or when the count fails, the button changes to **Run (~N min)** or
**Run anyway**, and the build only starts when you click it. The cost model's numbers are in
`gmnspy/workbench/data/build_cost.toml`; they are rough, so treat the estimate as a guide.

Opens and builds run as background jobs. The **Jobs** button in the header shows their stage and progress and
lets you cancel one; a cancel takes effect when the job reaches its next stage.

### Which folders the app can read and write

The file browser, opening a local path, and build input and output folders are all limited to
`io.allowed_roots`. When that list is empty (the default) it means your home folder. Paths given to
`gmnspy app` on the command line are always allowed for that session.

A remote source must look like `scheme://host/...` (for example `s3://bucket/net`) and must not contain any
`..` path segments. `file://` and `duckdb://` sources are treated as local paths in disguise and are checked
against `io.allowed_roots` like any other local path.

```toml
# ./gmnspy.toml
[io]
allowed_roots = ["~/networks", "/data/gmns"]

[app]
approve_above_s = 120
```

### The same thing from Python

A build is an ordinary action, so the history strip shows it as Python you can replay. The replayed call always
passes `approved=True`, because re-running a build you already approved counts as approval.

<!-- doctest: skip -->
```python
from gmnspy.workbench import BuildNetwork, Session

app = Session()
app.do(
    BuildNetwork(
        source="osm",
        area={"kind": "bbox", "bbox": (-78.91, 35.98, -78.88, 36.01)},
        output_dir="/home/me/networks",
        output_format="parquet",
        name="durham-core",
        approved=True,
    )
)
```

Without `approved=True`, a build over the threshold raises `gmnspy.workbench.ApprovalRequired`, and its
`.estimate` holds the estimate.

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
a script you can copy. Networks added from Python via `Session.add_network` aren't recorded as actions
and so aren't replayed in that script.
