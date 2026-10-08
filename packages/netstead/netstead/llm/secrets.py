"""Write-only API-key storage for LLM providers: environment variables, then the OS keyring.

From the Workbench's point of view keys are write-only. This module stores, resolves and
deletes them and reports *where* one was found. No API route, Action, history entry,
log line or SSE event ever carries a key value.

A key is bound to the endpoint it was entered for (:class:`KeySlot`). The provider's
official endpoint uses the plain provider slot (``"openai"``); a ``base_url`` override
gets its own slot named for its origin (``"openai@https://llm.example.org"``), with no
env fallback. Pointing a provider at a new URL therefore never sends an existing key there.

There is deliberately no plain-text fallback: on a machine without a usable keyring, keys
come from environment variables only, and the UI says which variable to set.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from corral.io.credentials import system_keyring

from .errors import MissingKey

__all__ = [
    "KEYRING_SERVICE",
    "KeySlot",
    "KeyringLike",
    "SecretStore",
    "SecretStoreError",
    "looks_like_secret",
    "origin_of",
    "redact",
]

#: Keyring service name for every netstead LLM key (one entry per :attr:`KeySlot.name`).
KEYRING_SERVICE = "netstead-llm"
Source = Literal["env", "keyring"]

#: Key-shaped text: Anthropic ``sk-ant-…``, OpenAI ``sk-…`` (case-insensitive), Google ``AIza…``
#: (exact-case only, so a path like ``/data/Aizawa_county...`` doesn't false-positive), 20+ chars
#: after the prefix. Matches even right after a ``_`` or ``-`` (e.g. an env-var-style
#: ``FOO_sk-...``); only an *alphanumeric* character immediately before the prefix rules a match
#: out, which is what keeps a path segment like ``task-abcdefgh...`` (prefix preceded by ``a``) from
#: matching.
_KEY_SHAPE = re.compile(r"(?<![A-Za-z0-9])(?:(?i:sk-ant-|sk-)|AIza)[A-Za-z0-9_-]{20,}")


class SecretStoreError(ValueError):
    """A key could not be stored or removed. The message is user-facing and secret-free."""


class KeyringLike(Protocol):
    """The three ``keyring`` functions the store uses (tests pass an in-memory fake)."""

    def get_password(self, service_name: str, username: str) -> str | None:
        """Return the stored secret, or ``None``."""
        ...

    def set_password(self, service_name: str, username: str, password: str) -> None:
        """Store ``password``."""
        ...

    def delete_password(self, service_name: str, username: str) -> None:
        """Delete the stored secret."""
        ...


#: Default port for a scheme, dropped from the rebuilt origin so ``https://h`` and
#: ``https://h:443`` bind the same key slot.
_DEFAULT_PORTS = {"https": 443, "http": 80}


def origin_of(url: str) -> str:
    """``scheme://host[:port]`` of ``url``: what a key slot is bound to.

    Rebuilt from the scheme, hostname and port only — never the raw ``netloc`` — so a
    ``user:pass@host`` component cannot ride along into the origin and, from there, into
    the keyring username, :class:`KeySlot` repr, ``MissingKey`` text or adapter error
    messages. Raises ``ValueError`` if ``url`` carries userinfo, or if its scheme or host
    is empty. An IPv6 literal keeps its brackets; the scheme's default port (``:443`` for
    ``https``, ``:80`` for ``http``) is dropped so two spellings of the same origin don't
    bind separate slots.
    """
    parts = urlsplit(url)
    if parts.username is not None or parts.password is not None:
        raise ValueError("base_url must not contain a username or password")
    scheme = parts.scheme.lower()
    host = parts.hostname  # already lowercased by urlsplit; brackets stripped for IPv6
    if not scheme or not host:
        raise ValueError("base_url must have a scheme and a host")
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    port = parts.port
    if port is not None and port != _DEFAULT_PORTS.get(scheme):
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


def redact(text: str, *secrets: str) -> str:
    """Replace each of ``secrets``, and anything key-shaped, in ``text`` with ``[redacted]``."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return _KEY_SHAPE.sub("[redacted]", text)


def looks_like_secret(value: Any) -> bool:
    """Whether ``value`` -- or any string nested in it, including dict keys -- looks like an API key."""
    if isinstance(value, str):
        return bool(_KEY_SHAPE.search(value))
    if isinstance(value, Mapping):
        return any(looks_like_secret(k) or looks_like_secret(v) for k, v in value.items())
    if isinstance(value, list | tuple | set | frozenset):
        return any(looks_like_secret(v) for v in value)
    return False


@dataclass(frozen=True)
class KeySlot:
    """Where a key lives: a provider plus, for a non-official endpoint, that endpoint's origin."""

    provider: str
    origin: str | None = None

    @property
    def name(self) -> str:
        """The keyring username: ``"openai"`` or ``"openai@https://host"``."""
        return self.provider if self.origin is None else f"{self.provider}@{self.origin}"


class SecretStore:
    """Resolve, store and delete LLM API keys. Only :meth:`get` ever returns a key."""

    def __init__(
        self,
        *,
        environ: Mapping[str, str],
        env_names: Mapping[str, Sequence[str]],
        keyring: KeyringLike | Literal["auto"] | None = "auto",
    ) -> None:
        """``keyring="auto"`` uses the OS keyring when one is usable; ``None`` disables it; tests pass a fake."""
        self._environ = environ
        self._env_names = {name: tuple(names) for name, names in env_names.items()}
        self._keyring_arg = keyring
        self._keyring: KeyringLike | None = None
        self._keyring_resolved = False

    def __repr__(self) -> str:
        """Backend only."""
        return f"SecretStore(keyring={self.keyring_available})"

    @property
    def keyring(self) -> KeyringLike | None:
        """The keyring in use (resolved once), or ``None``."""
        if not self._keyring_resolved:
            self._keyring = system_keyring() if isinstance(self._keyring_arg, str) else self._keyring_arg
            self._keyring_resolved = True
        return self._keyring

    @property
    def keyring_available(self) -> bool:
        """Whether keys can be stored in an OS keyring."""
        return self.keyring is not None

    def env_names(self, provider: str) -> tuple[str, ...]:
        """Env vars checked, in order, for ``provider``'s official-endpoint key."""
        return self._env_names.get(provider, ())

    def _keyring_lookup(self, slot: KeySlot) -> tuple[str | None, bool]:
        """``(key, read_failed)`` from the keyring for ``slot``.

        ``read_failed`` is true when the backend raised (locked, broken) rather than simply
        having no entry — :meth:`lookup` treats the two the same ("no key here", as in
        corral's cascade), but :meth:`get` reports a locked/broken keyring differently
        from "no key configured".
        """
        if (ring := self.keyring) is None:
            return None, False
        try:
            return ring.get_password(KEYRING_SERVICE, slot.name), False
        except Exception:  # boundary: a locked or broken backend; the caller decides how to report it
            return None, True

    def lookup(self, slot: KeySlot) -> tuple[str, Source] | None:
        """``(key, source)`` for ``slot``, or ``None``."""
        if slot.origin is None:
            for name in self.env_names(slot.provider):
                if value := self._environ.get(name, "").strip():
                    return value, "env"
        stored, _read_failed = self._keyring_lookup(slot)
        if stored:
            return stored, "keyring"
        return None

    def get(self, slot: KeySlot, label: str) -> str:
        """The key for ``slot``; raises :class:`~netstead.llm.errors.MissingKey` saying how to add one."""
        if slot.origin is None:
            for name in self.env_names(slot.provider):
                if value := self._environ.get(name, "").strip():
                    return value
        stored, read_failed = self._keyring_lookup(slot)
        if stored:
            return stored
        if read_failed:
            raise MissingKey(slot.provider, f"{label}: the OS keyring could not be read (locked?).")
        if slot.origin is not None:
            raise MissingKey(
                slot.provider,
                f"{label}: no API key is configured for {slot.origin}. Keys are bound to the endpoint they were "
                "entered for; add one for this endpoint in Settings → Language models (needs an OS keyring).",
            )
        raise MissingKey(slot.provider, f"{label}: no API key is configured. {self.how_to_add(slot.provider)}")

    def how_to_add(self, provider: str) -> str:
        """User-facing instructions for adding ``provider``'s key on this machine."""
        env = " or ".join(self.env_names(provider))
        if self.keyring_available:
            return (
                f"Add one in Settings → Language models, or set {env}."
                if env
                else "Add one in Settings → Language models."
            )
        return (
            f"This machine has no OS keyring, so set {env} in the environment that starts netstead, then restart it."
            if env
            else "This machine has no OS keyring, so keys can't be stored here."
        )

    def status(self, slot: KeySlot) -> dict[str, Any]:
        """``{"configured": bool, "source": "env" | "keyring" | None}``: never the key itself."""
        found = self.lookup(slot)
        return {"configured": found is not None, "source": found[1] if found else None}

    def set(self, slot: KeySlot, key: str) -> Source:
        """Store ``key`` for ``slot`` in the OS keyring and return ``"keyring"``."""
        key = key.strip()
        if not key or any(ch.isspace() for ch in key):
            raise SecretStoreError("an API key cannot be empty or contain spaces")
        ring = self.keyring
        if ring is None:
            raise SecretStoreError(self.how_to_add(slot.provider))
        error: SecretStoreError | None = None
        try:
            ring.set_password(KEYRING_SERVICE, slot.name, key)
        except Exception as exc:  # boundary: report the failure by type only; its text could echo the key
            error = SecretStoreError(f"the OS keyring refused the key ({type(exc).__name__})")
        # Raised outside the `except` block (and `exc` is dropped) so the error carries no
        # __context__ at all -- a traceback or log that ignores __suppress_context__ still
        # can't reach the original exception, whose text may itself contain the key.
        if error is not None:
            del key
            raise error
        return "keyring"

    def remove(self, slot: KeySlot) -> list[Source]:
        """Delete ``slot``'s key from the keyring; return where it was removed from (env vars are the user's)."""
        ring = self.keyring
        if ring is None:
            return []
        error: SecretStoreError | None = None
        try:
            if not ring.get_password(KEYRING_SERVICE, slot.name):
                return []
            ring.delete_password(KEYRING_SERVICE, slot.name)
        except Exception as exc:  # boundary: as in set()
            error = SecretStoreError(f"the OS keyring could not delete the key ({type(exc).__name__})")
        if error is not None:  # raised outside `except`, as in set(): no __context__
            raise error
        return ["keyring"]
