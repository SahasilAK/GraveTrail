"""Private detached CLI worker; fixed Python entry point, never a supplied command."""
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb

from dataforge.agent.contracts import AccessPolicy
from dataforge.agent.jobs import Jobs
from dataforge.agent.service import AgentService
from dataforge.store import Store


def main(home: str | Path, job_id: str) -> None:
    """Run the journaled job selected by the detached worker entry point.

    Args:
        home: Runtime data home containing the job journal and workspace data.
        job_id: Identifier of the queued job to execute."""
    journal = Jobs(Path(home))
    import json
    record = json.loads(journal.path(job_id).read_text(encoding="utf-8"))
    request = record.pop("request")

    def execute(progress: Callable[[float, Any], None], cancelled: Callable[[], bool]) -> Any:
        """Open the store and execute one persisted worker request.

        Args:
            progress: Callback used to publish job progress updates.
            cancelled: Callback that reports a cancellation request.

        Returns:
            The operation result stored in the job journal.

        Raises:
            duckdb.IOException: If the database remains busy past the retry window.
            AgentError: If the operation is invalid or unauthorized."""
        deadline = time.monotonic() + 10
        while True:
            try:
                store = Store(home)
                break
            except duckdb.IOException:
                # A CLI status probe may briefly own DuckDB before this detached worker.
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.1)
        service = AgentService(store, AccessPolicy(**request["policy"]))
        try:
            return service.run_operation(record["workspace_id"], record["operation"], request["arguments"], progress,
                                         cancelled=cancelled)
        finally:
            service.close()
            store.close()

    try:
        journal.run(record, execute, cancellable=True)
    finally:
        journal.close()


if __name__ == "__main__":
    main(*sys.argv[1:])
