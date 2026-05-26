---
title: Visual tour
audience: users
kind: tutorial
summary: See the bundled Leavenworth fixture rendered as a map, a validation report, a data-quality report, and a before/after edit — all from a single notebook session.
---

# Visual tour

!!! info "Stub — to be filled in Wave 4"
    This page is scaffolded. The content fill is tracked in [issue #96](https://github.com/e-lo/GMNSpy/issues/96) and follows the [Page Style Guide](../_page-style-guide.md).

## What you'll see

* Leavenworth as a Folium / Leaflet map embed.
* A live validation report (rich rendering).
* A data-quality report with severity grouping.
* A simplify-geometry before/after via the editing layer.

## Prerequisites

```text
$ pip install 'gmnspy[clean,notebook]'
```

## Steps

1. Load the fixture.
2. Render the network as a map.
3. Validate + display the report.
4. Run the quality pack + display.
5. Simplify geometry + render before/after.

## Next steps

* [Cookbook](../cookbook/index.md) — go deeper on any of these workflows.
* [Architecture](../architecture.md) — design rationale.
