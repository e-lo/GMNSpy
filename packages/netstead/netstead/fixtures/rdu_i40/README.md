# rdu_i40 fixture

A small GMNS network synthesized from OpenStreetMap covering an I-40 stretch in
Research Triangle Park, NC (South Miami Boulevard, Page Road, and Airport
Boulevard interchanges). Trimmed to a 4-hop graph buffer around the I-40
mainline so ramp→surface→mainline connectivity at each interchange is intact.

Carries the OSM `ref` tag (via `extra_tags=["ref"]` at build time) because
interstates/state routes live in `ref`, not `name`. Used by
`netstead.select` tests to exercise natural-language selection on real
limited-access interchange topology.

Rebuild: `python build.py` (run from the `packages/netstead` dir with the
`[osm,graph]` extras installed; hits the Overpass API). Data © OpenStreetMap
contributors, ODbL.

Load in code: `Network.from_source(<this dir>/'parquet')` (or `/'csv'`) — the
loader auto-discovers GMNS tables by filename; no datapackage.json needed.
