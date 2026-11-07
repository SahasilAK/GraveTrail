# Start with one persisted workflow

This walkthrough uses parser mode and local fixtures, so it needs no database server,
SAS installation, dbt executable or provider credential. It creates a temporary home and
closes the Store before deleting it.

## Install the locked environment

From a checkout with Python 3.11 or newer and `uv` installed:

```sh
uv sync --locked --extra dev
uv run gravetrail --help
uv run pytest -q tests/test_workflow.py
```

The project metadata supports Python 3.11+; pull-request CI currently exercises Python 3.12
on Ubuntu and Windows. `uv.lock` selects exact packages. The `ai-tokenizers` extra is optional;
parser analysis does not require it. See [technology](technology.md) before changing a pin.

## Run the application safely

```sh
uv run gravetrail-ui --home /absolute/path/to/new-disposable-home
```

On Windows, supply an absolute path such as `D:/scratch/gravetrail-dev-home`. The launcher
initializes the Store, locates checkout or bundled UI assets and then starts Streamlit on
loopback. The source-checkout default is `.dataforge` under the working directory unless
`DATAFORGE_HOME` overrides it. Installed and frozen launches select platform user-data homes;
these retain legacy `DataForge`/`dataforge` directory names for compatibility.

Direct development startup is also available:

```sh
uv run streamlit run app.py --server.address 127.0.0.1
```

Set `DATAFORGE_HOME` in the launching shell first when using that command. Stop the UI before
opening its home from an independent CLI or MCP process. A second workspace in the same
Store is isolated by workspace ID, but it is not a separate database process owner.

## Trace one source to one output

Save the following as a temporary Python script at the checkout root and run it with
`uv run python <script-name>.py`. The APIs are internal; the pattern mirrors the
[persisted workflow test](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_workflow.py).

```python
from tempfile import TemporaryDirectory

from dataforge.graph import LineageGraph
from dataforge.ingestion import Importer
from dataforge.services import analyze, column_report
from dataforge.store import Store

with TemporaryDirectory(prefix="gravetrail-doc-example-") as home:
    store = Store(home)
    try:
        workspace = store.create_workspace("First investigation")
        imported = Importer(store, workspace).files(
            [("jobs/orders.sql", b"CREATE TABLE mart.orders AS SELECT id FROM raw.orders;")],
            {".sql"},
        )
        assert imported.accepted == 1
        run = analyze(store, workspace)
        graph = LineageGraph(store.assets(workspace), store.edges(workspace))
        target = next(a for a in graph.search("mart.orders") if a["name"] == "mart.orders")
        report = graph.path_report(target["asset_id"], depth=5, include_code=True)
        assert run["edges"] == 1
        assert graph.search("raw.orders")
        print(report)
        source = next(a for a in graph.search("raw.orders") if a["name"] == "raw.orders")
        print(column_report(store, workspace, source["asset_id"]))
        print(analyze(store, workspace))  # unchanged input can reuse the parse cache
    finally:
        store.close()
```

The importer records a relative source path, decoded text, content hash and original blob.
The parser emits an operation referencing `raw.orders` and `mart.orders`. Publication resolves
stable identities and commits statements, operations, edges, direct column usage and derived
column facts together. `LineageGraph` reads those committed rows; `include_code=True` explicitly
adds source text to a path report. `column_report` answers where `raw.orders.id` is directly
referenced. Transformation tracing is a separate API.

## Read the implementation in this order

| Step | Source | What to look for |
| --- | --- | --- |
| Application startup | [app.py](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/app.py), [launcher.py](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/launcher.py) | navigation, home selection, connection scope |
| Safe import | [ingestion.py](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/ingestion.py) | `Limits`, `safe_relative`, `Importer.files`, immutable originals |
| Parse contracts | [models.py](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/models.py), [SQL parser](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/parsers/sql.py) | `ParseResult`, `Operation`, exact statement coordinates |
| Orchestration | [services.py](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/services.py) | cache key, selected versus pending files, one materialization transaction |
| Persistence | [store.py](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/store.py) | migrations, reentrant lock, transactions, version-pinned originals |
| Investigation | [graph.py](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/graph.py) | evidence arrays, cycle/depth bounds, incomplete reports |

For an end-to-end fixture with SQL, SAS, CSV, cycles and temporary stages, read
[`test_full_persisted_workflow_and_incremental`](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_workflow.py). Follow with
[internal API examples](internal-api.md) and the [subsystem map](code-map.md).
