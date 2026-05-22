"""Notebook helpers for datagrove.

Hosts the shared HTML-card helpers used by the ``_repr_html_`` methods
that live directly on the public classes (:class:`~datagrove.dataset.Package`,
:class:`~datagrove.dataset.Table`,
:class:`~datagrove.reports.ValidationReport`,
:class:`~datagrove.editing.EditResult`). The methods live on the
classes themselves — Jupyter / VS Code call ``obj._repr_html_()``
without any opt-in import — but every implementation funnels through
:func:`card` here so the look is consistent across the public surface.

Domain packages extend by composition: :mod:`gmnspy.notebook` re-exports
:func:`card` so :class:`gmnspy.Network` can layer GMNS-specific bits on
top of the same template.

The helpers are intentionally dependency-free (stdlib :mod:`html` plus
f-strings) so importing this module is cheap and bringing the notebook
extra is not required.
"""

from __future__ import annotations

import html
from collections.abc import Iterable

__all__ = ["card", "escape", "kv_line", "small_table", "truncation_note"]


# ---------------------------------------------------------------------------
# Style — kept inline so the card renders standalone in a Jupyter cell
# without external CSS.
# ---------------------------------------------------------------------------

_CARD_STYLE = (
    "border:1px solid #d0d7de;"
    "border-radius:6px;"
    "padding:10px 14px;"
    "margin:6px 0;"
    "font-family:system-ui,-apple-system,Segoe UI,sans-serif;"
    "font-size:13px;"
    "line-height:1.4;"
    "max-width:760px;"
    "color:#1f2328;"
    "background:#ffffff;"
)
_HEADER_STYLE = (
    "display:flex;"
    "justify-content:space-between;"
    "align-items:baseline;"
    "border-bottom:1px solid #eaeef2;"
    "padding-bottom:6px;"
    "margin-bottom:8px;"
    "gap:12px;"
)
_TITLE_STYLE = "font-weight:600;font-size:14px;"
_SUBTITLE_STYLE = "color:#656d76;font-size:12px;text-align:right;word-break:break-all;"
_TABLE_STYLE = "border-collapse:collapse;width:100%;margin-top:6px;font-size:12px;"
_TH_STYLE = "text-align:left;border-bottom:1px solid #eaeef2;padding:3px 8px 3px 0;font-weight:600;color:#656d76;"
_TD_STYLE = "padding:3px 8px 3px 0;border-bottom:1px solid #f6f8fa;vertical-align:top;"
_NOTE_STYLE = "color:#656d76;font-size:11px;margin-top:4px;font-style:italic;"


def escape(value: object) -> str:
    """HTML-escape a value, coercing to ``str`` first.

    ``None`` becomes an empty string so callers can drop optional values
    into f-strings without a guard.

    Examples:
        >>> escape("<script>")
        '&lt;script&gt;'
        >>> escape(None)
        ''
        >>> escape(42)
        '42'
    """
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def card(title: str, body_html: str, subtitle: str = "") -> str:
    """Wrap ``body_html`` in a standard datagrove card.

    ``title`` and ``subtitle`` are escaped here; ``body_html`` is
    inserted verbatim and is the caller's responsibility — every helper
    in this module returns escaped HTML.

    Examples:
        >>> "datagrove-card" in card("hello", "<p>x</p>")
        True
        >>> "&lt;script&gt;" in card("<script>", "")
        True
    """
    header = (
        f'<div style="{_HEADER_STYLE}">'
        f'<span style="{_TITLE_STYLE}">{escape(title)}</span>'
        f'<span style="{_SUBTITLE_STYLE}">{escape(subtitle)}</span>'
        f"</div>"
    )
    return f'<div class="datagrove-card" style="{_CARD_STYLE}">{header}{body_html}</div>'


def kv_line(items: Iterable[tuple[str, object]]) -> str:
    """Render a ``key: value`` row of pill-style spans.

    Skips items whose value is ``None`` or an empty string so callers
    can pass optional fields unconditionally. Both keys and values are
    HTML-escaped.

    Examples:
        >>> "engine" in kv_line([("engine", "pandas"), ("rows", 3)])
        True
        >>> kv_line([("hidden", None)])
        ''
    """
    parts: list[str] = []
    for key, value in items:
        if value is None or value == "":
            continue
        parts.append(
            f'<span style="margin-right:14px;">'
            f'<span style="color:#656d76;">{escape(key)}:</span> '
            f'<span style="font-weight:500;">{escape(value)}</span>'
            f"</span>"
        )
    if not parts:
        return ""
    return f'<div style="margin-bottom:4px;">{"".join(parts)}</div>'


def small_table(headers: list[str], rows: list[list[object]]) -> str:
    """Render a tiny HTML ``<table>`` with the standard card styling.

    Every cell is HTML-escaped. Empty ``rows`` returns the empty string
    so callers can short-circuit on "nothing to show".

    Examples:
        >>> "<table" in small_table(["a", "b"], [[1, 2]])
        True
        >>> small_table(["a"], [])
        ''
    """
    if not rows:
        return ""
    head = "".join(f'<th style="{_TH_STYLE}">{escape(h)}</th>' for h in headers)
    body_rows: list[str] = []
    for row in rows:
        cells = "".join(f'<td style="{_TD_STYLE}">{escape(c)}</td>' for c in row)
        body_rows.append(f"<tr>{cells}</tr>")
    return f'<table style="{_TABLE_STYLE}"><thead><tr>{head}</tr></thead><tbody>{"".join(body_rows)}</tbody></table>'


def truncation_note(remaining: int, noun: str = "rows") -> str:
    """Render a small italic "...+N more <noun>" note.

    Returns the empty string when ``remaining <= 0`` so callers can
    forward the raw count without a guard.

    Examples:
        >>> truncation_note(0)
        ''
        >>> "more rows" in truncation_note(5)
        True
        >>> "more issues" in truncation_note(40, "issues")
        True
    """
    if remaining <= 0:
        return ""
    return f'<div style="{_NOTE_STYLE}">…+{int(remaining)} more {escape(noun)}</div>'
