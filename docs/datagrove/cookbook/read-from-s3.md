---
title: Read from S3 with credentials
audience: users
kind: howto
summary: Load a GMNS data package from S3 (or any fsspec-backed cloud store) with the credential cascade — kwarg, env var, keyring, .netrc.
---

# Read from S3 with credentials

## When to use this

Your data lives on cloud storage and you want the same lazy-load surface you get from a local directory — predicate pushdown, column pruning, no full download. Credentials should come from whichever channel your environment already manages (CI secret, keyring, `~/.netrc`) without ever being baked into source.

## Quick example

```python
from gmnspy import Network

net = Network.from_source("s3://my-bucket/networks/leavenworth/")
print(f"{net.spec_version}: {net.links.count()} links")
# AWS creds discovered from the default chain — env, ~/.aws/credentials, IAM role.
```

If your bucket is public-readable, no credential resolution runs at all. If it's private and a credential is discoverable, the load is still lazy — `net.links` is an ibis expression, not a materialised frame.

## Step-by-step

### 1. Install

```shell-session
$ pip install 'gmnspy[server]'
```

The cloud filesystem drivers (`fsspec`, `s3fs`, `adlfs`, `gcsfs`) come along with the `[server]`, `[clean]`, and `[mcp]` extras. If you only installed the bare `gmnspy` and hit `ImportError: No module named 's3fs'`, that's the missing extra — re-install with one of those tags.

### 2. Provide credentials

Credentials cascade in a fixed order. The first one resolved wins:

1. **Explicit kwarg** — `Network.from_source(url, credential="…")`. Always wins. Use for one-off scripts and notebooks.
2. **Environment variable** — `DATAGROVE_CRED_<HOST>_TOKEN` where `<HOST>` is the URL host uppercased with dots and dashes flattened to underscores. For `s3://my-bucket/...` that's `DATAGROVE_CRED_MY_BUCKET_TOKEN`. Use for CI.
3. **System keyring** — service name `datagrove`, username matches host. Use for local dev so a token never lands in your shell history.
4. **`~/.netrc`** — falls back to the standard netrc machine entry. Use for legacy compatibility.

For AWS specifically, the default boto credential chain runs *inside* step 1 — IAM role, `~/.aws/credentials`, `AWS_*` env vars. You only need a `DATAGROVE_CRED_*` variable when the bucket needs a non-default credential (e.g. a different AWS account, a custom MinIO instance with HTTP Basic).

To store a credential in the keyring (one-off, on dev machines):

```python
import keyring
keyring.set_password("datagrove", "my-bucket", "AKIA…/secret-here")
```

The same call from `python -c` works for CI bootstrapping if you'd rather not put the secret in an env file.

### 3. Load the package

```python
from gmnspy import Network

# Discover via the cascade above:
net = Network.from_source("s3://my-bucket/networks/leavenworth/")

# Or pass an explicit credential (kwarg always wins):
net = Network.from_source(
    "s3://my-bucket/networks/leavenworth/",
    credential={"key": "AKIA…", "secret": "…"},
)
```

The result is the same `Network` you'd get from a local path. Every table (`net.links`, `net.nodes`, `net.lanes`, …) is an ibis expression backed by the cloud-aware filesystem.

### 4. Verify the load is lazy

```python
expr = net.links.expr  # underlying ibis Table
print(type(expr).__name__)  # 'Table'

# No bytes pulled yet. Push a filter down — only matching rows transit:
fast_links = net.links.filter(net.links.free_speed > 45.0).to_polars()
```

Filters and column projections push down to the parquet readers, so a 10 GB package over S3 can return a small filtered frame in a few seconds without downloading the whole file.

### 5. Cache for repeat reads

If the same script will hit the package many times — a notebook, a debugging loop, a CI matrix — convert it once and load locally:

```python
from gmnspy import Network

remote = Network.from_source("s3://my-bucket/networks/leavenworth/")
remote.write("/tmp/leavenworth.parquet")   # one-shot download

# Subsequent runs:
net = Network.from_source("/tmp/leavenworth.parquet")
```

Parquet is faster to re-read than CSV-over-S3 by an order of magnitude on cold cache. See [Convert formats](convert-formats.md) for the format trade-offs.

## Common variations

| Scheme | Install extra | Credential field | Notes |
|---|---|---|---|
| `s3://…` | `[server]` (s3fs) | AWS chain or `DATAGROVE_CRED_*_TOKEN` | Custom endpoints via `endpoint_url` kwarg. |
| `https://…` | `[server]` (httpx) | `Bearer <token>` or HTTP Basic `user:pass` | Bearer is detected when token has no `:`. |
| `az://container@account/…` | `[server]` (adlfs) | `DATAGROVE_CRED_<ACCOUNT>_TOKEN` | Account key, SAS token, or default Azure credential. |
| `gs://bucket/…` | `[server]` (gcsfs) | GCP application-default creds or service-account JSON path | Set `GOOGLE_APPLICATION_CREDENTIALS` for the file path. |
| `duckdb://https://…/file.duckdb` | bare `gmnspy` | HTTP creds as above | DuckDB native httpfs reader; one round-trip per table. |

## Pitfalls

* **Credential precedence is fixed and not configurable.** A kwarg always overrides env / keyring / netrc. If your CI keeps reading the wrong credential, check whether something upstream is passing `credential=` to `from_source`.
* **Regional endpoints matter.** For non-default AWS regions or S3-compatible stores (MinIO, R2, Wasabi), set `endpoint_url` via a kwarg or `AWS_ENDPOINT_URL` env var — the cascade doesn't auto-discover non-AWS endpoints.
* **Pre-signed URLs have TTLs.** If you pass an `https://…?X-Amz-Signature=…` URL, the credential is baked in and the URL expires. Re-issue for long-running jobs.
* **Listing a bucket isn't free.** `Package.from_source("s3://bucket/")` (no prefix) walks the bucket. Always include the package directory prefix.
* **Anonymous reads need an explicit signal.** For public buckets the AWS chain still attempts to sign requests if any credential is present in the environment. Pass `credential={"anon": True}` to force unsigned access.
* **Keyring on Linux needs a backend.** The Python `keyring` library on a headless Linux box falls through to `fail.Keyring` if no backend is installed. Install `keyrings.alt` for a file-backed store, or use the env-var path instead.

## See also

* [Architecture](../../shared/architecture.md) — package/network/engine layering and the `from_source` dispatcher.
* [Convert formats](convert-formats.md) — once loaded, write the package out as parquet or duckdb for faster repeat loads.
* [API reference](../reference/api.md) — `Network.from_source`, `Package.from_source`.
