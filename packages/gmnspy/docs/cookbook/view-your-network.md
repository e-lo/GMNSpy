---
title: View a network on a map (with or without findings)
audience: users
kind: howto
summary: Render a self-contained interactive Leaflet map of any GMNS network — useful for sanity-checks, demos, and bug reports. The same renderer is what `gmnspy validate --html` wraps; here you use it directly, with or without validation overlays.
---

# View a network on a map

## When to use this

You want a one-file, send-it-to-a-colleague visual of a GMNS network — without
having to spin up a Jupyter notebook, a geopandas plot, or a folium map. Maybe
to confirm an OSM build covered the right area, demo the result of an edit,
attach to a bug report, or check that quality-rule findings cluster where you
expect them.

The renderer is the same one `gmnspy validate --html` uses. Calling it
directly lets you pass any list of [`Issue`][issue] objects (validation,
quality, graph topology, custom) as overlays — or none at all.

## Quick example

```python
from gmnspy import Network
from gmnspy.reports import render_network_html

net = Network.from_source("./my-network")
open("net.html", "w").write(render_network_html(net, title="My network"))
```

Open `net.html` in any browser. You'll see the link geometry as a thin
underlay on a Leaflet base map. No overlay markers because no issues were
passed.

## Overlaying validation findings

```python
from gmnspy.reports import render_validation_html

net = Network.from_source("./my-network")
report = net.validate()
open("net.html", "w").write(render_validation_html(net, report))
```

Each finding becomes a clickable marker, colour-coded by severity. Cross-cutting
findings (no row, no coords) appear in an "Unlocated findings" sidebar — still
clickable for the row-sync.

## Overlaying anything else

The renderer accepts a flat `list[Issue]`, so any `Issue` source plugs in
without renderer changes:

```python
from datagrove.reports import Category, Issue, Severity

custom = [
    Issue(
        severity=Severity.WARNING,
        category=Category.DATA_QUALITY,
        code="quality.signage_missing",
        message="no stop sign at intersection 42",
        extra={"lon": -120.66, "lat": 47.59},
    ),
]
open("net.html", "w").write(render_network_html(net, custom))
```

GMNS-specific data-quality rules (`gmnspy.quality.*`) already produce
`Issue` objects in this shape; graph-topology checks (`gmnspy.graph.*`)
do too.

## OpenStreetMap deep links

When the network has `osm_way_id` (and optionally `osm_node_id`) columns —
as produced by `gmnspy build`, the OSM importer — each marker's popup
carries an "Edit in OSM" link straight to the iD editor at
`openstreetmap.org/edit?editor=id&way=<id>`. Pass `osm_editor="josm"` to
target the desktop JOSM editor instead (via its localhost
RemoteControl plugin).

## Variations

??? note "Different base map"
    ```python
    render_network_html(net, tile_provider="carto-positron")
    ```

??? note "Embed in a Jupyter notebook"
    ```python
    from IPython.display import IFrame
    open("/tmp/net.html", "w").write(render_network_html(net, report.issues))
    IFrame("/tmp/net.html", 900, 600)
    ```

??? note "From the CLI"
    ```bash
    gmnspy validate <source> --html report.html  # findings overlay
    ```
    There is currently no `gmnspy view` CLI — for a no-findings network
    map, call the Python function directly. (Tracked as a follow-up.)

## Pitfalls

* **Requires the `[reports]` extra.** `pip install 'gmnspy[reports]'`
  (pulls in `jinja2` and `openpyxl`). Leaflet itself is vendored —
  no internet required when the report is opened.
* **No marker clustering yet.** Past a few thousand findings the Leaflet
  canvas slows down. Filter the issue list before passing it in.
* **`title=` controls the `<title>` tag.** It does not override how the
  network's spec version / link / node counts appear in the subtitle.

## See also

* [Validate a network](validate-network.md) — `--html` / `--csv` / `--xlsx`
  CLI flags wrap the same renderer.
* [Build from OSM](build-from-osm.md) — produces a network with
  `osm_way_id` columns so the "Edit in OSM" links light up.
* [Customise quality](customise-quality.md) — quality rules feed the same
  `Issue` overlay path.

[issue]: https://e-lo.github.io/GMNSpy/datagrove/api/reports/#datagrove.reports.Issue
