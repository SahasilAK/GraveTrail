"""Managed, version-bound artifacts with bounded binary retrieval and read-time authorization."""
import base64
import hashlib
import json
import re
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from dataforge.agent.contracts import AgentError, compact
from dataforge.cleanup import checked_path
from dataforge.configuration import VisualizationSettings
from dataforge.excel_exports import XLSX_MIME
from dataforge.exports import graph_data, graph_html, path_rows, report_csv, report_html, source_bundle
from dataforge.reporting import code_matches, data_dictionary
from dataforge.services import column_report

READS = {'artifact_read', 'paths', 'steps', 'graph_view'}
WRITES = {'artifact_create'}
FORMATS = {'graph': {'html', 'json'}, 'paths': {'csv', 'json', 'xlsx'}, 'source-bundle': {'zip'},
           'original-source': {'raw'}, 'inventory': {'csv', 'json'}, 'code-search': {'csv', 'json'},
           'dictionary': {'csv', 'json', 'html'}, 'columns': {'csv', 'json', 'html'},
           'impact': {'csv', 'json', 'html'}, 'run-comparison': {'json'}, 'ai-result': {'json'}}
SOURCE_KINDS = {'graph', 'paths', 'source-bundle', 'original-source', 'code-search', 'columns', 'impact', 'ai-result'}
MAX_BYTES = 64 * 1024 * 1024


class Selection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    asset: str = Field(default='', max_length=1024)
    direction: Literal['upstream', 'downstream', 'combined'] = 'upstream'
    file_id: str = Field(default='', max_length=64)
    content_hash: str = Field(default='', max_length=64)
    file_ids: list[str] = Field(default_factory=list, max_length=500)
    versions: dict[str, str] = Field(default_factory=dict, max_length=500)
    query: str = Field(default='', max_length=1024)
    before: str = Field(default='', max_length=64)
    after: str = Field(default='', max_length=64)
    record_id: str = Field(default='', max_length=64)
    max_paths: int = Field(default=50, ge=1, le=500)
    include_evidence: bool = False
    include_source_text: bool = False


def _directory(store, workspace):
    if not re.fullmatch('[a-f0-9]{32}', workspace):
        raise AgentError('not_found', 'Artifact workspace does not exist')
    return checked_path(store.home, 'agent/artifacts/' + workspace)


def write_artifact(store, workspace, kind, format, data, complete, source_versions, source_required):
    if len(data) > MAX_BYTES:
        raise AgentError('resource_limit', 'Artifact exceeds 64 MB; narrow the selection')
    directory = _directory(store, workspace)
    directory.mkdir(parents=True, exist_ok=True)
    if sum(1 for _ in directory.iterdir()) >= 2000:
        raise AgentError('resource_limit', 'Managed artifact limit reached')
    aid = uuid.uuid4().hex
    mime = {'json': 'application/json', 'html': 'text/html', 'csv': 'text/csv', 'zip': 'application/zip', 'raw': 'application/octet-stream', 'xlsx': XLSX_MIME}[format]
    metadata = {'artifact_id': aid, 'schema_version': 1, 'workspace_id': workspace,
        'home_id': hashlib.sha256(str(store.home).encode()).hexdigest(), 'kind': kind, 'format': format,
        'mime_type': mime, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
        'complete': complete, 'source_required': source_required, 'source_versions': source_versions}
    with (directory / (aid + '.bin')).open('xb') as stream:
        stream.write(data)
    with (directory / (aid + '.json')).open('x', encoding='utf-8') as stream:
        stream.write(compact(metadata))
    return {k: v for k, v in metadata.items() if k not in {'home_id', 'source_required', 'source_versions'}}


class ArtifactOperations:
    def _artifact_graph(self, w, opts, asset, direction):
        selected = self._asset(w, asset)['asset_id']
        graph = self._graph(w, opts, selected)
        focused = graph.focus(selected, direction, opts.max_depth, opts.max_items)
        # Focus bounds must remain visible even when they stop exactly at a depth boundary.
        depth_boundary = any(set(graph.graph.predecessors(n) if direction == 'upstream' else
            graph.graph.successors(n) if direction == 'downstream' else set(graph.graph.predecessors(n)) | set(graph.graph.successors(n))) - set(focused.nodes)
            for n in focused.nodes)
        focused.truncated |= depth_boundary
        return selected, focused

    def _paths(self, w, opts, asset, direction='upstream', max_paths=50):
        if direction not in {'upstream', 'downstream'} or type(max_paths) is not int or not 1 <= max_paths <= 500:
            raise AgentError('validation_failed', 'Use upstream/downstream and 1–500 paths')
        selected = self._asset(w, asset)['asset_id']
        graph = self._graph(w, opts, selected)
        report = graph.path_report(selected, direction, max_paths, opts.max_depth)
        return self._page(w, opts, ['paths', selected, direction, max_paths], report['paths'],
            analysis_current=self._current(w), boundaries=['path_limit_depth_cycle_or_graph'] if report['truncated'] else [],
            direction=direction, selected_asset=selected, ordering='logical dependencies; not runtime execution')

    def _steps(self, w, opts, asset, direction='upstream'):
        _, graph = self._artifact_graph(w, opts, asset, direction)
        return self._page(w, opts, ['steps', asset, direction], graph.lineage_rows(), analysis_current=self._current(w),
            boundaries=['graph_limit_or_depth'] if graph.truncated else [], ordering='logical dependencies; not runtime execution')

    def _graph_view(self, w, opts, asset, direction='upstream', view='nodes', node_id='', edge_id=''):
        if view not in {'nodes', 'edges', 'tree'} or direction not in {'upstream', 'downstream', 'combined'}:
            raise AgentError('validation_failed', 'Use nodes, edges or tree view and a supported direction')
        selected, graph = self._artifact_graph(w, opts, asset, direction)
        data = graph_data(graph, VisualizationSettings.from_store(self.store, w))
        if view == 'nodes':
            rows = [{k: v for k, v in n.items() if k != 'metadata'} for n in data['nodes'] if not node_id or n['asset_id'] == node_id]
        elif view == 'edges':
            rows = []
            for edge in data['edges']:
                evidence = edge['evidence']
                if node_id and node_id not in {edge['source'], edge['target']}:
                    continue
                if edge_id and not any(e['edge_id'] == edge_id for e in evidence):
                    continue
                row = {**edge, 'evidence': [{k: v for k, v in e.items() if k != 'code'} for e in evidence]}
                if opts.detail_level == 'detailed':
                    self._workspace(w, source=True)
                    row['evidence'] = evidence
                rows.append(row)
        else:
            import networkx as nx
            traversal = graph.graph.reverse(copy=False) if direction == 'upstream' else (graph.graph.to_undirected(as_view=True) if direction == 'combined' else graph.graph)
            levels = nx.single_source_shortest_path_length(traversal, selected, cutoff=opts.max_depth)
            rows = [{'asset_id': n, 'name': graph.nodes[n]['name'], 'level': level,
                     'neighbors': sorted(traversal.neighbors(n)), 'boundary': 'depth' if level == opts.max_depth else ''}
                    for n, level in sorted(levels.items(), key=lambda x: (x[1], x[0]))]
        return self._page(w, opts, ['graph_view', asset, direction, view, node_id, edge_id], rows,
            analysis_current=self._current(w), boundaries=['graph_limit_or_depth'] if graph.truncated else [],
            selected_asset=selected, appearance=data['appearance'])

    def _artifact_create(self, w, opts, kind, format, selection):
        if kind == 'backup':
            raise AgentError('requires_local_admin', 'Whole-home backup downloads are local CLI/UI only')
        if format not in FORMATS.get(kind, set()):
            raise AgentError('validation_failed', 'Unsupported artifact kind/format combination')
        selection = Selection.model_validate(selection)
        source_required = kind in SOURCE_KINDS
        if source_required:
            self._workspace(w, write=True, source=True)
        if format == 'xlsx':
            from dataforge.services import export_lineage_excel

            target = self._asset(w, selection.asset)['asset_id']
            try:
                data, summary = export_lineage_excel(self.store, w, target, direction=selection.direction,
                    max_paths=selection.max_paths, max_depth=opts.max_depth, max_relationships=opts.max_items,
                    collapse_temporary=opts.collapse_temporary, include_evidence=selection.include_evidence,
                    include_source_text=selection.include_source_text)
            except ValueError as exc:
                raise AgentError('resource_limit' if 'limit' in str(exc) or 'budget' in str(exc) or '32767' in str(exc)
                                 else 'validation_failed', str(exc)) from None
            versions = summary.pop('source_versions')
            artifact = write_artifact(self.store, w, kind, format, data, summary['complete'], versions, source_required)
            return {**artifact, **summary, 'filename': f'lineage-{w[:8]}.xlsx'}
        versions, complete = {}, self._current(w)
        rows = []
        if kind in {'graph', 'impact'}:
            _, graph = self._artifact_graph(w, opts, selection.asset, selection.direction if kind == 'graph' else 'downstream')
            complete &= not graph.truncated
            rows = graph.lineage_rows()
            versions = {e['file_id']: e.get('source_hash', '') for _, _, a in graph.graph.edges(data=True) for e in a['evidence']}
            if kind == 'graph':
                appearance = VisualizationSettings.from_store(self.store, w)
                data = (graph_html(graph, appearance) if format == 'html' else compact(graph_data(graph, appearance))).encode()
        elif kind == 'paths':
            target = self._asset(w, selection.asset)['asset_id']
            graph = self._graph(w, opts, target)
            report = graph.path_report(target, selection.direction, selection.max_paths, opts.max_depth)
            complete &= not report['truncated']
            rows = path_rows(report)
            if format == 'json':
                data = compact(report).encode()
        elif kind in {'original-source', 'source-bundle'}:
            file_ids = [selection.file_id] if kind == 'original-source' else selection.file_ids
            if not file_ids and selection.asset:
                _, graph = self._artifact_graph(w, opts, selection.asset, selection.direction)
                file_ids = sorted({e['file_id'] for _, _, a in graph.graph.edges(data=True) for e in a['evidence']})
                for _, _, attrs in graph.graph.edges(data=True):
                    for evidence in attrs['evidence']:
                        versions.setdefault(evidence['file_id'], set()).add(evidence['source_hash'])
                versions = {fid: sorted(hashes) for fid, hashes in versions.items()}
                complete &= not graph.truncated
            if not file_ids or len(file_ids) > 500 or set(selection.versions) - set(file_ids):
                raise AgentError('validation_failed', 'Select 1–500 authorized source files/versions')
            total = 0
            for fid in file_ids:
                self._source_metadata(w, opts, fid)
                selected = selection.versions.get(fid) or selection.content_hash or versions.get(fid) or self.store.file(fid)['content_hash']
                hashes = selected if isinstance(selected, list) else [selected]
                for digest in hashes:
                    self.store.file(fid, digest)
                    path = checked_path(self.store.home, 'blobs/' + digest)
                    total += path.stat().st_size
                    if total > MAX_BYTES or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                        raise AgentError('resource_limit', 'Source bundle exceeds limit or blob integrity failed')
                versions[fid] = hashes if len(hashes) > 1 else hashes[0]
            data = self.store.original(file_ids[0], versions[file_ids[0]]) if kind == 'original-source' else source_bundle(self.store, file_ids, versions)
            complete = complete if selection.asset else True
        elif kind == 'inventory':
            rows = [{k: f[k] for k in ('file_id', 'relative_path', 'extension', 'file_size', 'encoding', 'content_hash', 'parsing_status')} for f in self.store.files(w)]
        elif kind == 'dictionary':
            rows = data_dictionary(self.store, w, selection.query)
        elif kind == 'columns':
            rows = column_report(self.store, w, self._asset(w, selection.asset)['asset_id'])
        elif kind == 'code-search':
            rows = code_matches(self.store, w, selection.query, opts.max_items + 1)
        elif kind == 'run-comparison':
            data = compact(self._runs_compare(w, opts, selection.before, selection.after)).encode()
        else:
            detailed = opts.model_copy(update={'detail_level': 'detailed'})
            data = compact(self._ai_result(w, detailed, selection.record_id)).encode()
        if kind not in {'graph', 'original-source', 'source-bundle', 'run-comparison', 'ai-result'} and not (kind == 'paths' and format == 'json'):
            complete &= len(rows) <= opts.max_items
            rows = rows[:opts.max_items]
            data = (compact(rows) if format == 'json' else report_csv(rows) if format == 'csv' else report_html(rows)).encode()
        return write_artifact(self.store, w, kind, format, data, complete, versions, source_required)

    def _artifact_read(self, w, opts, artifact_id, offset=0, length=16384):
        if not re.fullmatch('[a-f0-9]{32}', artifact_id):
            raise AgentError('not_found', 'Artifact does not exist')
        directory = _directory(self.store, w)
        manifest = checked_path(self.store.home, (directory / (artifact_id + '.json')).relative_to(self.store.home))
        if not manifest.is_file() or manifest.stat().st_size > 100000:
            raise AgentError('not_found', 'Artifact does not exist in this workspace')
        metadata = json.loads(manifest.read_text(encoding='utf-8'))
        if metadata['workspace_id'] != w or metadata['home_id'] != hashlib.sha256(str(self.store.home).encode()).hexdigest() or metadata['kind'] == 'backup':
            raise AgentError('forbidden', 'Artifact does not belong to this authorized home/workspace')
        if metadata['source_required']:
            self._workspace(w, source=True)
        if type(offset) is not int or type(length) is not int or not 0 <= offset <= metadata['bytes'] or not 1 <= length <= 16384:
            raise AgentError('validation_failed', 'Use valid byte offset and length1–16384')
        path = checked_path(self.store.home, (directory / (artifact_id + '.bin')).relative_to(self.store.home))
        if path.stat().st_size != metadata['bytes'] or metadata['bytes'] > MAX_BYTES:
            raise AgentError('conflict', 'Artifact size changed')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != metadata['sha256']:
                raise AgentError('conflict', 'Artifact integrity failed')
            length = min(length, max(1, (opts.max_chars - 400) * 3 // 4))
            stream.seek(offset)
            data = stream.read(length)
        return {'artifact_id': artifact_id, 'encoding': 'base64', 'offset': offset,
                'data': base64.b64encode(data).decode(), 'next_offset': offset + len(data),
                'bytes': metadata['bytes'], 'sha256': digest, 'complete': offset + len(data) == metadata['bytes'],
                'artifact_complete': metadata['complete']}
