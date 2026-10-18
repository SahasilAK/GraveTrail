"""Shared stored-fact inventory, history, dictionary, schema and health reports."""
import json
from collections import Counter

from dataforge.agent.contracts import AgentError
from dataforge.graph import LineageGraph
from dataforge.services import compare_runs

READS = {'dictionary', 'asset_schema', 'health', 'lineage_validate', 'runs_list', 'run_get',
         'ingestions_list', 'ingestion_get', 'runs_compare', 'source_metadata'}


def data_dictionary(store, workspace, query=''):
    rows = []
    for asset in store.assets(workspace):
        if query.casefold() not in asset['name'].casefold():
            continue
        metadata = json.loads(asset['metadata'])
        columns = metadata.get('columns', [])
        if columns:
            provenance = 'SQL DDL declaration' if metadata.get('schema_status') == 'declared' else 'CSV header / sampled type'
            rows.extend({'asset': asset['name'], 'column': c['name'], 'type': c['type'], 'provenance': provenance} for c in columns)
        else:
            usages = store.rows('SELECT DISTINCT column_name FROM column_usages WHERE workspace_id=? AND asset_id=? ORDER BY column_name', [workspace, asset['asset_id']])
            rows.extend({'asset': asset['name'], 'column': u['column_name'], 'type': 'unknown',
                         'provenance': 'direct code reference; incomplete schema'} for u in usages)
            if not usages:
                rows.append({'asset': asset['name'], 'column': 'unknown', 'type': 'unknown', 'provenance': 'table reference only'})
    return rows


def workspace_health(store, workspace, graph=None, limit=50):
    graph = graph or LineageGraph(store.assets(workspace), store.edges(workspace),
        store.setting(workspace, 'min_lineage_confidence', 0.), store.setting(workspace, 'include_inferred', True))
    files = store.files(workspace)
    hotspots = sorted([{'asset_id': n, 'name': a['name'], 'connections': graph.graph.degree(n),
                        'downstream': graph.graph.out_degree(n)} for n, a in graph.nodes(data=True)],
                       key=lambda x: (-x['connections'], x['name'], x['asset_id']))
    cycles = graph.cycles()
    return {'counts': {'source_files': len(files), 'assets': len(graph.nodes), 'edges': len(store.edges(workspace)),
            'diagnostics': len(store.diagnostics(workspace)), 'isolated': sum(graph.graph.degree(n) == 0 for n in graph.nodes),
            'temporary': sum(a['temporary'] for _, a in graph.nodes(data=True)), 'cyclic_groups': len(cycles)},
            'parsing_status': dict(Counter(f['parsing_status'] for f in files)), 'hotspots': hotspots[:limit],
            'cycles': cycles[:limit], 'truncated': graph.truncated or len(hotspots) > limit or len(cycles) > limit}


def validate_lineage_evidence(store, workspace):
    invalid = []
    edges = store.edges(workspace)
    for edge in edges:
        valid = bool(edge['code']) and 1 <= edge['start_line'] <= edge['end_line'] and 0 <= edge['confidence'] <= 1
        try:
            source = store.file(edge['file_id'], edge['source_hash'])
            lines = source['raw_content'].splitlines(keepends=True)
            valid &= edge['end_line'] <= len(lines) and edge['code'].strip() in ''.join(lines[edge['start_line'] - 1:edge['end_line']])
        except (ValueError, OSError):
            valid = False
        if not valid:
            invalid.append({'edge_id': edge['edge_id'], 'file_id': edge['file_id'], 'reason': 'missing_or_invalid_original_evidence'})
    return {'checked': len(edges), 'invalid_count': len(invalid), 'invalid': invalid,
            'meaning': 'Stored evidence integrity only; no reparsing, repair or runtime correctness claim'}


def code_matches(store, workspace, query, limit=1000):
    if not query or len(query) > 1024:
        raise AgentError('validation_failed', 'Literal code query requires 1–1024 characters')
    rows = []
    for source in store.files(workspace):
        if source['extension'] == '.csv':
            continue
        for line, text in enumerate(store.file(source['file_id'])['raw_content'].splitlines(), 1):
            if query.casefold() in text.casefold():
                rows.append({'file_id': source['file_id'], 'path': source['relative_path'], 'line': line, 'code': text,
                             'content_hash': source['content_hash']})
                if len(rows) >= limit:
                    return rows
    return rows


class ReportOperations:
    def _dictionary(self, w, opts, query=''):
        return self._page(w, opts, ['dictionary', query], data_dictionary(self.store, w, query), analysis_current=self._current(w))

    def _health(self, w, opts):
        graph = self._graph(w, opts, '')
        result = workspace_health(self.store, w, graph, min(opts.limit, opts.max_items))
        return {**result, 'analysis_current': self._current(w), 'complete': self._current(w) and not result['truncated']}

    def _asset_schema(self, w, opts, asset):
        selected = self._asset(w, asset)
        metadata = json.loads(selected['metadata'])
        evidence = metadata.get('schema_evidence', [])
        if opts.detail_level == 'detailed':
            self._workspace(w, source=True)
            evidence = [{**e, 'original': self._statement(w, e['statement_id'])} for e in evidence]
        return {'asset_id': selected['asset_id'], 'columns': metadata.get('columns', []),
                'schema_status': metadata.get('schema_status', 'sampled' if selected['kind'] == 'csv' else 'unknown'),
                'evidence': evidence, 'analysis_current': self._current(w), 'complete': self._current(w),
                'warning': 'Declared/sample metadata is not a verified live database schema'}

    def _lineage_validate(self, w, opts):
        result = validate_lineage_evidence(self.store, w)
        invalid = result.pop('invalid')
        return self._page(w, opts, 'lineage_validate', invalid, **result, analysis_current=self._current(w))

    def _runs_list(self, w, opts):
        rows = self.store.rows('SELECT run_id,status,analyzed,cached,duration,created_at FROM analysis_runs WHERE workspace_id=? ORDER BY created_at DESC,run_id', [w])
        return self._page(w, opts, 'runs', rows, analysis_current=self._current(w))

    def _run_get(self, w, opts, run_id):
        rows = self.store.rows('SELECT * FROM analysis_runs WHERE workspace_id=? AND run_id=?', [w, run_id])
        if not rows:
            raise AgentError('not_found', 'Analysis run does not exist in this workspace')
        return {'run': rows[0], 'analysis_current': self._current(w), 'complete': True}

    def _ingestions_list(self, w, opts):
        rows = self.store.rows('SELECT ingestion_id,created_at,report FROM ingestion_runs WHERE workspace_id=? ORDER BY created_at DESC,ingestion_id', [w])
        return self._page(w, opts, 'ingestions', rows)

    def _ingestion_get(self, w, opts, ingestion_id):
        rows = self.store.rows('SELECT ingestion_id,created_at,report FROM ingestion_runs WHERE workspace_id=? AND ingestion_id=?', [w, ingestion_id])
        if not rows:
            raise AgentError('not_found', 'Ingestion does not exist in this workspace')
        return {'ingestion': rows[0], 'complete': True}

    def _runs_compare(self, w, opts, before, after):
        first, second = (self._run_get(w, opts, rid)['run'] for rid in (before, after))
        if first['status'] != 'completed' or second['status'] != 'completed':
            raise AgentError('validation_failed', 'Compare completed analysis runs only')
        return {'before': before, 'after': after, 'comparison': compare_runs(first, second), 'complete': True}

    def _source_metadata(self, w, opts, file_id):
        files = [f for f in self.store.files(w) if f['file_id'] == file_id]
        if not files:
            raise AgentError('not_found', 'Source does not exist in this workspace')
        fields = ('file_id', 'relative_path', 'extension', 'encoding', 'file_size', 'metadata', 'line_count', 'content_hash', 'parsing_status', 'error_details')
        result = {key: files[0][key] for key in fields}
        metadata = json.loads(result['metadata'])
        if opts.detail_level != 'detailed':
            metadata.pop('preview', None)
        result['metadata'] = metadata
        return {**result, 'analysis_current': self._current(w)}
