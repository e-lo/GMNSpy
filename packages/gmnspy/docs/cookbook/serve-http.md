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

Write a minimal config that binds localhost on port 8000, requires a bearer token, and exposes one package. Start it with `gmnspy server run`:

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

```bash
gmnspy server run --config server.yaml
```

Expected:

```text
INFO:     Uvicorn running on http://127.0.0.1:8000
```

![Interactive OpenAPI docs for the gmnspy HTTP server](../assets/screenshots/serve-http-openapi.png){ .screenshot }
*Interactive OpenAPI at `/docs` — every endpoint with try-it-out forms and the JSON response schema.*

## Step-by-step

### 1. Install the `[server]` extra

Brings in FastAPI + uvicorn + the auth dependencies:

```bash
pip install 'gmnspy[server]'
```

### 2. Generate a dev token

The dev-token helper prints both the raw token (which clients use) and the Argon2 hash (which the server stores). The raw token is never persisted server-side:

```bash
python -c "from datagrove.api import generate_dev_token; print(generate_dev_token())"
```

Expected:

```text
token:     7yK3-...-Q9p
token_hash: $argon2id$v=19$m=65536,t=3,p=4$...
```

Save the raw `token` somewhere safe; paste `token_hash` into your config.

### 3. Write a config YAML

A config declares network bind, auth mode, and one entry per exposed package. Sources accept any path or URL that `Network.from_source` accepts:

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

Start the server, then hit `/health` (the unauthenticated liveness probe) to confirm it's up:

```bash
gmnspy server run --config server.yaml
```

```bash
curl http://127.0.0.1:8000/health
```

Expected:

```json
{"status": "ok", "version": "1.0.0"}
```

### 5. Make authenticated requests

Pass the raw token from step 2 as a bearer header. The server returns JSON by default and HTML when the request sets `Accept: text/html`:

```bash
TOKEN="7yK3-...-Q9p"
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/networks
```

Expected:

```json
[{"id": "leavenworth", "spec_version": "0.97", "link_count": 214, ...}]
```

Run quality checks with a POST:

```bash
curl -H "Authorization: Bearer $TOKEN" \
     http://127.0.0.1:8000/networks/leavenworth/quality
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

???+ note "Default — localhost bind with bearer auth"
    Safe default for dev and single-host production behind a reverse proxy.

    ```yaml
    bind: 127.0.0.1
    auth: { mode: bearer, token_hash: "$argon2id$..." }
    ```

??? note "Off-host access (LAN, etc.)"
    Bind `0.0.0.0` — but keep auth on.

    ```yaml
    bind: 0.0.0.0
    auth: { mode: bearer, token_hash: "$argon2id$..." }
    ```

??? note "Behind nginx / Caddy"
    Bind to `127.0.0.1`; let the proxy terminate TLS and forward. No server-side TLS config needed.

    ```yaml
    bind: 127.0.0.1
    port: 8000
    ```

??? note "Multiple tokens (one per client)"
    Use the plural `token_hashes:` form; clients still pass a single bearer header.

    ```yaml
    auth:
      mode: bearer
      token_hashes:
        - "$argon2id$...client-a..."
        - "$argon2id$...client-b..."
    ```

??? note "Disable auth (dev only)"
    Server refuses to start unless bound to localhost.

    ```yaml
    bind: 127.0.0.1
    auth: { mode: none }
    ```

??? note "Docker"
    Dockerfile is on the Phase 5 roadmap; for now `pip install` in your own image and copy the config alongside.

    ```dockerfile
    FROM python:3.12-slim
    RUN pip install 'gmnspy[server]'
    COPY server.yaml /etc/gmnspy/server.yaml
    CMD ["gmnspy", "server", "run", "--config", "/etc/gmnspy/server.yaml"]
    ```

## Pitfalls

* **`auth: none` + non-localhost bind is a security footgun.** The server logs a loud `SECURITY WARNING` at startup and refuses to start unless you also set `auth.allow_unauthenticated_remote: true` in the config — don't.
* **Bearer tokens are compared via constant-time HMAC** against the stored Argon2 hash. Don't compare raw tokens elsewhere in your stack.
* **Stateless server, lazy engine.** Each request loads the package fresh through the lazy ibis engine. Big networks may want a connection pool / cache layer in front; the server doesn't ship one.
* **No write endpoints.** The HTTP server is read-only by design. For editing, use the Python API + `Session`, or wait for the deferred write surface.

## See also

* [Wire the MCP server to Claude Code / Claude Desktop](serve-mcp.md) — same data, stdio transport.
* [MCP tools reference](../ai/mcp-tools.md) — what the MCP surface exposes.
* [API reference](../reference/api.md) — `datagrove.api.generate_dev_token`, server config schema.
