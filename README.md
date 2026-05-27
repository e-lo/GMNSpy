# GMNSpy monorepo

Two Python packages for the [General Modeling Network Specification (GMNS)](https://github.com/zephyr-data-specs/GMNS), developed under the [Zephyr Foundation](http://zephyrtransport.org).

| Package | What it is | PyPI | Docs |
|---|---|---|---|
| [`gmnspy`](packages/gmnspy/) | GMNS toolkit — load, validate, scope, edit GMNS networks | [`gmnspy`](https://pypi.org/project/gmnspy/) | [e-lo.github.io/GMNSpy/gmnspy/](https://e-lo.github.io/GMNSpy/gmnspy/) |
| [`datagrove`](packages/datagrove/) | Generic Frictionless Data Package engine that `gmnspy` builds on | [`datagrove`](https://pypi.org/project/datagrove/) | [e-lo.github.io/GMNSpy/datagrove/](https://e-lo.github.io/GMNSpy/datagrove/) |

Most users only install `gmnspy`. `datagrove` comes as a transitive dependency.

---

## 🧪 v1.0 beta is open

We're shipping the v1.0 rewrite as a public beta. **If you can spare half an hour to try it on a real network, your feedback shapes GA.**

```bash
uv add 'gmnspy[all]==1.0.0b1'        # or: pip install 'gmnspy[all]==1.0.0b1'
gmnspy doctor                        # confirm install
```

- 📖 [Beta program details — what's in scope, how to report](BETA.md)
- 🐛 [File a beta-feedback issue](https://github.com/e-lo/GMNSpy/issues/new?template=beta-feedback.md)
- 📝 [Migration from v0.3.x](packages/gmnspy/docs/migration/v0.3-to-v1.0.md)

---

## Quick start

```python
import gmnspy
from gmnspy.fixtures import leavenworth      # bundled example network

net = gmnspy.read(leavenworth.csv_dir())     # auto-detect format
report = gmnspy.validate(net)                # structural + schema + FK + sync
print(f"{net.links.count()} links, {len(report.issues)} validation issues")

report.to_html("report.html")                # interactive single-file HTML
```

More: the [5-minute quickstart](https://e-lo.github.io/GMNSpy/gmnspy/quickstart/).

## Why a monorepo

`gmnspy` builds on a generic Frictionless engine (`datagrove`) extracted up front. The intent: future spec toolkits (GTFSpy, etc.) reuse the engine instead of reimplementing it. Both packages release independently; CI tests them together.

```
GMNSpy/
├── packages/
│   ├── datagrove/   # generic engine — PyPI package
│   └── gmnspy/      # GMNS toolkit on top — PyPI package
├── skills/          # Claude Code Skills (installable via path/git URL)
├── docs/            # umbrella landing page only — real docs are per-package
└── .github/         # CI/CD, issue templates, release-drafter
```

## Development

Workspace managed via [`uv`](https://docs.astral.sh/uv/). One command installs both packages with all extras editable:

```bash
git clone https://github.com/e-lo/GMNSpy.git
cd GMNSpy
uv sync --all-packages --all-extras

uv run gmnspy --help              # CLI
uv run pytest packages            # tests
```

Full contributor workflow: [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache 2.0](LICENSE).

## Acknowledgements

- [`zephyr-data-specs/GMNS`](https://github.com/zephyr-data-specs/GMNS) — upstream spec.
- [Zephyr Foundation](http://zephyrtransport.org) — project home.
- See [CONTRIBUTORS.md](CONTRIBUTORS.md).
