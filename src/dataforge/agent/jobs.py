"""Bounded local jobs with atomic journals and heartbeat-based crash detection."""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from dataforge.agent.contracts import AgentError, compact
from dataforge.agent.paging import page
from dataforge.connections import RuntimeConnections, connection_scope, current_connections

TERMINAL = {"completed", "failed", "interrupted", "cancelled"}


class Jobs:
    """Manage bounded asynchronous jobs and their local JSON journals."""

    def __init__(self, home: Path) -> None:
        """Initialize the job journal and its two-worker executor.

        Args:
            home: Runtime data home where job records are stored."""
        self.directory = home / "agent" / "jobs"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="gravetrail-agent")
        self.lock = threading.RLock()

    def path(self, job_id: str) -> Path:
        """Return the journal path for a syntactically valid job identifier.

        Args:
            job_id: Hexadecimal job identifier.

        Returns:
            The path to the job's JSON journal.

        Raises:
            AgentError: If the identifier is malformed."""
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise AgentError("not_found", "Job does not exist")
        return self.directory / (job_id + ".json")

    def write(self, record: dict[str, Any]) -> None:
        """Atomically publish a job record to its journal file.

        Args:
            record: Job state containing a ``job_id`` field.

        Raises:
            PermissionError: If replacement remains blocked after retries."""
        target = self.path(record["job_id"])
        temporary = target.with_suffix("." + uuid.uuid4().hex + ".tmp")
        temporary.write_text(compact(record), encoding="utf-8")
        for attempt in range(20):
            try:
                temporary.replace(target)
                return
            except PermissionError:
                # Windows readers may briefly deny replacement of an open journal.
                if attempt == 19:
                    temporary.unlink(missing_ok=True)
                    raise
                time.sleep(.01)

    def read(self, job_id: str, workspace: str, private: bool=False) -> dict[str, Any]:
        """Read a job record, hiding internal access and request fields by default.

        Args:
            job_id: Identifier of the job to read.
            workspace: Workspace expected to own the job.
            private: Whether to include internal fields for trusted local callers.

        Returns:
            The job record, with stale nonterminal jobs reported as interrupted.

        Raises:
            AgentError: If the job is missing or belongs to another workspace."""
        try:
            for attempt in range(20):
                try:
                    with self.lock:
                        record = json.loads(self.path(job_id).read_text(encoding="utf-8"))
                    break
                except PermissionError:
                    if attempt == 19:
                        raise
                    time.sleep(.01)
        except (FileNotFoundError, ValueError):
            raise AgentError("not_found", "Job does not exist") from None
        if record["workspace_id"] != workspace:
            raise AgentError("not_found", "Job does not exist in this workspace")
        if record["status"] not in TERMINAL and time.time() - record["updated_at"] > 30:
            # Never rewrite a live worker's journal from a polling process.
            record = {**record, "status": "interrupted", "error": "Worker heartbeat expired; retry explicitly"}
        record['cancel_requested'] = self.path(job_id).with_suffix('.cancel').exists() and record['status'] not in TERMINAL
        return record if private else {k: v for k, v in record.items() if k not in {"access", "request"}}

    def create(self, workspace: str, operation: str, access: dict[str, Any] | None=None) -> dict[str, Any]:
        """Create and journal a queued job if capacity permits.

        Args:
            workspace: Workspace that owns the job.
            operation: Operation name to execute.
            access: Optional access snapshot associated with the job.

        Returns:
            The newly created queued job record.

        Raises:
            AgentError: If the journal limit or active-job limit is reached."""
        with self.lock:
            files = list(self.directory.glob("*.json"))
            if len(files) >= 1000:
                raise AgentError("busy", "Job journal limit reached; archive old local job files before retrying")
            active = []
            for path in files:
                record = json.loads(path.read_text(encoding="utf-8"))
                if record["status"] not in TERMINAL and time.time() - record["updated_at"] <= 30:
                    active.append(record)
            if len(active) >= 2 or any(r["workspace_id"] == workspace for r in active):
                raise AgentError("busy", "A job is already active for this workspace or both workers are busy")
            record = {"job_id": uuid.uuid4().hex, "workspace_id": workspace, "operation": operation,
                      "status": "queued", "progress": 0, "created_at": time.time(),
                      "updated_at": time.time(), "access": access or {}}
            self.write(record)
            return record

    def start(self, workspace: str, operation: str, function: Callable[..., Any], access: dict[str, Any] | None=None, *, connections: RuntimeConnections | None=None, cancellable: bool=False) -> dict[str, str]:
        """Queue an operation on the job executor.

        Args:
            workspace: Workspace that owns the job.
            operation: Operation name to execute.
            function: Work callback receiving a progress callback.
            access: Optional access snapshot associated with the job.
            connections: Optional runtime connection context for the worker.
            cancellable: Whether the callback accepts a cancellation predicate.

        Returns:
            The new job identifier and its initial status.

        Raises:
            AgentError: If a job cannot be created under current capacity limits."""
        record = self.create(workspace, operation, access)
        # Context variables are not inherited by ThreadPoolExecutor workers. Bind the
        # initiating session explicitly; the manager is never serialized to the journal.
        self.pool.submit(self.run, record, function, connections or current_connections(), cancellable)
        return {"job_id": record["job_id"], "status": "queued"}

    def cancel(self, job_id: str, workspace: str) -> dict[str, Any]:
        """Request cancellation for a nonterminal job in its owning workspace.

        Args:
            job_id: Identifier of the job to cancel.
            workspace: Workspace expected to own the job.

        Returns:
            The job identifier, current status, and whether cancellation was requested.

        Raises:
            AgentError: If the job does not exist or belongs to another workspace.
        """
        record = self.read(job_id, workspace)
        if record['status'] not in TERMINAL:
            # Separate marker cannot be overwritten by a heartbeat or another owner.
            self.path(job_id).with_suffix('.cancel').touch()
        return {'job_id': job_id, 'status': record['status'], 'cancel_requested': record['status'] not in TERMINAL}

    def run(self, record: dict[str, Any], function: Callable[..., Any], connections: RuntimeConnections | None=None, cancellable: bool=False) -> None:
        """Run a job while recording heartbeat, progress, and terminal status.

        Args:
            record: Mutable job record to update.
            function: Work callback receiving a progress callback.
            connections: Optional runtime connection context for the worker.
            cancellable: Whether the callback accepts a cancellation predicate.

        Raises:
            InterruptedError: If cancellation is requested before execution."""
        stop = threading.Event()
        marker = self.path(record['job_id']).with_suffix('.cancel')

        def cancelled() -> bool:
            """Return whether the job's cancellation marker exists."""
            return marker.exists()

        def update(**values: Any) -> None:
            """Update and persist the job record under the journal lock."""
            with self.lock:
                record.update(values, updated_at=time.time())
                self.write(record)

        def heartbeat() -> None:
            """Refresh the job timestamp until the worker signals completion."""
            while not stop.wait(2):
                update()

        update(status="running", started_at=time.time())
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            def progress(fraction, stage):
                update(progress=round(fraction, 3), stage=str(stage)[:100], stage_started_at=time.time())

            progress.bind_run = lambda run_id: update(run_id=run_id)

            with connection_scope(connections or current_connections()):
                if cancelled():
                    raise InterruptedError('Job cancelled before execution')
                result = function(progress, cancelled) if cancellable else function(progress)
            stop.set()
            thread.join()
            outcome = result.get('status') if isinstance(result, dict) else None
            status = outcome if outcome in {'failed', 'cancelled', 'interrupted'} else 'completed'
            update(status=status, progress=1, result=result, finished_at=time.time())
        except Exception as exc:
            stop.set()
            thread.join()
            code = exc.code if isinstance(exc, AgentError) else type(exc).__name__
            update(status="cancelled" if isinstance(exc, InterruptedError) else "failed", error=code,
                   finished_at=time.time())
        finally:
            marker.unlink(missing_ok=True)

    def wait(self, job_id: str, workspace: str, timeout: float=300) -> dict[str, Any]:
        """Poll a job until it reaches a terminal state or the timeout expires.

        Args:
            job_id: Identifier of the job to wait for.
            workspace: Workspace expected to own the job.
            timeout: Maximum number of seconds to wait.

        Returns:
            The terminal job record.

        Raises:
            AgentError: If the job is missing or still running when time expires."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            record = self.read(job_id, workspace)
            if record["status"] in TERMINAL:
                return record
            time.sleep(.05)
        raise AgentError("busy", "Job is still running; poll its job_id", job_id=job_id)

    def close(self) -> None:
        """Wait for submitted jobs and shut down the executor."""
        self.pool.shutdown(wait=True)


def status_result(record: dict[str, Any], options: Any) -> dict[str, Any]:
    """Build a bounded public job response, paging diagnostics when requested.

    Args:
        record: Internal job record.
        options: Validated response detail and character-budget options.

    Returns:
        A sanitized job response, optionally with a diagnostics page.

    Raises:
        AgentError: If the serialized response exceeds the requested budget."""
    result = {k: v for k, v in record.items() if k not in {"access", "request"}}
    if "diagnostics" in result.get("result", {}):
        diagnostics = result["result"]["diagnostics"]
        result["result"] = {k: v for k, v in result["result"].items() if k != "diagnostics"}
        result["result"]["diagnostic_count"] = len(diagnostics)
        if options.detail_level != "summary":
            return page([{"diagnostic": d} for d in diagnostics], options,
                        [record["job_id"], record["updated_at"]], **result)
    if len(compact(result)) > options.max_chars:
        raise AgentError("budget_too_small", "Job result exceeds max_chars; increase the response budget")
    return result
