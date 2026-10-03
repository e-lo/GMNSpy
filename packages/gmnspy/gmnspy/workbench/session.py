"""Workbench session: the one place state changes, via :meth:`Session.dispatch`.

UI clicks (``POST /api/actions``), Python (``session.dispatch(...)``), and, in
P3, the NL assistant all funnel through ``dispatch``. Each call is recorded as a
:class:`HistoryEntry` carrying its ``to_python`` replay snippet, and publishes
``history`` + ``state`` events for the browser. Network *edits* are not actions
here yet: in P2 they become ProjectCard-shaped ``NetworkChange`` objects.

Actions marked ``runs_as_job`` (``OpenNetwork``, ``BuildNetwork``) do their slow
work on a background job thread *without* the session lock. :meth:`Session.submit`
starts one and returns immediately (the HTTP path); :meth:`Session.dispatch` starts
one and waits (Python, the CLI), so callers see the same blocking behaviour as before.

A successful job ends in :meth:`Session._commit`, which registers the loaded network
*and* records its history entry in one critical section. History order therefore
always matches registry order, even when two jobs overlap, so replaying the history
reproduces the same network ids. Failed and cancelled jobs are recorded by
:meth:`Session._finish`.
"""

from __future__ import annotations

import copy
import logging
import threading
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from datagrove.engines.ibis_engine import IbisEngine

from gmnspy import Network
from gmnspy.config import LoadedSettings, Settings, SettingsError, get_value, load_settings, save_setting
from gmnspy.select.intent import SelectionIntent
from gmnspy.select.parse import ClaudeParser, StubParser
from gmnspy.select.resolve import resolve_frames
from gmnspy.viz.styling import styleable_columns

from . import build
from .actions import (
    Action,
    BuildNetwork,
    ClearSelection,
    CloseNetwork,
    Navigate,
    OpenNetwork,
    Select,
    SetActiveNetwork,
    SetSetting,
    Style,
    parse_action,
    to_python,
)
from .errors import ActionError, ApprovalRequired, JobCancelled, NotSupportedYet, PathNotAllowed
from .estimate import Estimate, needs_approval
from .events import EventBus
from .jobs import Job, JobContext, JobRunner
from .paths import open_locator
from .registry import NetworkHandle, NetworkRegistry, as_pandas
from .selection import selection_payload, unparsed_payload

__all__ = ["DEFAULT_STYLE", "ActionError", "ApprovalRequired", "HistoryEntry", "NotSupportedYet", "Session"]

logger = logging.getLogger(__name__)

DEFAULT_STYLE: dict[str, Any] = {
    "color_by": "none",
    "ramp": "YlOrRd",
    "offset": True,
    "show_direction": False,
    "show_legend": True,
    "show": {"links": True, "nodes": True, "labels": True, "selection": True},
    "colors": {"links": [46, 64, 110], "nodes": [70, 90, 120], "selection": [255, 140, 59]},
}


@dataclass
class _Loaded:
    """A job's loaded network, waiting for :meth:`Session._commit` to register it."""

    net: Network
    frames: dict[str, Any]
    source: str
    label: str | None
    net_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)  # merged into the job result after ``net_id``


@dataclass
class HistoryEntry:
    """One dispatched action, successful or not."""

    seq: int
    action: dict[str, Any]
    python: str
    ok: bool
    error: str | None
    error_type: str | None
    result: Any
    ts: float

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe copy."""
        return asdict(self)


class Session:
    """Live workbench state: open networks, selection, style, settings, history."""

    def __init__(
        self,
        *,
        project_dir: str | Path | None = None,
        overrides: Mapping[str, Any] | None = None,
        parser: Any = None,
        environ: Mapping[str, str] | None = None,
        http: Any = None,
    ) -> None:
        """Load settings (raises :class:`~gmnspy.config.SettingsError` on bad config) and start empty.

        ``http`` is the HTTP session for Overpass/Nominatim (anything with ``get``/``post`` like
        :mod:`requests`); ``None`` means ``requests`` itself. Tests inject a fake.
        """
        self.project_dir = project_dir
        self._environ = environ
        self._overrides: dict[str, Any] = dict(overrides or {})
        self.loaded: LoadedSettings = load_settings(project_dir=project_dir, overrides=self._overrides, environ=environ)
        self.registry = NetworkRegistry()
        self.events = EventBus()
        self.active: str | None = None
        self.selection: dict[str, Any] | None = None
        self.style: dict[str, Any] = copy.deepcopy(DEFAULT_STYLE)
        self.history: list[HistoryEntry] = []
        self._injected_parser = parser
        self._parser = parser
        self.http = http
        self.jobs = JobRunner(lambda event: self.events.publish(event))  # late-bound, like every other publish
        self._lock = threading.RLock()
        self._committed: dict[str, int] = {}  # job id -> history seq its ``_commit`` recorded

    # ------------------------------------------------------------------ public API

    @property
    def settings(self) -> Settings:
        """The currently resolved settings."""
        return self.loaded.settings

    def parser(self) -> Any:
        """The NL parser chosen by ``select.provider`` (built lazily; an injected parser wins)."""
        if self._parser is None:
            sel = self.settings.select
            self._parser = ClaudeParser(model=sel.model) if sel.provider == "claude" else StubParser()
        return self._parser

    def dispatch(self, action: Action | dict[str, Any]) -> Any:
        """Apply ``action`` (waiting for a job action to finish) and return its result.

        Raises the recorded failure's type: :class:`~gmnspy.workbench.errors.ApprovalRequired` (with
        ``.estimate``), :class:`NotSupportedYet`, :class:`~gmnspy.workbench.errors.PathNotAllowed`,
        :class:`~gmnspy.workbench.errors.JobCancelled`, else :class:`ActionError`.
        """
        entry = self.dispatch_recorded(action)
        if entry.ok:
            return entry.result
        if entry.error_type == "ApprovalRequired":
            raise ApprovalRequired(Estimate(**entry.result["estimate"]), entry.result["threshold_s"])
        raise _ERROR_TYPES.get(entry.error_type or "", ActionError)(entry.error)

    do = dispatch

    def dispatch_recorded(self, action: Action | dict[str, Any]) -> HistoryEntry:
        """Apply ``action``, record and publish it, and return the entry (never raises ``ActionError``).

        A ``runs_as_job`` action is submitted as a background job and this call waits for it.
        """
        if isinstance(action, dict):
            action = parse_action(action)
        if action.runs_as_job:
            # The job thread needs the lock (``_commit``/``_finish``) and we wait for it below, so a
            # caller already holding the lock (e.g. a handler) would deadlock: fail loudly instead.
            if self._lock._is_owned():  # type: ignore[attr-defined]  # RLock's owner check
                raise RuntimeError("cannot run a job action while holding the session lock (it would deadlock)")
            job = self.submit(action)
            # Wait OUTSIDE the session lock: the job thread takes it in ``_commit`` and ``_finish``,
            # so waiting while holding it would deadlock. Never call this with the lock held.
            job.wait()
            if job.history_seq is None:  # on_finish itself failed (already logged by the runner)
                raise RuntimeError(f"job {job.id} finished without a history entry")
            return self.history[job.history_seq - 1]
        handler = getattr(self, f"_do_{action.type}")
        with self._lock:
            try:
                result, ok, error, error_type = handler(action), True, None, None
            except ActionError as exc:  # includes NotSupportedYet
                result, ok, error, error_type = exc.payload, False, str(exc), type(exc).__name__
            except Exception as exc:  # boundary: an unexpected handler failure is still a recorded, user-facing error
                logger.exception("workbench action %s failed", action.type)
                error = f"internal error: {type(exc).__name__}: {exc}"
                result, ok, error_type = None, False, "InternalError"
            return self._record(action, ok=ok, result=result, error=error, error_type=error_type)

    def submit(self, action: Action | dict[str, Any]) -> Job:
        """Start a ``runs_as_job`` action on a background job and return the :class:`Job` at once.

        The history entry is recorded when the job finishes (so ``seq`` follows completion order).
        """
        if isinstance(action, dict):
            action = parse_action(action)
        if not action.runs_as_job:
            raise ValueError(f"{action.type} is not a job action; use dispatch()")
        run = getattr(self, f"_job_{action.type}")
        return self.jobs.submit(
            action.type,
            action.job_label(),
            lambda ctx: self._commit(action, ctx, run(action, ctx)),
            on_finish=lambda job: self._finish(action, job),
        )

    def _commit(self, action: Action, ctx: JobContext, loaded: _Loaded) -> dict[str, Any]:
        """Register ``loaded`` and record the success entry in ONE critical section; return the job result.

        Doing both under one lock acquisition is what keeps history order equal to registry order:
        with separate acquisitions two overlapping jobs could register A, B but record B, A, and a
        replay would then hand out swapped ids. The caller's last ``ctx.stage`` was the final
        cancellation checkpoint, so nothing can cancel the job once this runs.
        """
        with self._lock:
            handle = self.registry.add(loaded.net, source=loaded.source, label=loaded.label, net_id=loaded.net_id)
            handle.prime(**loaded.frames)
            self.active = handle.id
            result = {"net_id": handle.id, **loaded.extra}
            entry = self._record(action, ok=True, result=result, error=None, error_type=None)
            self._committed[ctx.job_id] = entry.seq
        return result

    def _finish(self, action: Action, job: Job) -> None:
        """Job callback: link the committed entry to the job, or record a failure/cancellation entry."""
        with self._lock:
            seq = self._committed.pop(job.id, None)
            if seq is None:
                ok = job.status == "done"  # only a job whose commit never ran gets here: normally a failure
                seq = self._record(
                    action,
                    ok=ok,
                    result=job.result if ok else job.payload,
                    error=job.error,
                    error_type=job.error_type,
                ).seq
        self.jobs.update(job, history_seq=seq)

    def _record(
        self, action: Action, *, ok: bool, result: Any, error: str | None, error_type: str | None
    ) -> HistoryEntry:
        """Append and publish a history entry (then a ``state`` event on success). Call with the lock held."""
        entry = HistoryEntry(
            seq=len(self.history) + 1,
            action=action.model_dump(mode="json"),
            python=to_python(action),
            ok=ok,
            error=error,
            error_type=error_type,
            result=copy.deepcopy(result),
            ts=time.time(),
        )
        self.history.append(entry)
        self.events.publish({"type": "history", "entry": entry.to_dict()})
        if ok:
            self.events.publish({"type": "state", "state": self.state()})
        return entry

    def add_network(
        self, net: Network, *, source: str = "<python>", label: str | None = None, net_id: str | None = None
    ) -> NetworkHandle:
        """Register an already-loaded ``Network`` (the Python path; not an Action because it isn't JSON)."""
        with self._lock:
            handle = self.registry.add(net, source=source, label=label, net_id=net_id)
            self.active = self.active or handle.id
            self.events.publish({"type": "state", "state": self.state()})
        return handle

    def state(self) -> dict[str, Any]:
        """JSON-safe snapshot pushed to the browser."""
        with self._lock:
            return {
                "networks": [h.summary() for h in self.registry],
                "active": self.active,
                "selection": copy.deepcopy(self.selection),
                "style": copy.deepcopy(self.style),
            }

    def settings_payload(self) -> dict[str, Any]:
        """Settings values, per-key sources, JSON schema, and file paths (for the Settings UI)."""
        return {
            "values": self.settings.model_dump(mode="json"),
            "sources": dict(self.loaded.sources),
            "schema": Settings.model_json_schema(),
            "paths": {"user": str(self.loaded.user_path), "project": str(self.loaded.project_path)},
        }

    # ------------------------------------------------------------------ handlers (run under the lock)

    def _handle(self, net_id: str | None) -> NetworkHandle:
        target = net_id or self.active
        if target is None:
            raise ActionError("no network is open")
        try:
            return self.registry.get(target)
        except KeyError as exc:
            raise ActionError(exc.args[0]) from exc

    # -------------------------------------------------- job actions (run on a job thread, lock only to register)

    def _load(self, source: str, spec_version: str) -> tuple[Network, dict[str, Any]]:
        """Load ``source`` and materialise its link/node frames, all without the session lock."""
        try:
            net = Network.from_source(source, spec_version=spec_version)
            frames = {"links_df": as_pandas(net.links), "nodes_df": as_pandas(net.nodes)}
        except Exception as exc:  # boundary: any load failure is a user-facing error, not a crash
            raise ActionError(f"could not open {source}: {exc}") from exc
        return net, frames

    def _job_open_network(self, action: OpenNetwork, ctx: JobContext) -> _Loaded:
        settings = self.settings
        source = open_locator(action.source, settings)  # only remote URLs skip io.allowed_roots
        ctx.stage("open", progress=0.1)
        net, frames = self._load(source, settings.io.spec_version)
        ctx.stage("register", progress=0.9)  # last cancellation checkpoint before ``_commit``
        return _Loaded(net, frames, source=source, label=action.label, net_id=action.net_id)

    def _job_build_network(self, action: BuildNetwork, ctx: JobContext) -> _Loaded:
        settings = self.settings
        plan = build.plan_build(action, settings)
        threshold = settings.app.approve_above_s
        with build.staging(plan.dest) as tmp:  # removes the partial output on any failure, cancel included
            engine = IbisEngine()  # private connection: never shared with the networks the browser reads
            try:
                ctx.stage("estimate", progress=0.0)
                estimate = build.estimate_for(action, plan, settings, http=self.http, engine=engine)
                over = needs_approval(estimate, threshold)
                if over and not action.approved:
                    raise ApprovalRequired(estimate, threshold)
                try:
                    net = build.fetch_and_convert(
                        action, plan, settings, ctx, estimate=estimate, http=self.http, engine=engine
                    )
                    build.write_output(net, tmp, action.output_format, ctx)
                    # Last cancellation checkpoint: once the output is promoted the build is done, so a
                    # later cancel cannot leave a finished output that the history calls cancelled.
                    ctx.stage("open", progress=0.9)
                    build.promote(tmp, plan.dest)
                except ActionError as exc:  # includes JobCancelled: keep the estimate for the history entry
                    exc.payload = {**(exc.payload or {}), "estimate": estimate.to_dict()}
                    raise
            finally:
                engine.close()
        output = str(plan.dest)
        try:
            loaded, frames = self._load(output, action.spec_version or settings.io.spec_version)
        except ActionError as exc:
            failed = ActionError(
                f"the network was written to {output} but could not be opened ({exc}); open it with OpenNetwork"
            )
            failed.payload = {"output": output, "estimate": estimate.to_dict()}
            raise failed from exc
        extra = {
            "output": output,
            "estimate": estimate.to_dict(),
            "threshold_s": threshold,
            "approval": "given" if over else "not_needed",
        }
        return _Loaded(loaded, frames, source=output, label=action.label or action.name, extra=extra)

    def _do_close_network(self, action: CloseNetwork) -> None:
        self._handle(action.net_id)
        self.registry.remove(action.net_id)
        if self.selection and self.selection["net_id"] == action.net_id:
            self.selection = None
        if self.active == action.net_id:
            ids = self.registry.ids()
            self.active = ids[0] if ids else None

    def _do_set_active_network(self, action: SetActiveNetwork) -> None:
        self.active = self._handle(action.net_id).id

    def _do_select(self, action: Select) -> dict[str, Any]:
        if action.component != "roadway":
            raise NotSupportedYet("transit selection arrives with the transit component (phase P6)")
        handle = self._handle(action.net_id)
        if action.utterance is not None:
            try:
                intent = self.parser().parse(action.utterance)
            except Exception as exc:  # any parse failure is a normal "not_found" selection
                self.selection = unparsed_payload(handle, action.utterance, exc)
                return self.selection
        else:
            intent = SelectionIntent(link_ids=list(action.link_ids or []))
        result = resolve_frames(intent, handle.links_df(), handle.nodes_df())
        self.selection = selection_payload(handle, result, utterance=action.utterance)
        return self.selection

    def _do_clear_selection(self, action: ClearSelection) -> None:
        self.selection = None

    def _do_style(self, action: Style) -> dict[str, Any]:
        patch = action.model_dump(exclude_none=True, exclude={"type"})
        color_by = patch.get("color_by")
        if color_by not in (None, "none"):
            names = {c["name"] for c in styleable_columns(self._handle(None).links_df())}
            if color_by not in names:
                raise ActionError(f"cannot color by {color_by!r}; choose one of {sorted(names)}")
        for key, value in patch.items():
            self.style[key] = {**self.style[key], **value} if isinstance(value, dict) else value
        return copy.deepcopy(self.style)

    def _do_navigate(self, action: Navigate) -> None:
        if action.to_selection and not self.selection:
            raise ActionError("nothing is selected")
        self.events.publish({"type": "navigate", **action.model_dump(mode="json", exclude={"type"})})

    def _do_set_setting(self, action: SetSetting) -> dict[str, Any]:
        key = action.key.strip().lower()
        if any(key == k or k.startswith(f"{key}.") for k in _CONFIG_ONLY_KEYS):  # "io" would replace it too
            raise ActionError(
                f"{action.key} cannot be changed here: io.allowed_roots can only be set in config files, env, "
                "or on the command line"
            )
        try:
            if action.scope == "session":
                overrides = {**self._overrides, action.key: action.value}
                loaded = load_settings(project_dir=self.project_dir, overrides=overrides, environ=self._environ)
                self._overrides = overrides
            else:
                save_setting(
                    action.key, action.value, scope=action.scope, project_dir=self.project_dir, environ=self._environ
                )
                loaded = load_settings(project_dir=self.project_dir, overrides=self._overrides, environ=self._environ)
            value = get_value(loaded.settings, action.key)
        except SettingsError as exc:
            raise ActionError(str(exc)) from exc
        self.loaded = loaded
        if action.key.startswith("select.") and self._injected_parser is None:
            self._parser = None  # rebuilt from the new provider/model on next use
        return {"key": action.key, "value": value, "source": loaded.sources.get(action.key)}


#: Settings the action API refuses at every scope. ``io.allowed_roots`` is the sandbox for every local
#: read and write; if an action (a browser click, a replayed script, the NL assistant) could widen it,
#: the sandbox would protect nothing.
_CONFIG_ONLY_KEYS = ("io.allowed_roots",)

#: Recorded ``error_type`` -> the exception :meth:`Session.dispatch` re-raises (anything else: ActionError).
_ERROR_TYPES: dict[str, type[ActionError]] = {
    cls.__name__: cls for cls in (NotSupportedYet, JobCancelled, PathNotAllowed)
}
