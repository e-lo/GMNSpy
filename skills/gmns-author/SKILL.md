---
name: gmns-author
description: Author or edit a GMNS network from scratch — the minimum link.csv + node.csv schema, common pitfalls, and a validate-as-you-go loop. Use when the user wants to construct a small GMNS network programmatically or hand-edit one.
---

# gmns-author

Use this skill when a user says "I want to build a GMNS network for X,"
"how do I make a node table?", "what columns do I need in link.csv?", or
asks for a minimal working example. This skill is about *creating* GMNS
data; for *checking* an existing network, use `gmns-validate`.

A valid GMNS network needs, at minimum, two CSVs (`node.csv` and `link.csv`)
plus a `datapackage.json` that declares them. The full GMNS spec defines
many more tables (lane, signal, segment, etc.) but they are all optional.
Start small, validate, then add tables as needed.

## Workflow

1. **Decide what you're modeling.** Nodes are intersections / endpoints;
   links are the roadway segments between them. Every link references two
   nodes by id.
2. **Write `node.csv` first.** Required columns:
   - `node_id` (int, unique, primary key)
   - `x_coord` (float, longitude in WGS84 unless your schema says otherwise)
   - `y_coord` (float, latitude)
   Optional but common: `node_type`, `ctrl_type`, `zone_id`.
3. **Write `link.csv`.** Required columns:
   - `link_id` (int, unique)
   - `from_node_id` (int, FK → node.node_id)
   - `to_node_id` (int, FK → node.node_id)
   - `length` (float, meters by default)
   - `lanes` (int)
   - `free_speed` (float, in your declared units — kph or mph)
   - `capacity` (float, vehicles per hour per lane)
   Optional: `facility_type`, `link_type`, `geometry` (WKT LINESTRING),
   `dir_flag`.
4. **Create `datapackage.json`.** The easiest path is to copy the GMNS
   reference one from `packages/gmnspy/gmnspy/fixtures/leavenworth/csv/` and
   trim it to just `node` and `link`.
5. **Validate after every change.** Run `gmnspy validate <dir> --json`
   between edits. Fix `schema.required` and `fk.missing_target` before
   adding more rows.
6. **Load it programmatically** with `Network.from_source(path)` to confirm
   it round-trips through the gmnspy data model.

## Example

A 3-node, 2-link network — the smallest useful GMNS example. Save these
three files in a fresh directory:

`node.csv`

```csv
node_id,x_coord,y_coord,node_type
1,-120.6615,47.5965,
2,-120.6602,47.5961,
3,-120.6588,47.5957,
```

`link.csv`

```csv
link_id,from_node_id,to_node_id,length,lanes,free_speed,capacity,facility_type
101,1,2,105.4,2,40,1800,local
102,2,3,108.7,2,40,1800,local
```

`datapackage.json`

```json
{
  "name": "tiny-gmns",
  "profile": "tabular-data-package",
  "resources": [
    {
      "name": "node",
      "path": "node.csv",
      "schema": {
        "fields": [
          {"name": "node_id", "type": "integer", "constraints": {"required": true, "unique": true}},
          {"name": "x_coord", "type": "number", "constraints": {"required": true}},
          {"name": "y_coord", "type": "number", "constraints": {"required": true}},
          {"name": "node_type", "type": "string"}
        ],
        "primaryKey": "node_id"
      }
    },
    {
      "name": "link",
      "path": "link.csv",
      "schema": {
        "fields": [
          {"name": "link_id", "type": "integer", "constraints": {"required": true, "unique": true}},
          {"name": "from_node_id", "type": "integer", "constraints": {"required": true}},
          {"name": "to_node_id", "type": "integer", "constraints": {"required": true}},
          {"name": "length", "type": "number"},
          {"name": "lanes", "type": "integer"},
          {"name": "free_speed", "type": "number"},
          {"name": "capacity", "type": "number"},
          {"name": "facility_type", "type": "string"}
        ],
        "primaryKey": "link_id",
        "foreignKeys": [
          {"fields": "from_node_id", "reference": {"resource": "node", "fields": "node_id"}},
          {"fields": "to_node_id",   "reference": {"resource": "node", "fields": "node_id"}}
        ]
      }
    }
  ]
}
```

Validate and load:

```bash
gmnspy validate ./tiny-gmns --json | jq '.summary'
# {"errors": 0, "warnings": 0, "tables": 2}
```

```python
from gmnspy import Network

net = Network.from_source("./tiny-gmns")
print(len(net.nodes), "nodes;", len(net.links), "links")
# 3 nodes; 2 links
```

## Common pitfalls

- **Off-by-one node ids** in `from_node_id` / `to_node_id` → `fk.missing_target`.
  Always validate after appending links.
- **Lat/lon swapped** (`x_coord` is *longitude*, `y_coord` is *latitude*).
  If your nodes plot in the wrong hemisphere, you swapped them.
- **Mixed units.** Pick meters or feet for `length` and stick with it; declare
  in `datapackage.json` if your schema supports it.
- **Stranded nodes** are warnings, not errors — but they often mean you
  forgot a link.
- **Duplicate link_id when extending** — append, don't overwrite, and keep a
  max id counter.

## See also

- `gmns-validate` — interpreting the report after you save changes
- `gmns-convert` — once authored, convert to parquet for sharing
- `docs/gmns-data-model.md` — full table inventory and field reference
- GMNS spec: <https://github.com/zephyr-data-specs/GMNS>
- Reference fixture: `packages/gmnspy/gmnspy/fixtures/leavenworth/csv/`
