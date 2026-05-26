---
title: Self-host the HTTP server
audience: users
kind: howto
summary: Run the FastAPI server with bearer-token auth, configure packages, and stand it up behind a reverse proxy.
---

# Self-host the HTTP server

## When to use this

You want HTTP access to your GMNS networks — for dashboards, non-Python consumers, or a small team sharing a single curated set of packages. The server is read-only and stateless.

## Quick example

```yaml
# server.yaml
bind: 127.0.0.1
port: 8000
auth:
  mode: bearer
  token_hash: "$argon2id$v=19$..."   # generate via generate_dev_token
packages:
  - id: leavenworth
    source: packages/gmnspy/gmnspy/fixtures/leavenworth/csv
```

```shell-session
$ gmnspy server run --config server.yaml
INFO:     Uvicorn running on http://127.0.0.1:8000
```

## Step-by-step

### 1. Install the `[server]` extra

```shell-session
$ pip install 'gmnspy[server]'
```

Brings in FastAPI + uvicorn + the auth dependencies.

### 2. Generate a dev token

```shell-session
$ python -c "from datagrove.api import generate_dev_token; print(generate_dev_token())"
token:     7yK3-...-Q9p
token_hash: $argon2id$v=19$m=65536,t=3,p=4$...
```

Save the raw `token` somewhere safe (clients need it); paste `token_hash` into your config. The raw token is never stored on the server.

### 3. Write a config YAML

```yaml
# server.yaml
bind: 127.0.0.1      # 0.0.0.0 to accept off-host requests (see pitfalls)
port: 8000

auth:
  mode: bearer       # or "none" — see pitfalls
  token_hash: "$argon2id$v=19$..."

packages:
  - id: leavenworth
    source: packages/gmnspy/gmnspy/fixtures/leavenworth/csv
  - id: regional
    source: s3://my-bucket/regional/datapackage.json
    # optional: spec_version, engine, credentials cascade

logging:
  level: INFO
```

### 4. Run it + verify

```shell-session
$ gmnspy server run --config server.yaml
$ curl http://127.0.0.1:8000/health
{"status": "ok", "version": "1.0.0"}
```

### 5. Make authenticated requests

```shell-session
$ TOKEN="7yK3-...-Q9p"
$ curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/networks
[{"id": "leavenworth", "spec_version": "0.97", "link_count": 214, ...}]

$ curl -H "Authorization: Bearer $TOKEN" \
       http://127.0.0.1:8000/networks/leavenworth/quality
{"issues": [...], "spec_version": "0.97"}
```

### 6. Endpoint list

| Endpoint | Returns |
|---|---|
| `GET /health` | liveness probe (no auth) |
| `GET /packages` | configured packages |
| `GET /packages/{id}` | one package's metadata |
| `GET /packages/{id}/spec` | Frictionless spec JSON |
| `POST /packages/{id}/validate` | full validation report |
| `GET /networks` | GMNS networks only |
| `GET /networks/{id}` | GMNS metadata + counts |
| `POST /networks/{id}/quality` | runs the GMNS rule pack |

Interactive OpenAPI at `http://127.0.0.1:8000/docs`.

## Common variations

| You want... | Change |
|---|---|
| Off-host access | `bind: 0.0.0.0` *and keep auth on* |
| Behind nginx / Caddy | Bind to `127.0.0.1`; let the proxy terminate TLS + forward |
| Multiple tokens (per client) | List under `auth.token_hashes:` instead of `auth.token_hash:` |
| Disable auth (dev only) | `auth: { mode: none }` — refuses to start unless bound to localhost |
| Docker | Dockerfile is on the Phase 5 roadmap; for now `pip install` in your own image and copy the config |

## Pitfalls

* **`auth: none` + non-localhost bind is a security footgun.** The server logs a loud `SECURITY WARNING` at startup and refuses to start unless you also set `auth.allow_unauthenticated_remote: true` in the config — don't.
* **Bearer tokens are compared via constant-time HMAC** against the stored Argon2 hash. Don't compare raw tokens elsewhere in your stack.
* **Stateless server, lazy engine.** Each request loads the package fresh through the lazy ibis engine. Big networks may want a connection pool / cache layer in front; the server doesn't ship one.
* **No write endpoints.** The HTTP server is read-only by design. For editing, use the Python API + `Session`, or wait for the deferred write surface.

## See also

* [Wire the MCP server to Claude Code / Claude Desktop](serve-mcp.md) — same data, stdio transport.
* [MCP tools reference](../ai/mcp-tools.md) — what the MCP surface exposes.
* [API reference](../reference/api.md) — `datagrove.api.generate_dev_token`, server config schema.
