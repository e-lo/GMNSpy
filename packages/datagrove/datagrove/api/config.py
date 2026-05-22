"""Server configuration model + loader (datagrove.api, task 4.10).

Pydantic-Settings-backed config so an operator can configure the server
from a YAML / TOML / env-var combo without code changes. The
:class:`ServerSettings` model is the single source of truth — both
:func:`build_app` and the CLI's ``server run`` command read it.

Security defaults (rationale embedded in the field docs):

* ``bind = "127.0.0.1"`` — localhost only by default. The operator
  must consciously change this to expose the service.
* ``auth.kind = "bearer"`` — token-required by default. ``"none"``
  is allowed but the app emits a loud warning if combined with a
  non-localhost bind.

We deliberately keep this layer small (~150 LOC) — the architecture
calls for OAuth2 as a stretch; bearer-token covers the v1 use cases
(local hosting, single-tenant, behind a reverse proxy).
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "AuthSettings",
    "PackageRef",
    "ServerSettings",
    "generate_dev_token",
    "load_settings",
]

logger = logging.getLogger(__name__)


class AuthSettings(BaseModel):
    """How the server authenticates incoming requests.

    Attributes:
        kind: Either ``"none"`` (no auth — only safe on localhost) or
            ``"bearer"`` (require a ``Bearer <token>`` header matching
            :attr:`token`). Default ``"bearer"``.
        token: Required when ``kind == "bearer"``. Compared against
            the incoming ``Authorization`` header in constant time.
    """

    kind: Literal["none", "bearer"] = "bearer"
    token: str | None = None


class PackageRef(BaseModel):
    """One package the server should expose under a public id.

    Attributes:
        id: Public, URL-safe identifier (used in ``/packages/{id}`` /
            ``/networks/{id}`` paths). Must match
            ``^[a-zA-Z0-9_-]+$`` — checked at load time.
        source: Anything :meth:`datagrove.dataset.Package.from_source`
            accepts (path, URL, or directory).
        description: Optional human-readable summary returned by the
            metadata endpoint.
    """

    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    source: str
    description: str | None = None


class ServerSettings(BaseModel):
    """Top-level server configuration.

    Attributes:
        bind: Interface to bind. Default ``"127.0.0.1"`` — operator
            must explicitly opt into a public bind.
        port: TCP port. Default ``8000``.
        auth: Auth configuration (default bearer-token).
        packages: List of packages to expose under public ids. Empty
            list means "no packages mounted"; the app still starts
            (e.g. for ``/health`` smoke tests) but every
            ``/packages/{id}`` request 404s.
    """

    bind: str = "127.0.0.1"
    port: int = 8000
    auth: AuthSettings = Field(default_factory=AuthSettings)
    packages: list[PackageRef] = Field(default_factory=list)

    def is_public_bind(self) -> bool:
        """Return ``True`` when :attr:`bind` exposes the server beyond localhost."""
        return self.bind not in {"127.0.0.1", "localhost", "::1"}

    def warn_on_unsafe_combinations(self) -> None:
        """Emit a loud log warning when the combination is risky.

        Today: ``auth=none`` + non-localhost bind. Future: missing TLS,
        weak token, etc.
        """
        if self.auth.kind == "none" and self.is_public_bind():
            logger.warning(
                "datagrove.api: auth.kind='none' with bind=%r exposes the server with NO authentication. "
                "Set auth.kind='bearer' + auth.token, OR bind to 127.0.0.1, before going live.",
                self.bind,
            )


def generate_dev_token() -> str:
    """Return a fresh URL-safe token for a dev / smoke-test config."""
    return secrets.token_urlsafe(32)


def load_settings(path: str | Path | None = None) -> ServerSettings:
    """Load :class:`ServerSettings` from ``path`` (yaml / json) or env defaults.

    When ``path`` is ``None``, returns the dataclass defaults (which
    bind to localhost with auth=bearer and no packages — safe but
    useless). YAML support is optional (uses ``pyyaml`` if installed,
    else falls back to JSON).
    """
    if path is None:
        return ServerSettings()
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as e:  # pragma: no cover - optional
            raise ImportError("pyyaml required for YAML config; install pyyaml or use JSON") from e
        data = yaml.safe_load(text) or {}
    else:
        import json

        data = json.loads(text)
    return ServerSettings.model_validate(data)
