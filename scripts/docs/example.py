"""Recreate the public snapshot from tracked fixtures; print the digest for review."""
from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'docs/assets/examples/lineage.html'
POLICY = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
          "img-src data:; base-uri 'none'; form-action 'none'")


def render_example() -> str:
    """Analyze only safe scenario fixtures in an isolated home and return HTML."""
    # Authoring requires application dependencies; the docs-only build uses saved output.
    from dataforge.exports import graph_html
    from dataforge.graph import LineageGraph
    from dataforge.ingestion import Importer
    from dataforge.services import analyze
    from dataforge.store import Store

    with TemporaryDirectory(prefix='gravetrail-doc-example-') as home:
        store = Store(home)
        try:
            workspace = store.create_workspace('Safe documentation scenario')
            fixture = ROOT / 'tests/fixtures/scenario'
            Importer(store, workspace, [fixture]).directory(fixture, {'.sql', '.sas', '.csv'})
            analyze(store, workspace)
            graph = LineageGraph(store.assets(workspace), store.edges(workspace))
            target = graph.search('mart.customer_summary')[0]['asset_id']
            graph = graph.focus(target, 'upstream', 10, 50)
            assert len(graph.nodes) == 4 and len(graph.graph.edges) == 3
            for node in graph.nodes.values():
                node.pop('workspace_id', None)
            output = graph_html(graph)
            assert str(ROOT) not in output and 'OneDrive' not in output
            return output.replace('<meta charset="utf-8">',
                '<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' + POLICY + '">')
        finally:
            store.close()


if __name__ == '__main__':
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render_example(), encoding='utf-8', newline='\n')
    print(f'Review embedded evidence and browser behavior before updating PUBLIC_HTML_SHA256:\n'
          f'{hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}')
