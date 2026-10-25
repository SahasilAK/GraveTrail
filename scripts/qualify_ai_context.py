"""Offline golden transport qualification. Never calls a live model."""
from __future__ import annotations

import argparse
import json
import tempfile
import time
import tracemalloc

import httpx

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_analysis_store import load_file_extractions, load_file_parts
from dataforge.ai_budget import request_budget
from dataforge.ai_linking import build_operation_graph
from dataforge.analysis_service import preview_analysis, run_analysis
from dataforge.ingestion import Importer
from dataforge.llm import Profile
from dataforge.model_capabilities import ModelCapabilities, bind_capabilities
from dataforge.store import Store


def golden_project(family, count, *, oversized=True, duplicate_writes=False):
    """Expected relationships come from this generator, never from a parser."""
    files, gold = [], {}
    for i in range(count):
        source, target = ('raw.input' if i == 0 else f't{i-1}'), f't{i}'
        if family == 'sas':
            code = f'data {target}; set {source}; id=id; run;'
        elif family == 'dbt':
            call = "{{ source('raw', 'input') }}" if i == 0 else "{{ ref('t" + str(i-1) + "') }}"
            code = 'select id from ' + call
        else:
            code = f'create table {target} as select id from {source};'
        if i == 0 and oversized:
            code = '/*' + ' known padding 界 ' * 1500 + '*/\n' + code
        path = ('models/' if family == 'dbt' else '') + target + ('.sas' if family == 'sas' else '.sql')
        gold[path] = {'source': source, 'target': target, 'code': code, 'ordinal': i}
        files.append((path, code.encode()))
    if duplicate_writes and family in {'sql', 'sas'}:
        for name in ('duplicate_a', 'duplicate_b'):
            source, target = 'raw.' + name, 'duplicate'
            code = (f'data {target}; set {source}; id=id; run;' if family == 'sas' else
                    f'create table {target} as select id from {source};')
            path = name + ('.sas' if family == 'sas' else '.sql')
            gold[path] = {'source': source, 'target': target, 'code': code, 'ordinal': count}
            files.append((path, code.encode()))
    if family == 'dbt':
        files.extend([('dbt_project.yml', b'name: gold\nversion: 1.0'),
                      ('models/schema.yml', b'version: 2\nsources:\n  - name: raw\n    tables:\n      - name: input')])
    return files, gold


def golden_response(item, gold, *, omit=False):
    part, path = item['part'], item['path']
    result = {'part_id': part['part_id'], 'coverage': 'complete'}
    if path not in gold:
        result['coverage'] = 'no_operations'
        return result
    expected = gold[path]
    source, target, code = expected['source'], expected['target'], expected['code']
    expression = code.rfind('id') if path.endswith('.sas') else code.rfind('select id') + 7
    # Only the source range containing the transformation owns the golden fact.
    if not part['start_offset'] <= expression < expression + 2 <= part['end_offset'] or omit:
        result['coverage'] = 'complete'  # Deliberate semantic omission can still claim completeness.
        return result
    ref = {k: part[k] for k in ('file_id', 'content_hash', 'start_offset', 'end_offset')}
    result['operations'] = [{'operation_id': target, 'kind': 'CREATE', 'evidence': [ref],
        'reads': [{'name': source}], 'writes': [{'name': target}],
        'derivations': [{'fact_id': target + ':id', 'target_table': target, 'target_column': 'id',
            'inputs': [{'table': source, 'column': 'id', 'role': 'value'},
                       {'table': source, 'column': 'id', 'role': 'row_filter'}],
            'expression': {**ref, 'start_offset': expression, 'end_offset': expression + 2},
            'evidence': [ref]}]}]
    return result


def score(predicted, expected):
    predicted, expected = set(predicted), set(expected)
    correct = len(predicted & expected)
    return {'precision': correct / len(predicted) if predicted else 0.,
            'recall': correct / len(expected) if expected else 1.,
            'false_positive': len(predicted - expected), 'missing': len(expected - predicted), 'correct': correct}


def evaluate(*, family='sql', files=1000, context_tokens=70000, output_tokens=8000, interrupt=True,
             reverse=False, omit=False, oversized=True, duplicate_writes=False):
    started = time.monotonic()
    tracemalloc.start()
    entries, gold = golden_project(family, files, oversized=oversized, duplicate_writes=duplicate_writes)
    if reverse:
        entries.reverse()
    with tempfile.TemporaryDirectory(prefix='gravetrail-golden-') as home:
        store = Store(home)
        workspace = store.create_workspace('golden ' + family)
        Importer(store, workspace).files(entries, {'.sql', '.sas'} if family != 'dbt' else set(),
                                         source_kind='dbt' if family == 'dbt' else 'files')
        profile = Profile(provider='OpenAI compatible', base_url='http://localhost:1234', model='golden-mock',
                          retries=0, max_tokens=output_tokens, source_limit_policy='token_capacity')
        profile.model_capabilities = bind_capabilities(ModelCapabilities(context_tokens=context_tokens,
            output_tokens=output_tokens, source='manual'), profile)
        store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', workspace, 'gold', profile.model_dump_json()])
        store.set_setting(workspace, 'default_profile', 'p')
        request = AnalysisRequest(mode='ai')
        preview = preview_analysis(store, workspace, request)
        assert preview['valid'], preview['blocked']
        sent, ranges, requests, max_input = [], [], 0, 0
        cancel, armed = [False], [interrupt]
        def provider(http_request):
            nonlocal requests, max_input
            payload = json.loads(http_request.content)
            context = json.loads(payload['messages'][-1]['content'])
            budget = request_budget(profile, json.dumps(payload, ensure_ascii=False, separators=(',', ':')), output_tokens)
            assert budget.fits, budget.reasons
            max_input = max(max_input, budget.input_count)
            requests += 1
            results = []
            for item in context['items']:
                part = item['part']
                sent.append(part['part_id'])
                if part['work_kind'] == 'extraction':
                    ranges.append((part['file_id'], part['start_offset'], part['end_offset']))
                results.append(golden_response(item, gold, omit=omit and item['path'].rsplit('/', 1)[-1] in {'t1.sql', 't1.sas'}))
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'items': results})}, 'finish_reason': 'stop'}]})
        def progress(fraction, stage):
            if armed[0] and 'Waiting for AI' in stage and requests >= max(1, preview['estimated_requests'] // 2):
                # Cancel before the next physical attempt; already saved results survive.
                cancel[0], armed[0] = True, False
        result = run_analysis(store, workspace, request, transport=httpx.MockTransport(provider),
                              cancelled=lambda: cancel[0], progress=progress)
        resumed = result.status == 'cancelled'
        if resumed:
            store.close()
            store = Store(home)
            cancel[0] = False
            result = run_analysis(store, workspace, AnalysisRequest(mode='ai', resume_run_id=result.run_id),
                                  transport=httpx.MockTransport(provider))
        assert result.status == 'committed', result.reasons
        saved = load_file_extractions(store, workspace, result.run_id)
        saved_parts = [(p, r) for p, r in load_file_parts(store, workspace, result.run_id) if p.work_kind == 'extraction']
        assert len({pid for pid in sent}) == len(sent), 'Repeated completed work'
        for source in store.files(workspace):
            spans = sorted((p.start_offset, p.end_offset) for p, _ in saved_parts if p.file_id == source['file_id'])
            assert spans[0][0] == 0 and spans[-1][1] == len(store.snapshot_content(source))
            assert all(a[1] == b[0] for a, b in zip(spans, spans[1:]))
        graph = build_operation_graph(saved)
        actual_tables = {(r.name, w.name) for file in saved for op in file.operations for r in op.reads for w in op.writes}
        expected_tables = {(g['source'], g['target']) for g in gold.values()}
        actual_columns = {(i.table, i.column, d.target_table, d.target_column, i.role) for file in saved
                          for op in file.operations for d in op.derivations for i in d.inputs}
        expected_columns = {(g['source'], 'id', g['target'], 'id', role) for g in gold.values() for role in ('value', 'row_filter')}
        actual_files = {(graph.nodes[a]['file_id'], graph.nodes[b]['file_id']) for resource, data in graph.nodes(data=True)
            if data['kind'] == 'resource' for a in graph.predecessors(resource) for b in graph.successors(resource)}
        by_target = {g['target']: path for path, g in gold.items()}
        file_ids = {m['relative_path']: m['file_id'] for m in store.files(workspace)}
        expected_files = {(file_ids[by_target[g['source']]], file_ids[path]) for path, g in gold.items() if g['source'] in by_target}
        metrics = {'table': score(actual_tables, expected_tables), 'column': score(actual_columns, expected_columns),
                   'file': score(actual_files, expected_files)}
        duplicate_boundaries = [n for n, data in graph.nodes(data=True) if data['kind'] == 'resource' and data.get('name') == 'duplicate' and data.get('unresolved')]
        if duplicate_writes and family in {'sql', 'sas'}:
            assert len(duplicate_boundaries) == 2
        if not omit:
            assert all(m['false_positive'] == m['missing'] == 0 for m in metrics.values()), metrics
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        report = {'family': family, 'source_files': len(entries), 'semantic_files': files, 'parts': len(saved_parts),
            'requests': requests, 'estimated_input_tokens': preview['estimated_input_tokens'],
            'actual_provider_tokens': None, 'maximum_sent_input_tokens': max_input, 'context_tokens': context_tokens,
            'reserved_output_tokens': result.counts['reserved_output_tokens'], 'elapsed_seconds': time.monotonic() - started,
            'peak_python_bytes': peak, 'saved_result_bytes': sum(len(f.model_dump_json().encode()) for f in saved),
            'processed_coverage': 1., 'semantic_metrics': metrics, 'interrupted_and_resumed': resumed,
            'evidence_validity': 1., 'unresolved_rate': sum(bool(f.unresolved) for f in saved) / len(saved),
            'cost_per_correct_relationship': None, 'qualification': 'deterministic_mock', 'live_model_accuracy': 'pending'}
        report['duplicate_writer_boundaries'] = len(duplicate_boundaries)
        store.close()
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--files', type=int, default=1000)
    parser.add_argument('--family', choices=['sql', 'sas', 'dbt', 'all'], default='all')
    parser.add_argument('--context-tokens', type=int, default=70000)
    parser.add_argument('--output-tokens', type=int, default=8000)
    args = parser.parse_args()
    families = ('sql', 'sas', 'dbt') if args.family == 'all' else (args.family,)
    for family in families:
        print(json.dumps(evaluate(family=family, files=args.files, context_tokens=args.context_tokens,
                                 output_tokens=args.output_tokens, duplicate_writes=True)), flush=True)


if __name__ == '__main__':
    main()
