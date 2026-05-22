"""FastAPI primitives for self-hostable data-package HTTP services (task 4.10).

Three modules, one concern each:

* :mod:`datagrove.api.config` — :class:`ServerSettings` /
  :class:`AuthSettings` / :class:`PackageRef`, plus
  :func:`load_settings` (YAML / JSON) and :func:`generate_dev_token`.
* :mod:`datagrove.api.auth` — :func:`build_auth_dependency` returns
  the FastAPI dependency that enforces ``auth.kind`` (``"none"`` or
  ``"bearer"``) using :func:`hmac.compare_digest` against the token.
* :mod:`datagrove.api.app` — :func:`build_app` factory + the four
  generic endpoints (``/health``, ``/packages``, ``/packages/{id}``,
  ``/packages/{id}/spec``, ``/packages/{id}/validate``). Domain
  packages pass an ``extra_router_factory`` to bolt on their own
  routers (see :mod:`gmnspy.server`).

The whole layer ~400 LOC. Stretch endpoints (table download with
scope, HTML validation report, OAuth2) live in follow-up issues —
the v1 contract is small on purpose.
"""

from .app import PackageRegistry, build_app
from .auth import build_auth_dependency
from .config import AuthSettings, PackageRef, ServerSettings, generate_dev_token, load_settings

__all__ = [
    "AuthSettings",
    "PackageRef",
    "PackageRegistry",
    "ServerSettings",
    "build_app",
    "build_auth_dependency",
    "generate_dev_token",
    "load_settings",
]
