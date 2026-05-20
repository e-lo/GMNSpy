"""Notebook-aware progress bar + spinner over :mod:`rich.progress`.

Thin wrappers used by long-running validation/scope/edit ops. The
:func:`progress` helper wraps any iterable; :class:`Spinner` covers
indeterminate ops. Both auto-disable under pytest (so test logs stay
clean) and render inline when invoked from a Jupyter kernel.

Design notes:
    * No cost-model integration here — the CLI (Phase 4) wires the
      cost-model gate from task 3.1 to ``disable=`` on these helpers.
    * No raw SQL, no pandas, no engine deps — pure UX helper.
    * Notebook detection is intentionally a one-liner heuristic; the
      ipywidget path is deferred to Phase 4 notebook polish.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from typing import Any, TypeVar

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

__all__ = ["Spinner", "is_notebook", "progress"]

T = TypeVar("T")


def _get_ipython() -> Any:
    """Return the active IPython shell, or None.

    Wrapped so tests can monkey-patch this single attribute instead of
    poking at the (sometimes absent) IPython module.
    """
    try:
        from IPython import get_ipython  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        return get_ipython()
    except Exception:
        return None


def is_notebook() -> bool:
    """Return True when running inside a Jupyter / IPython kernel.

    Uses the ``get_ipython().has_trait("kernel")`` heuristic. Plain
    Python REPLs, scripts, and pytest all return False.

    Examples:
        >>> from datagrove.operations import is_notebook
        >>> isinstance(is_notebook(), bool)
        True
    """
    shell = _get_ipython()
    if shell is None:
        return False
    try:
        return bool(shell.has_trait("kernel"))
    except Exception:
        return False


def _auto_disable() -> bool:
    """Auto-disable progress under pytest to keep test output pristine."""
    return "PYTEST_CURRENT_TEST" in os.environ


def _make_console() -> Console:
    """Console tuned for notebook vs terminal output."""
    if is_notebook():
        # force_terminal=False keeps ANSI escapes out of the notebook HTML.
        return Console(force_terminal=False, force_jupyter=True)
    return Console()


def progress(
    iterable: Iterable[T],
    *,
    total: int | None = None,
    description: str = "",
    disable: bool = False,
) -> Iterator[T]:
    """Wrap ``iterable`` with a notebook-aware rich progress bar.

    Args:
        iterable: Any iterable. ``total`` is required for generators
            (anything without ``__len__``).
        total: Explicit length when not derivable.
        description: Prefix shown next to the bar.
        disable: Skip the bar entirely. Auto-True under pytest and when
            callers (e.g. CLI ``--json``) want silent output.

    Yields:
        Items from ``iterable`` unchanged.

    Examples:
        >>> from datagrove.operations import progress
        >>> list(progress([1, 2, 3], disable=True))
        [1, 2, 3]
    """
    if disable or _auto_disable():
        yield from iterable
        return

    if total is None:
        try:
            total = len(iterable)  # type: ignore[arg-type]
        except TypeError:
            total = None

    columns = [
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
    ]
    with Progress(*columns, console=_make_console(), transient=False) as bar:
        task_id = bar.add_task(description or "working", total=total)
        for item in iterable:
            yield item
            bar.advance(task_id)


class Spinner:
    """Context-manager spinner for ops of unknown duration.

    Args:
        description: Label shown next to the spinner.
        disable: Skip the spinner entirely. Auto-True under pytest.

    Examples:
        >>> from datagrove.operations import Spinner
        >>> with Spinner("noop", disable=True):
        ...     pass
    """

    def __init__(self, description: str, *, disable: bool = False) -> None:
        """Store config; spinner starts in :meth:`__enter__`."""
        self.description = description
        self.disable = disable or _auto_disable()
        self._progress: Progress | None = None
        self._task_id: int | None = None

    def __enter__(self) -> Spinner:
        """Start the underlying rich.Progress (no-op when disabled)."""
        if self.disable:
            return self
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=_make_console(),
            transient=True,
        )
        self._progress.__enter__()
        self._task_id = self._progress.add_task(self.description, total=None)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        """Tear down the spinner; never swallow caller exceptions."""
        if self._progress is not None:
            self._progress.__exit__(exc_type, exc_val, exc_tb)
            self._progress = None
            self._task_id = None
        # Never swallow caller exceptions.
        return False
