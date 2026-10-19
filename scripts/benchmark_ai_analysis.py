"""Offline semantic gold scoring; --live explicitly opts into bounded synthetic OmniRoute calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile

from dataforge.ai_analysis_models import AnalysisRequest, AnalysisUnit, ValidationContext
from dataforge.ai_reconciliation import normalize_parser_facts
from dataforge.ai_validation import expression_key, validate_project_response
from dataforge.models import canonical, stable_id
from dataforge.parsers.sas import parse_sas
from dataforge.parsers.sql import parse_sql

FIXTURES = Path(__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'ai_analysis'
METRICS = ('table_edges', 'direct_usages', 'derivations', 'value_dependencies', 'row_dependencies')


def score_sets(predicted, expected):
    predicted, expected = set(predicted), set(expected)
    tp, fp, fn = len(predicted & expected), len(predicted - expected), len(expected - predicted)
    return {'tp': tp, 'fp': fp, 'fn': fn, 'predictions': len(predicted), 'expected': len(expected),
            'precision': tp / len(predicted) if predicted else None,
            'recall': tp / len(expected) if expected else None}


def score_case(predicted, expected):
    result = {metric: score_sets({tuple(x) for x in predicted.get(metric, [])},
                                 {tuple(x) for x in expected.get(metric, [])}) for metric in METRICS}
    result['abstention_expected'] = bool(expected.get('abstain'))
    result['abstention_observed'] = bool(predicted.get('abstain'))
    return result


def _cases():
    gold = json.loads((FIXTURES / 'evaluation_gold.json').read_text(encoding='utf-8'))
    for case in gold['cases']:
        path = (FIXTURES / case['source']).resolve()
        if path.parent != FIXTURES.resolve() or path.suffix not in {'.sql', '.sas'}:
            raise ValueError('Gold sources must be checked-in SQL/SAS fixtures')
        source = path.read_text(encoding='utf-8')
        from dataforge.ai_context import _unit_spans
        spans = list(_unit_spans(source, path.suffix))
        expected = {metric: [] for metric in METRICS}
        for metric in METRICS:
            for row in case['expected'][metric]:
                values = list(row)
                values[0] = spans[values[0]][0]
                if metric == 'derivations':
                    values[7] = expression_key(source.strip() if values[7] == '@source' else values[7])
                expected[metric].append(values)
        expected['abstain'] = case['expected']['abstain']
        for job in case.get('jobs', ['benchmark']):
            yield {**case, 'id': case['id'] + (':' + job if case.get('jobs') else ''),
                   'job': job, 'code': source, 'expected': expected, 'unit_count': len(spans)}


def _context(case):
    code = case['code']
    unit = AnalysisUnit(unit_id=case['id'], file_id=case['id'], path=case['source'],
        content_hash=hashlib.sha256(code.encode()).hexdigest(), extension='.' + case['language'],
        job_id=case['job'], first=1, last=code.count('\n') + 1,
        start_offset=0, end_offset=len(code), code=code)
    parsed = parse_sas(code) if case['language'] == 'sas' else parse_sql(code)
    return ValidationContext(unit=unit, workspace_id='synthetic-benchmark', source_text=code, parser_result=parsed)


def prediction_from_facts(facts, *, abstain=False):
    result = {metric: [] for metric in METRICS}
    result['abstain'] = abstain
    for fact in facts:
        if fact.status == 'unresolved':
            result['abstain'] = True
            continue
        start = fact.detail['operation_span'][0]
        if fact.kind == 'table_edge':
            result['table_edges'].append([start, canonical(fact.source), canonical(fact.target)])
        elif fact.kind == 'direct_usage':
            result['direct_usages'].append([start, canonical(fact.table), canonical(fact.column), fact.operation.upper()])
        else:
            target = [start, canonical(fact.table), canonical(fact.column), fact.scope,
                      str(fact.version), fact.branch, fact.ordinal]
            result['derivations'].append([*target, expression_key(fact.expression),
                                           fact.detail['derivation']['category']])
            for item in fact.inputs:
                metric = 'value_dependencies' if item.role == 'value' else 'row_dependencies'
                result[metric].append([*target, canonical(item.table), canonical(item.column),
                                      item.scope, str(item.version), item.role])
    return result


def _live_predictions(cases, *, key_env, max_attempts, max_seconds):
    """Fixed synthetic inputs and one fixed loopback route, with the normal runtime policy/budget gates."""
    if os.environ.get('DATAFORGE_AI_BENCHMARK_LIVE') != '1':
        raise ValueError('Set DATAFORGE_AI_BENCHMARK_LIVE=1 and pass --live to authorize synthetic calls')
    if not re.fullmatch(r'DATAFORGE_[A-Z][A-Z0-9_]*', key_env):
        raise ValueError('Live benchmark requires an application-prefixed credential reference')
    from dataforge.ai_context import AIExecutionContext, plan_ai_units, prepare_analysis
    from dataforge.ai_reconciliation import reconcile_candidates
    from dataforge.connections import RuntimeConnections
    from dataforge.ingestion import Importer
    from dataforge.llm import Profile, invoke_analysis_unit
    from dataforge.store import Store

    connections = RuntimeConnections()
    if not connections.resolve(key_env):
        raise ValueError('Configured benchmark credential is unavailable')
    predictions, completed, processed_units, requests, usage_known, failures = {}, 0, 0, 0, True, 0
    input_tokens, output_tokens = 0, 0
    hybrid_predictions = {}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='gravetrail-ai-gold-') as directory:
        store = Store(directory)
        try:
            for case in cases:
                remaining = max_seconds - (time.monotonic() - started)
                if requests >= max_attempts or remaining < 30:
                    break
                workspace = store.create_workspace('Synthetic semantic benchmark')
                Importer(store, workspace).files([(case['source'], case['code'].encode())], {'.sql', '.sas'})
                profile = Profile(provider='OmniRoute', base_url='http://localhost:20128/v1',
                    model='auto/best-reasoning', key_env=key_env, retries=0, timeout=min(90, remaining),
                    max_tokens=4096, context_chars=200000)
                profile_id = stable_id(workspace, 'benchmark')
                store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)',
                              [profile_id, workspace, 'Synthetic benchmark', profile.model_dump_json()])
                for setting, value in [('default_profile', profile_id), ('llm_chunk_chars', 100000),
                                       ('max_context_chars', 100000), ('default_job', case['job'])]:
                    store.set_setting(workspace, setting, value)
                request = AnalysisRequest(mode='ai', max_provider_attempts=max_attempts - requests,
                                          max_seconds=max(30, min(14400, int(remaining))))
                prepared = prepare_analysis(store, workspace, request)
                plan = plan_ai_units(prepared, max_chars=100000)
                execution = AIExecutionContext(request, connections=connections, settings=prepared.settings,
                    source_hashes={s.file_id: s.content_hash for s in prepared.sources})
                facts, hybrid_facts, abstain, failed = [], [], False, False
                try:
                    if plan.blocked:
                        raise ValueError('Synthetic benchmark plan blocked')
                    parsed = _context(case).parser_result
                    for unit in plan.units:
                        if time.monotonic() - started >= max_seconds:
                            raise TimeoutError('benchmark_deadline')
                        execution.catalog = plan.context_for(unit)
                        attempt = invoke_analysis_unit(store, workspace, unit, 'project_lineage', execution)
                        if attempt is None or attempt.outcome != 'validated' or attempt.result is None:
                            failed = True
                            break
                        usage_known &= attempt.usage_known
                        for name, aliases in [('input_tokens', ('input_tokens', 'prompt_tokens', 'promptTokenCount')),
                                               ('output_tokens', ('output_tokens', 'completion_tokens', 'candidatesTokenCount'))]:
                            value = next((attempt.usage[k] for k in aliases if isinstance(attempt.usage.get(k), int)), None)
                            if value is None:
                                usage_known = False
                            elif name == 'input_tokens':
                                input_tokens += value
                            else:
                                output_tokens += value
                        context = ValidationContext(unit=unit, workspace_id=workspace,
                            source_text=case['code'], settings=prepared.settings, parser_result=parsed)
                        validated = validate_project_response(attempt.result, context)
                        facts.extend(validated.accepted)
                        hybrid_facts.extend(reconcile_candidates(parsed, validated, 'hybrid', context=context).facts)
                        processed_units += 1
                        abstain |= bool(validated.unresolved or validated.rejected
                                        or validated.coverage.status in {'partial', 'unsupported'})
                except (ValueError, OSError, TimeoutError):
                    failed = True
                requests += execution.attempts
                if failed:
                    failures += 1
                    usage_known = False
                    continue
                predictions[case['id']] = prediction_from_facts(facts, abstain=abstain)
                hybrid_predictions[case['id']] = prediction_from_facts(hybrid_facts, abstain=abstain)
                completed += 1
        finally:
            store.close()
    return predictions, {'processed': completed, 'processed_units': processed_units, 'requests': requests,
                         'usage_known': usage_known and bool(requests), 'failed_cases': failures,
                         'hybrid_predictions': hybrid_predictions,
                         'input_tokens': input_tokens if usage_known and requests else None,
                         'output_tokens': output_tokens if usage_known and requests else None}


def _wilson(successes, total):
    if not total:
        return None
    p, z = successes / total, 1.959963984540054
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0, center - half), min(1, center + half)]


def evaluate(*, predictions=None, live=False, key_env='DATAFORGE_OMNIROUTE_API_KEY',
             max_attempts=30, max_seconds=600, case_ids=None):
    if live and predictions is not None:
        raise ValueError('Choose saved predictions or explicit live extraction')
    if not 1 <= max_attempts <= 2000 or not 30 <= max_seconds <= 14400:
        raise ValueError('Invalid benchmark request/time budget')
    cases = list(_cases())
    if live and os.environ.get('DATAFORGE_AI_BENCHMARK_LIVE') != '1':
        raise ValueError('Set DATAFORGE_AI_BENCHMARK_LIVE=1 and pass --live to authorize synthetic calls')
    if live and not case_ids:
        raise ValueError('Live benchmarking requires explicit selected fixture IDs (--cases)')
    if case_ids is not None:
        if not case_ids or set(case_ids) - {case['id'] for case in cases}:
            raise ValueError('Unknown fixture IDs or empty fixture selection')
        cases = [case for case in cases if case['id'] in set(case_ids)]
    total_units = sum(case['unit_count'] for case in cases)
    stats = {'processed': len(cases), 'processed_units': total_units, 'requests': 0,
             'usage_known': False, 'failed_cases': 0, 'input_tokens': None, 'output_tokens': None}
    if live:
        predicted, stats = _live_predictions(cases, key_env=key_env, max_attempts=max_attempts, max_seconds=max_seconds)
        source = 'live_synthetic'
    elif predictions is not None:
        saved = predictions if isinstance(predictions, dict) else json.loads(Path(predictions).read_text(encoding='utf-8'))
        predicted = saved['predictions']
        source = 'saved_predictions'
        stats['processed'] = len(set(predicted) & {case['id'] for case in cases})
        stats['processed_units'] = sum(case['unit_count'] for case in cases if case['id'] in predicted)
    else:
        predicted, source = {}, 'parser_baseline'
        for case in cases:
            context = _context(case)
            facts = normalize_parser_facts(context.parser_result, context)
            predicted[case['id']] = prediction_from_facts(facts,
                abstain=any(d.severity != 'info' for d in context.parser_result.diagnostics))
    languages, scores = {}, {}
    for language in ('sql', 'sas'):
        group = [case for case in cases if case['language'] == language]
        aggregate_predicted, aggregate_expected = defaultdict(set), defaultdict(set)
        for case in group:
            prediction = predicted.get(case['id'], {'abstain': True})
            scores[case['id']] = score_case(prediction, case['expected'])
            for metric in METRICS:
                aggregate_predicted[metric].update((case['id'], *row) for row in prediction.get(metric, []))
                aggregate_expected[metric].update((case['id'], *row) for row in case['expected'][metric])
        metrics = {metric: score_sets(aggregate_predicted[metric], aggregate_expected[metric]) for metric in METRICS}
        for metric in metrics.values():
            metric['precision_wilson95'] = _wilson(metric['tp'], metric['predictions'])
        scripts = len({case['source'] for case in group})
        enough = (live and stats['processed'] == len(cases) and scripts >= 20
                  and metrics['table_edges']['predictions'] >= 100
                  and metrics['value_dependencies']['predictions'] >= 200)
        passed = (enough and metrics['table_edges']['precision'] >= .99
                  and metrics['value_dependencies']['precision'] >= .98)
        languages[language] = {**metrics, 'distinct_scripts': scripts, 'cases': len(group),
            'abstentions_expected': sum(scores[c['id']]['abstention_expected'] for c in group),
            'abstentions_observed': sum(scores[c['id']]['abstention_observed'] for c in group),
            'release_gate': {'status': 'passed' if passed else 'failed' if enough else 'insufficient_evidence',
                'minimum_live_scripts': 20, 'minimum_live_table_predictions': 100,
                'minimum_live_value_predictions': 200}}
    report = {'gold_version': 1, 'split': 'holdout', 'source': source, 'synthetic_sources_only': True,
        'requests': stats['requests'], 'usage_known': stats['usage_known'], 'failed_cases': stats['failed_cases'],
        'unit_coverage': {'processed': stats['processed_units'], 'total': total_units},
        'case_coverage': {'processed': stats['processed'], 'total': len(cases)},
        'input_tokens': stats['input_tokens'], 'output_tokens': stats['output_tokens'],
        'languages': languages, 'cases': scores,
        'limitations': ['Small synthetic holdout; insufficient sample size for live release gates.',
                       'Offline parser results and saved predictions never establish live model precision.',
                       'Abstentions and missing cases reduce coverage; zero predictions have unknown precision.',
                       'Wilson intervals summarize counted predictions; dependencies within scripts may be correlated.']}
    if live:
        report['mode_comparison'] = {
            'parser': evaluate(case_ids=case_ids)['languages'],
            'ai': languages,
            'hybrid': evaluate(case_ids=case_ids, predictions={'predictions': stats['hybrid_predictions']})['languages']}
        report['comparison_requests_shared'] = True
    return report


def evaluate_projects():
    """Offline script-only archive acceptance; manifests stay exclusively inside this scorer."""
    import networkx as nx

    from dataforge.graph import LineageGraph
    from dataforge.ingestion import Importer
    from dataforge.services import analyze
    from dataforge.store import Store

    report = {}
    for language in ('sql', 'sas'):
        archive = FIXTURES.parents[1] / 'sample_data' / f'dataforge_{language}_lineage_test_project.zip'
        with ZipFile(archive) as zipped:
            name = next(n for n in zipped.namelist() if n.endswith('expected/lineage_manifest.json'))
            manifest = json.loads(zipped.read(name))
        expected = {(source, asset['target']) for asset in manifest['assets'] for source in asset['inputs']}
        with tempfile.TemporaryDirectory(prefix='gravetrail-project-gold-') as directory:
            store = Store(directory)
            try:
                workspace = store.create_workspace('Offline synthetic archive acceptance')
                imported = Importer(store, workspace).zip(archive.read_bytes(), {'.' + language})
                analyze(store, workspace)
                graph = LineageGraph(store.assets(workspace), store.edges(workspace)).simplified()
                actual = {(graph.nodes[source]['name'], graph.nodes[target]['name'])
                          for source, target in graph.graph.edges}
                target = next(node for node, data in graph.nodes.items() if data['name'] == 'pub.all_kpis')
                upstream = nx.ancestors(graph.graph, target)
                roots = {graph.nodes[node]['name'] for node in upstream if graph.graph.in_degree(node) == 0}
                expected_names = {asset['target'] for asset in manifest['assets']}
                observed_names = {data['name'] for data in graph.nodes.values()}
                report[language] = {'logical_edges': score_sets(actual, expected),
                    'persistent_tables': len(expected_names & observed_names),
                    'missing_manifest_tables': len(expected_names - observed_names),
                    'upstream_roots': len(roots), 'work_tables': sum(a['temporary'] for a in store.assets(workspace)),
                    'physical_edges': len(store.edges(workspace)), 'imported_scripts': imported.accepted,
                    'requests': 0}
            finally:
                store.close()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--cases', nargs='+', help='Explicit checked-in fixture IDs; required with --live')
    parser.add_argument('--predictions', type=Path)
    parser.add_argument('--key-env', default='DATAFORGE_OMNIROUTE_API_KEY')
    parser.add_argument('--max-attempts', type=int, default=30)
    parser.add_argument('--max-seconds', type=int, default=600)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--project-gold', action='store_true', help='Also score both synthetic ZIPs offline')
    args = parser.parse_args(argv)
    try:
        report = evaluate(predictions=args.predictions, live=args.live, key_env=args.key_env,
                          max_attempts=args.max_attempts, max_seconds=args.max_seconds, case_ids=args.cases)
        if args.project_gold:
            report['offline_project_gold'] = evaluate_projects()
    except (ValueError, OSError, KeyError) as exc:
        # Provider bodies, source, credential values and imported prediction payloads never reach summaries.
        report = {'status': 'failed', 'error_type': type(exc).__name__, 'synthetic_sources_only': True}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 1 if report.get('status') == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
