"""Bounded local jobs with atomic journals and heartbeat-based crash detection."""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from dataforge.agent.contracts import AgentError, compact
from dataforge.agent.paging import page

TERMINAL = {"completed", "failed", "interrupted"}


class Jobs:
    def __init__(self, home):
        self.directory = home / "agent" / "jobs"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dataforge-agent")
        self.lock = threading.RLock()

    def path(self, job_id):
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise AgentError("not_found", "Job does not exist")
        return self.directory / (job_id + ".json")

    def write(self, record):
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

    def read(self, job_id, workspace, private=False):
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
        return record if private else {k: v for k, v in record.items() if k not in {"access", "request"}}

    def create(self, workspace, operation, access=None):
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
                      "status": "queued", "progress": 0, "updated_at": time.time(), "access": access or {}}
            self.write(record)
            return record

    def start(self, workspace, operation, function, access=None):
        record = self.create(workspace, operation, access)
        self.pool.submit(self.run, record, function)
        return {"job_id": record["job_id"], "status": "queued"}

    def run(self, record, function):
        stop = threading.Event()

        def update(**values):
            with self.lock:
                record.update(values, updated_at=time.time())
                self.write(record)

        def heartbeat():
            while not stop.wait(2):
                update()

        update(status="running")
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            result = function(lambda fraction, _: update(progress=round(fraction, 3)))
            stop.set()
            thread.join()
            update(status="completed", progress=1, result=result)
        except Exception as exc:
            stop.set()
            thread.join()
            code = exc.code if isinstance(exc, AgentError) else type(exc).__name__
            update(status="failed", error=code)

    def wait(self, job_id, workspace, timeout=300):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            record = self.read(job_id, workspace)
            if record["status"] in TERMINAL:
                return record
            time.sleep(.05)
        raise AgentError("busy", "Job is still running; poll its job_id", job_id=job_id)

    def close(self):
        self.pool.shutdown(wait=True)


def status_result(record, options):
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
