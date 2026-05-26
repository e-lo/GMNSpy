"""Credentials cascade resolver for remote (URL) sources.

Resolves an fsspec-shaped ``storage_options`` dict for a given host by
walking a fixed cascade:

    1. ``explicit`` kwarg (caller's dict)         -- highest precedence
    2. ``DATAGROVE_CRED_<HOST_UPPER>_TOKEN`` env var
       (or ``_KEY`` + ``_SECRET`` for S3-style creds)
    3. ``keyring.get_password("datagrove", host)`` (optional dep)
    4. ``netrc`` lookup (stdlib)
    5. ``{}``                                     -- lowest precedence

The resolver **never raises on missing credentials** -- the underlying
storage backend will raise its own auth error when the request actually
fails. That keeps "no credentials available" silent and "wrong
credentials" loud, which is what users want.

**Security:**

- Credential *values* are never logged. Only host names are logged at
  debug level, and only when explicitly enabled. See ``test_no_creds_logged``.
- ``explicit`` is shallow-copied before return to avoid the caller
  later mutating what they handed us (which would mutate our return).
"""

from __future__ import annotations

import logging
import netrc
import os
from typing import Final

__all__ = ["resolve_credentials"]

_logger: Final = logging.getLogger(__name__)

# Service name used as the keyring "service" key. Single namespace for the
# whole project so users don't have to deal with per-format keys.
_KEYRING_SERVICE: Final = "datagrove"


def resolve_credentials(host: str, *, explicit: dict | None = None) -> dict:
    """Resolve fsspec ``storage_options`` for ``host`` via the cascade.

    Args:
        host: Network host (e.g. ``"s3.amazonaws.com"``,
            ``"example.com:8080"``). Port suffixes are stripped.
        explicit: Caller-provided storage_options. Takes precedence over
            every other layer. ``None`` (default) means consult the
            cascade.

    Returns:
        A dict suitable for ``fsspec.open(..., **storage_options)``.
        Typical shapes:

        - Bearer token: ``{"token": "..."}`` (env ``_TOKEN``, keyring)
        - S3-style:     ``{"key": "...", "secret": "..."}`` (env
          ``_KEY`` + ``_SECRET``)
        - HTTP basic:   ``{"username": "...", "password": "..."}`` (netrc)
        - Empty:        ``{}`` when no layer produced anything --
          the underlying backend will surface its own auth error.

    Examples:
        Explicit creds beat the env var:

        >>> import os
        >>> os.environ["DATAGROVE_CRED_DOCTEST_HOST_TOKEN"] = "from-env"
        >>> resolve_credentials(
        ...     "doctest.host", explicit={"token": "from-arg"}
        ... )
        {'token': 'from-arg'}
        >>> del os.environ["DATAGROVE_CRED_DOCTEST_HOST_TOKEN"]

        A host with no credentials anywhere returns an empty dict --
        not an exception:

        >>> resolve_credentials("no.such.host.example") == {}
        True
    """
    # Layer 1: explicit kwarg wins.
    if explicit is not None:
        # Shallow copy so caller mutations don't bleed into our return.
        return dict(explicit)

    sanitized = _sanitize_host(host)

    # Layer 2: env vars.
    creds = _lookup_env(sanitized)
    if creds:
        return creds

    # Layer 3: keyring (optional).
    creds = _lookup_keyring(host)
    if creds:
        return creds

    # Layer 4: netrc.
    creds = _lookup_netrc(host)
    if creds:
        return creds

    # Layer 5: nothing.
    return {}


# ---------------------------------------------------------------------------
# Layer helpers (module-level so tests can monkeypatch them individually).
# ---------------------------------------------------------------------------


def _sanitize_host(host: str) -> str:
    """Normalize ``host`` into the env-var-fragment form.

    Drops any port suffix (``:9000``), lowercases, then replaces ``.``
    and ``-`` with ``_``. The result is upper-cased by callers when used
    in env var lookups.
    """
    # Strip user/auth that some URLs carry; we only care about the host:port tail.
    bare = host.split("@")[-1]
    # Drop port.
    bare = bare.split(":")[0]
    bare = bare.strip().lower()
    return bare.replace(".", "_").replace("-", "_")


def _lookup_env(sanitized_host: str) -> dict:
    """Read ``DATAGROVE_CRED_<HOST>_TOKEN`` (or ``_KEY`` + ``_SECRET``).

    Returns ``{}`` if no relevant env var is set or all are empty.
    Empty-string env values are treated as "missing", not "empty
    credential" -- handing fsspec ``token=""`` would silently produce
    a confusing auth error.
    """
    prefix = f"DATAGROVE_CRED_{sanitized_host.upper()}"

    token = os.environ.get(f"{prefix}_TOKEN", "")
    if token:
        return {"token": token}

    key = os.environ.get(f"{prefix}_KEY", "")
    secret = os.environ.get(f"{prefix}_SECRET", "")
    if key and secret:
        return {"key": key, "secret": secret}

    return {}


def _lookup_keyring(host: str) -> dict:
    """Look up a bearer token in the system keyring.

    Optional dependency: ``[keyring]`` extra. When the ``keyring``
    package is missing (or has been disabled with
    ``sys.modules['keyring'] = None``), this returns ``{}`` silently.

    Headless environments (CI, containers, WSL without an unlocked
    secret service) have ``keyring`` installed but no usable backend.
    The library raises ``NoKeyringError`` from a fail-backend; treat
    that as "no credentials" rather than letting it propagate — the
    cascade contract is "never raise on missing".
    """
    try:
        import keyring  # type: ignore[import-not-found]
    except ImportError:
        return {}
    # ``sys.modules['keyring'] = None`` (used by tests to simulate "not
    # installed") makes the import succeed but the binding is None.
    if keyring is None:  # type: ignore[unreachable]
        return {}

    try:
        value = keyring.get_password(_KEYRING_SERVICE, host)
    except keyring.errors.KeyringError:
        return {}
    if value:
        return {"token": value}
    return {}


def _lookup_netrc(host: str) -> dict:
    """Read ``~/.netrc`` (or ``$NETRC``) for ``host``.

    The stdlib parser raises if the file does not exist or has no entry
    for the host; we coerce those to "no credentials" rather than
    propagating, because the cascade's contract is "never raise on
    missing".
    """
    netrc_path = os.environ.get("NETRC")
    try:
        rc = netrc.netrc(netrc_path) if netrc_path else netrc.netrc()
    except (FileNotFoundError, netrc.NetrcParseError, OSError):
        return {}

    auth = rc.authenticators(host)
    if not auth:
        return {}

    login, _account, password = auth
    out: dict = {}
    if login:
        out["username"] = login
    if password:
        out["password"] = password
    return out
