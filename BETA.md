# GMNSpy v1.0 + datagrove v0.1 — beta program

Thanks for trying the v1.0 beta. This page tells you what the beta is, what to expect, and how to get the most useful feedback to us.

## What's in the beta

Two PyPI packages, released together:

| Package | First beta tag | What it is |
|---|---|---|
| **`datagrove`** | `datagrove-v0.1.0-beta.1` | Generic Frictionless Data Package engine — lazy ibis/DuckDB, validation, scope, edit/rollback. |
| **`gmnspy`** | `gmnspy-v1.0.0-beta.1` | GMNS-specific toolkit on top — quality rules, network-aware scope, clean/edit, HTTP server, MCP. |

Most users only install `gmnspy`. `datagrove` comes as a transitive dependency.

## Install the beta

=== "uv (recommended)"

    ```bash
    uv add 'gmnspy[all]==1.0.0b1'
    ```

=== "pip"

    ```bash
    pip install 'gmnspy[all]==1.0.0b1'
    ```

=== "pipx (CLI-only)"

    ```bash
    pipx install 'gmnspy[all]==1.0.0b1'
    ```

See the [install guide](https://e-lo.github.io/GMNSpy/gmnspy/#install) for extras + the `zsh` quoting note.

After install, confirm everything works:

```bash
gmnspy doctor
```

That should report all green. If anything fails, [file a beta-feedback issue](#how-to-report) with the doctor output.

## Try it on the bundled fixture

A tiny real network (Leavenworth, WA — ~600 m of OSM-derived streets) ships in the wheel so you can try things without finding data:

```bash
# Print the bundled-fixture path
LV=$(uv run python -c "from gmnspy.fixtures import leavenworth; print(leavenworth.csv_dir())")

# Walk the basic surface
uv run gmnspy info $LV
uv run gmnspy validate $LV --html /tmp/lv-report.html && open /tmp/lv-report.html
uv run gmnspy quality $LV
```

Or in Python:

```python
import gmnspy
from gmnspy.fixtures import leavenworth

net = gmnspy.read(leavenworth.csv_dir())            # gmnspy.Network
report = gmnspy.validate(net)                       # ValidationReport
print(f"{net.links.count()} links, {len(report.issues)} issues")
```

## What we want from beta users

In rough priority order:

1. **Wrong-answer bugs.** A command exits 0 but the result is wrong. These are the hardest to catch in CI and the most important to find before GA.
2. **"It crashed loading my data."** Pull / strip / synthesise the shape of your data, file with a reproduction. Even an env mismatch report is useful.
3. **"I expected X to do Y but it did Z."** Friction. Where our docs say one thing and the code does another. Where the error message doesn't tell you what to fix.
4. **First-touch experience.** Did you install it from cold, run the quickstart, and have everything work? Where did you stumble?
5. **Performance at your network's scale.** Run `gmnspy bench /path/to/your/network` and tell us the wall-time numbers.

Less critical:

6. Suggestions for v1.1+ features.
7. "Have you considered building X?" — yes; we have a roadmap. File anyway, but expect "after GA."

## What's IN scope for beta fixes

- Wrong-answer bugs (any severity).
- Crashes on real-world data shapes.
- Documented behavior that's actually missing or different.
- Missing error messages / unhelpful tracebacks.
- Docs gaps where a user genuinely couldn't proceed.

## What's OUT of scope for beta fixes (will land in v1.1 or later)

- New features (unless trivial).
- Performance refactors beyond fixing pathological regressions.
- API surface additions (we want the v1.0 surface to settle, not grow).
- Windows support (community-maintained only).

## How to report

[**Open a beta-feedback issue →**](https://github.com/e-lo/GMNSpy/issues/new?template=beta-feedback.md)

The template asks for:

1. What you tried to do (one sentence).
2. What happened.
3. The shortest reproduction we can run.
4. The output of `gmnspy doctor --json`.

You don't have to fill every section — anything beats a silent fail.

## What we don't promise during beta

- Turnaround SLAs. This is volunteer time.
- API stability across `beta.N` → `beta.N+1`. We'll try to avoid breaking changes but the surface may shift if early users find sharp edges.
- Patches against `beta.N` once `beta.N+1` is out. Upgrade.

## When does it ship?

We're targeting GA (`datagrove-v0.1.0` + `gmnspy-v1.0.0`) **after at least two `beta.N` cycles** with no new critical bugs reported in the most recent cycle. Realistic timeline: 4–8 weeks from `beta.1`, depending on what beta finds.

## Roadmap beyond v1.0

After GA we'll publish a `v1.1` roadmap. Likely candidates (not promised):

- More network-cleanup ops (`split_link_at_node`, `snap_to_reference`).
- Map-view embed in the HTML validation report.
- Polygon and CRS-aware scope operations.
- Programmatic `gmnspy.bench` API (currently CLI-only).
- More quality rules (community contributions welcome).

## Thank you

Beta-program participation is unpaid open-source work, and it makes the GA release massively better. If you find a real issue, you'll get credit in the v1.0.0 changelog acknowledgements.

— Elizabeth Sall + maintainers
