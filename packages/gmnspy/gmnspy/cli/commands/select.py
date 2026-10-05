"""``gmnspy select`` — natural-language selection of GMNS elements.

Parses an utterance into a structured intent, resolves it against a network,
and emits a validated GMNS selection fragment (or the ambiguity/not-found
diagnostics). Selection only — no edit is applied.
"""

from __future__ import annotations

import json
from typing import Any

import typer
from datagrove.cli.render import render_dict

from gmnspy import Network

from ...config import SettingsError, load_settings
from ...llm import LLMError, build_registry
from ...select.emit import to_fragment
from ...select.parse import make_parser
from ...select.resolve import resolve
from .._helpers import resolve_engine

__all__ = ["register"]


def _make_parser(provider: str | None, model: str | None) -> Any:
    """The parser for ``--provider``/``--model`` over the layered settings (exit 2: bad settings; 1: no key)."""
    overrides = {k: v for k, v in {"select.provider": provider, "select.model": model}.items() if v is not None}
    try:
        settings = load_settings(overrides=overrides).settings
        return make_parser(settings.select, build_registry(settings))
    except SettingsError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from None
    except LLMError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None


def register(app: typer.Typer) -> None:
    """Register the ``select`` command on ``app``."""

    @app.command(name="select")
    def select(
        utterance: str = typer.Argument(..., help='e.g. "I-40 EB between Harrison Ave and NC 54".'),
        # str, not Path: a Path argument collapses "https://host/x" to "https:/host/x".
        source: str = typer.Argument(..., help="Path/URL to a GMNS network."),
        provider: str = typer.Option(
            None, "--provider", help="Parser: stub | anthropic | openai | gemini | ollama (default: settings)."
        ),
        model: str = typer.Option(
            None, "--model", help="Model id (default: settings, else the provider default; see `gmnspy llm status`)."
        ),
        engine: str = typer.Option(
            None, "--engine", help="Compute engine (DuckDB is the only one; kept for compatibility)."
        ),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout."),
    ) -> None:
        """Resolve a natural-language selection to GMNS link/node ids.

        Prints the validated selection fragment on success. On an ambiguous
        result it prints the fragment plus candidate notes; on not-found it
        prints diagnostics and exits non-zero.
        """
        parser = _make_parser(provider, model)
        try:
            intent = parser.parse(utterance)
        except LLMError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None

        net = Network.from_source(source, engine=resolve_engine(engine))
        result = resolve(intent, net)

        if result.status == "not_found":
            payload = {"status": result.status, "diagnostics": result.diagnostics}
            _emit(payload, json_out)
            raise typer.Exit(code=1)

        fragment = to_fragment(result)
        if result.status == "ambiguous":
            fragment["_status"] = "ambiguous"
            fragment["_diagnostics"] = result.diagnostics
        _emit(fragment, json_out)

    @app.command(name="select-serve")
    def select_serve(
        # str, not Path: a Path argument collapses "https://host/x" to "https:/host/x".
        source: str = typer.Argument(..., help="Path/URL to a GMNS network."),
        provider: str = typer.Option(
            None, "--provider", help="NL parser: stub | anthropic | openai | gemini | ollama (default: settings)."
        ),
        engine: str = typer.Option(
            None, "--engine", help="Ignored: DuckDB is the only engine (kept for compatibility)."
        ),
        host: str = typer.Option(None, "--host", help="Bind host."),
        port: int = typer.Option(None, "--port", help="Bind port."),
    ) -> None:
        """Serve the interactive selection map: now an alias of ``gmnspy app SOURCE``."""
        from .workbench import run_workbench

        del engine  # accepted for backward compatibility only
        typer.echo("note: `gmnspy select-serve` is now `gmnspy app`", err=True)
        run_workbench([str(source)], provider=provider, host=host, port=port)


def _emit(payload: dict, json_out: bool) -> None:
    if json_out:
        typer.echo(json.dumps(payload, default=str))
    else:
        render_dict(payload)
