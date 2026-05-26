---
title: Customise the data-quality rule pack
audience: users
kind: howto
summary: Override thresholds, disable rules, promote severity, and register your own rule via entry point.
---

# Customise the data-quality rule pack

## When to use this

GMNS defaults are designed for typical mid-sized urban networks. Override them when:

* Your network's speed limits, lane counts, or geometry tolerances differ from the defaults (a 30 mph residential cap, or a CRS in degrees instead of meters).
* You want to silence a rule that's noise on your data.
* You want to plug in a project-specific quality rule.

## Quick example

Tighten the residential-speed threshold from the default 35 mph down to 30 mph. `RuleConfig.thresholds` merges into the rule's defaults — you only specify the keys you want to change:

```python
from gmnspy import Network
from gmnspy.fixtures import leavenworth
from datagrove.quality import run_quality, RuleConfig

net = Network.from_source(leavenworth.csv_dir())
report = run_quality(
    net,
    config={"quality.high_speed_residential": RuleConfig(thresholds={"speed_limit_mph": 30.0})},
)
print(f"{len(report.issues)} issues at the lower 30 mph threshold")
```

![Quality report card for the Leavenworth fixture](../../assets/screenshots/leavenworth-quality-report.png){ .screenshot }
*Quality report card. The custom 30 mph threshold surfaces a handful of extra residential-speed warnings that the default 35 mph threshold would have hidden.*

## Step-by-step

### 1. List the rules currently registered

Inspect the registered rule pack to see codes, defaults, and severities. The GMNS pack ships seven rules out of the box:

```python
from datagrove.quality import list_rules

for rule in list_rules():
    print(f"{rule.code:42} {rule.severity.value:8} {rule.description[:50]}")
```

| Code | Threshold key | Default | Severity |
|---|---|---|---|
| `quality.high_speed_residential` | `speed_limit_mph` | `35` | WARNING |
| `quality.duplicate_near_nodes` | `epsilon_units` | `1e-5` | WARNING |
| `quality.sharp_angle_bend` | `min_angle_deg` | `30` | INFO |
| `quality.lane_count_mismatch` | (no threshold) | — | WARNING |
| `quality.zero_length_link` | `min_length_units` | `0.0` | WARNING |
| `quality.disconnected_component` | `min_component_size` | `2` | INFO |
| `quality.orphan_node` | (no threshold) | — | INFO |

### 2. Override a threshold

`RuleConfig.thresholds` is merged into the rule's defaults — you only specify the keys you want to change. Override multiple rules in one call:

```python
report = run_quality(
    net,
    config={
        "quality.high_speed_residential": RuleConfig(thresholds={"speed_limit_mph": 25.0}),
        "quality.sharp_angle_bend": RuleConfig(thresholds={"min_angle_deg": 45.0}),
    },
)
```

### 3. Disable a rule entirely

A disabled rule produces no issues and isn't listed in the report:

```python
report = run_quality(
    net,
    config={"quality.orphan_node": RuleConfig(enabled=False)},
)
```

### 4. Promote (or demote) severity

A common case: your CI pipeline should fail on lane-count mismatches even though the rule ships as WARNING. Use `severity_override` to promote, then check `report.issues` and exit non-zero accordingly:

```python
from datagrove.reports import Severity

report = run_quality(
    net,
    config={"quality.lane_count_mismatch": RuleConfig(severity_override=Severity.ERROR)},
)
exit(1 if any(i.severity is Severity.ERROR for i in report.issues) else 0)
```

### 5. Write your own rule and register it

A rule is a class with five attributes plus a `run` generator. Yield one `Issue` per finding; let `config.severity_override` win if it's set so callers can promote / demote the rule:

```python
from datagrove.quality import Rule, register_rule
from datagrove.reports import Issue, Severity, Category

class NoTollLinksRule(Rule):
    code = "quality.no_toll_links"
    description = "Project networks should not contain toll links."
    severity = Severity.WARNING
    applies_to = ("link",)  # which tables the rule needs

    def run(self, net, config):
        links = net.tables["link"].to_pandas()
        for row in links[links["toll"] > 0].itertuples():
            yield Issue(
                code=self.code,
                severity=config.severity_override or self.severity,
                category=Category.DATA_QUALITY,
                message=f"link {row.link_id} has nonzero toll",
                table="link",
                row=row.Index,
                fix_hint="set toll=0 or remove from project scope",
            )

register_rule(NoTollLinksRule())
```

For auto-registration on import, declare the rule via the `datagrove.quality.rules` entry point in your package's `pyproject.toml`:

```toml
[project.entry-points."datagrove.quality.rules"]
no_toll_links = "myproject.rules:NoTollLinksRule"
```

## Common variations

???+ note "Default — override one threshold for one run"
    Most common pattern: tighten or loosen a single threshold without touching anything else.

    ```python
    report = run_quality(
        net,
        config={"quality.high_speed_residential": RuleConfig(thresholds={"speed_limit_mph": 30.0})},
    )
    ```

??? note "Silence a noisy rule entirely"
    Disable it via `RuleConfig(enabled=False)`; the rule contributes no issues and doesn't appear in the report.

    ```python
    report = run_quality(net, config={"quality.orphan_node": RuleConfig(enabled=False)})
    ```

??? note "Promote a WARNING to ERROR for CI"
    Use `severity_override`; then exit non-zero if any ERROR issue appears.

    ```python
    report = run_quality(
        net,
        config={"quality.lane_count_mismatch": RuleConfig(severity_override=Severity.ERROR)},
    )
    ```

??? note "Ship a custom rule with your package"
    Register via the `datagrove.quality.rules` entry point so it auto-loads on import.

    ```toml
    [project.entry-points."datagrove.quality.rules"]
    no_toll_links = "myproject.rules:NoTollLinksRule"
    ```

## Pitfalls

* **`epsilon_units` is CRS-sensitive.** The default `1e-5` is tight for WGS84 degrees (~1 metre near the equator). A network in projected meters needs something like `epsilon_units=0.5` for the same intent. Always set this explicitly for non-WGS84 networks.
* **`severity_override` doesn't mute — it replaces.** Setting `severity_override=Severity.INFO` on a WARNING rule still produces issues; if you want to drop them, use `enabled=False`.
* **Custom rules need `applies_to`.** A rule that touches the `signal` table without listing it in `applies_to` won't be invoked on networks that lack the table — the runner skips it silently.

## See also

* [Quickstart](../quickstart.md#4-run-data-quality-checks) — the default quality flow.
* [API reference](../reference/api.md) — `run_quality`, `RuleConfig`, `Rule`, `Issue`.
