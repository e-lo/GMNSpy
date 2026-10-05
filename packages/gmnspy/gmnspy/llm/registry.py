"""ProviderRegistry: adapters built from settings + stored keys, and what is usable right now.

The Workbench routes, the session's parser and the ``gmnspy llm`` CLI all go through this.
It hands out key *status* (configured / source), never key values. The only code that reads
a key is :meth:`ProviderRegistry.provider`, which hands it straight to an adapter.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal

from .catalog import Catalog, ProviderInfo, load_catalog
from .errors import LLMError
from .providers import ADAPTERS
from .secrets import KeyringLike, KeySlot, SecretStore, origin_of
from .types import LLMProvider

if TYPE_CHECKING:
    # gmnspy.config imports gmnspy.llm.secrets, so this module (reached from gmnspy.llm's own
    # __init__) cannot import gmnspy.config at module scope without a circular import; the
    # functions below that need it (is_local_url, load_settings, user_config_path) import it
    # locally instead, by which point gmnspy.config has always finished loading.
    from gmnspy.config import LLMSettings, Settings

__all__ = ["PROBE_TIMEOUT_S", "ProviderRegistry", "build_registry", "default_registry", "is_local_url"]

#: Status probes of a local server (Ollama) must not stall the UI.
PROBE_TIMEOUT_S = 1.5


def is_local_url(url: str) -> bool:
    """Whether ``url`` points at this machine (re-exported from :mod:`gmnspy.config`, the one implementation)."""
    from gmnspy.config import is_local_url as _is_local_url  # deferred: see the TYPE_CHECKING import note above

    return _is_local_url(url)


class ProviderRegistry:
    """Build provider adapters with their keys, and report status, models and connection tests."""

    def __init__(self, settings: LLMSettings, secrets: SecretStore, catalog: Catalog, *, transport: Any = None) -> None:
        """Bind endpoint settings, the key store, the catalog, and an optional ``httpx`` transport (tests)."""
        self.settings = settings
        self.secrets = secrets
        self.catalog = catalog
        self._transport = transport

    def names(self) -> list[str]:
        """Providers with both a catalog entry and an adapter, in catalog order."""
        return [name for name in self.catalog.names() if name in ADAPTERS]

    def base_url(self, name: str) -> str:
        """The effective endpoint for ``name``: the settings override, else the catalog's official URL."""
        override = getattr(self.settings, name).base_url
        return (override or self.catalog[name].base_url).rstrip("/")

    def slot(self, name: str) -> KeySlot:
        """The key slot for ``name``'s *effective* endpoint; a non-official origin gets its own slot."""
        here = origin_of(self.base_url(name))
        return KeySlot(name, None if here == origin_of(self.catalog[name].base_url) else here)

    def is_local(self, name: str) -> bool:
        """Whether ``name``'s effective endpoint is on this machine (nothing it is sent leaves it)."""
        return self.settings.is_local(name)

    def grounding_on(self, name: str) -> bool:
        """Whether network vocabulary (street names, route numbers) is sent to ``name``."""
        return self.settings.grounding_on(name)

    def project_context_on(self, name: str) -> bool:
        """Whether the project's ``AGENTS.md``/``CLAUDE.md`` is sent to ``name``."""
        return self.settings.project_context_on(name)

    def match_retry_on(self, name: str) -> bool:
        """Whether a miss re-prompts ``name`` with the closest real names (``auto``: local endpoints only)."""
        return self.settings.match_retry_on(name)

    def disclosure(self, name: str) -> list[str]:
        """What a selection sends to ``name``, in words, for the privacy note (follows the quality settings)."""
        quality = self.settings.quality
        items = ["your utterance", "the selection tool's schema (GMNS field names such as lanes)"]
        if quality.assistant_context:
            items.append("the GMNS assistant guide that ships with gmnspy")
        if self.grounding_on(name):
            items.append(f"up to {quality.grounding_max_names} street names and route numbers from the active network")
        if self.project_context_on(name):
            items.append(
                f"your project notes (AGENTS.md or CLAUDE.md, up to {quality.project_context_max_chars} characters)"
            )
        if quality.few_shot:
            items.append(f"up to {quality.few_shot_max} earlier selections from this session (utterance and result)")
        return items

    def provider(self, name: str, *, timeout_s: float | None = None) -> LLMProvider:
        """An adapter for ``name`` holding its key; raises :class:`~gmnspy.llm.errors.MissingKey` if there is none."""
        info = self.catalog[name]
        key = "" if info.kind == "local" else self.secrets.get(self.slot(name), info.label)
        return ADAPTERS[name](
            api_key=key,
            base_url=self.base_url(name),
            timeout_s=timeout_s or getattr(self.settings, name).timeout_s,
            transport=self._transport,
        )

    def status(self) -> list[dict[str, Any]]:
        """One row per provider: configured / source / usable / error / models. Never a key value."""
        return [self._status(name) for name in self.names()]

    def _status(self, name: str) -> dict[str, Any]:
        info = self.catalog[name]
        base = self.base_url(name)
        row: dict[str, Any] = {
            "provider": name,
            "label": info.label,
            "kind": info.kind,
            "base_url": base,
            "local": is_local_url(base),
            "default_model": info.default_model,
            "key_env": list(info.key_env),
            "sends": self.disclosure(name),
            "configured": False,
            "source": None,
            "usable": False,
            "error": None,
            "models": None,
        }
        if info.kind == "local":
            try:
                installed = self.provider(name, timeout_s=PROBE_TIMEOUT_S).list_models()
            except LLMError as exc:
                row["error"] = str(exc)
                return row
            row.update(configured=True, usable=bool(installed), models=len(installed))
            if not installed:
                row["error"] = f"{info.label} is running but has no models; run: ollama pull {info.default_model}"
            return row
        row.update(self.secrets.status(self.slot(name)))
        row["usable"] = row["configured"]
        return row

    def models(self, name: str) -> list[dict[str, Any]]:
        """Models to offer: the catalog for remote providers; the installed models for local ones."""
        info = self.catalog[name]
        if info.kind == "remote":
            return [m.to_dict() for m in info.models]
        installed = self.provider(name, timeout_s=PROBE_TIMEOUT_S).list_models()
        return [{**_describe(info, model_id), "installed": True} for model_id in installed]

    def test(self, name: str, model: str | None = None) -> dict[str, Any]:
        """An authenticated, token-free call (list models). Failures are reported in the result, not raised."""
        info = self.catalog[name]
        started = time.perf_counter()
        try:
            served = self.provider(name).list_models()
        except LLMError as exc:
            return {"provider": name, "ok": False, "error_type": type(exc).__name__, "message": str(exc)}
        result: dict[str, Any] = {
            "provider": name,
            "ok": True,
            "error_type": None,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "models_served": len(served),
            "catalog_missing": [m.id for m in info.models if m.id not in served] if info.kind == "remote" else [],
            "message": f"{info.label}: connected ({len(served)} models available).",
        }
        if model and model not in served:
            result.update(
                ok=False,
                error_type="ModelNotFound",
                message=f"{info.label}: connected, but model {model!r} is not available here.",
            )
        return result


def _describe(info: ProviderInfo, model_id: str) -> dict[str, Any]:
    known = info.model(model_id)
    return known.to_dict() if known else {"id": model_id, "label": model_id, "tier": None, "tools": None}


def build_registry(
    settings: Settings,
    *,
    environ: Mapping[str, str] | None = None,
    keyring: KeyringLike | Literal["auto"] | None = "auto",
    transport: Any = None,
) -> ProviderRegistry:
    """A registry for ``settings``: the catalog (plus user overlay) and key store live in the user config dir."""
    from gmnspy.config import user_config_path  # deferred: see the TYPE_CHECKING import note above

    env = os.environ if environ is None else environ
    user_dir = user_config_path(env).parent
    catalog = load_catalog(user_dir)
    secrets = SecretStore(
        environ=env,
        env_names={name: info.key_env for name, info in catalog.providers.items()},
        keyring=keyring,
    )
    return ProviderRegistry(settings.llm, secrets, catalog, transport=transport)


def default_registry() -> ProviderRegistry:
    """A registry from the current process's layered settings and environment."""
    from gmnspy.config import load_settings  # deferred: see the TYPE_CHECKING import note above

    return build_registry(load_settings().settings)
