"""GMNS spec loader — vendored multi-version support.

Three GMNS spec releases ship side-by-side under
``packages/gmnspy/gmnspy/spec/<version>/``: ``0.95``, ``0.96``, and
``0.97`` (the current default). Each version directory holds the
top-level package descriptor plus one ``<resource>.schema.json`` file
per table. ``0.97`` additionally ships ``shared_categories.json``
defining reusable enums that field constraints reference via
``$ref``; the underlying :func:`datagrove.spec.load_package` resolves
those refs and inlines the enum values onto each field.

Two descriptor filenames are in play: ``datapackage.json`` (0.96+)
and ``gmns.spec.json`` (0.95 only — the same Frictionless shape under
a different filename). :func:`load_gmns_spec` picks the right one
per version, so callers stay version-agnostic.

Public API:
    * :data:`SUPPORTED_SPECS` — tuple of supported version strings.
    * :data:`DEFAULT_SPEC` — version returned when callers omit one.
    * :func:`get_spec_path` — directory containing the vendored files
      for a given version.
    * :func:`load_gmns_spec` — parsed :class:`DataPackage` for a given
      version, with resource schemas resolved and shared-category
      enums inlined.

See ``docs/architecture.md`` section 7 ("Spec sync strategy") for the
vendoring policy and release cadence.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from datagrove.spec import DataPackage, load_package

__all__ = [
    "DEFAULT_SPEC",
    "SUPPORTED_SPECS",
    "get_spec_path",
    "load_gmns_spec",
]

SUPPORTED_SPECS: tuple[str, ...] = ("0.95", "0.96", "0.97")
"""GMNS spec versions vendored in this wheel, oldest to newest."""

DEFAULT_SPEC: str = "0.97"
"""Default GMNS spec version used when callers do not specify one."""

# Per-version filename of the top-level Frictionless data-package
# descriptor. 0.95 predates the ``datapackage.json`` convention and
# ships the same shape under the older ``gmns.spec.json`` name; 0.96+
# adopted the standard filename. The dict drives :func:`load_gmns_spec`
# so per-version branching stays in one place.
_DESCRIPTOR_FILENAME: dict[str, str] = {
    "0.95": "gmns.spec.json",
    "0.96": "datapackage.json",
    "0.97": "datapackage.json",
}


def _check_version(version: str) -> None:
    """Raise :class:`ValueError` when ``version`` is not vendored."""
    if version not in SUPPORTED_SPECS:
        raise ValueError(
            f"Unsupported GMNS spec version: {version!r}. Supported versions: {', '.join(SUPPORTED_SPECS)}"
        )


def get_spec_path(version: str = DEFAULT_SPEC) -> Path:
    """Return the on-disk directory holding the vendored spec.

    Resolves the version directory through :mod:`importlib.resources`
    so the lookup works identically whether ``gmnspy`` was imported
    from a source checkout or installed from a wheel.

    Args:
        version: One of :data:`SUPPORTED_SPECS` (default
            :data:`DEFAULT_SPEC`).

    Returns:
        Filesystem path to ``packages/gmnspy/gmnspy/spec/<version>/``
        — the directory that contains the descriptor JSON plus one
        ``.schema.json`` file per resource.

    Raises:
        ValueError: If ``version`` is not in :data:`SUPPORTED_SPECS`.

    Examples:
        >>> from gmnspy.spec import get_spec_path
        >>> p = get_spec_path()
        >>> p.is_dir()
        True
        >>> p.name
        '0.97'
        >>> (p / "link.schema.json").is_file()
        True
    """
    _check_version(version)
    # ``files()`` on a package returns a Traversable rooted at that
    # package's directory; joining the version segment gives the
    # vendored data directory. ``as_file`` would copy to a temp dir
    # for zip-installed packages, but pip/uv install gmnspy as a
    # regular tree so the underlying path is real — wrap in
    # ``Path(str(...))`` for a plain filesystem path.
    root = resources.files(__package__)
    return Path(str(root / version))


def load_gmns_spec(version: str = DEFAULT_SPEC) -> DataPackage:
    """Load the vendored GMNS data package for one spec version.

    Delegates parsing to :func:`datagrove.spec.load_package`, which
    resolves each resource's ``schema`` reference, follows ``$ref``
    pointers (including into ``shared_categories.json`` when present
    — that file ships only in 0.97), and inlines the resolved enum
    values onto each field's ``constraints.enum``.

    Args:
        version: One of :data:`SUPPORTED_SPECS` (default
            :data:`DEFAULT_SPEC`).

    Returns:
        Parsed :class:`~datagrove.spec.DataPackage` with every
        resource's ``table_schema`` populated.

    Raises:
        ValueError: If ``version`` is not in :data:`SUPPORTED_SPECS`.
        SpecLoadError: If the vendored descriptor is missing or
            malformed. This should not happen in a released wheel;
            it indicates the package data was corrupted at build
            time.

    Examples:
        >>> from gmnspy.spec import load_gmns_spec
        >>> pkg = load_gmns_spec()
        >>> pkg.name
        'gmns'
        >>> {r.name for r in pkg.resources} >= {"link", "node"}
        True
    """
    _check_version(version)
    descriptor = get_spec_path(version) / _DESCRIPTOR_FILENAME[version]
    return load_package(descriptor)
