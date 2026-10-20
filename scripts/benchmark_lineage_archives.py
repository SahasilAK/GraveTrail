"""Score supplied synthetic banking archives; gold files never enter model context.

Offline is the default. Live samples require explicit split, limit, opt-in and bounded
attempt/time ceilings. Reports measure manifest agreement, not database execution.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from dataforge.ai_reconciliation import normalize_parser_facts

if __package__:
    from scripts.benchmark_ai_analysis import _context, _live_predictions, score_sets
else:
    from benchmark_ai_analysis import _context, _live_predictions, score_sets

SPLIT_VERSION = 'scenario-sha256-v1'


def partition(scenario):
    # Keep repeated templates together; per-file random splitting leaks near duplicates.
    digest = hashlib.sha256((SPLIT_VERSION + ':' + scenario).encode()).hexdigest()
    return 'holdout' if int(digest[:8], 16) % 5 == 0 else 'development'


def mask_answer_header(code):
    """Mask leading SQL line comments only, without altering executable text/coordinates."""
    result, header = [], True
    for line in code.splitlines(keepends=True):
        if header and line.lstrip().startswith('--'):
            result.append(re.sub(r'[^\r\n]', ' ', line))
        else:
            result.append(line)
            if line.strip():
                header = False
    return ''.join(result)


def load_archive(path, language, *, split='development', limit=None):
    if language not in {'sql', 'sas'} or split not in {'development', 'holdout', 'all'}:
        raise ValueError('Choose SQL/SAS and an explicit split')
    if limit is not None and not 1 <= limit <= 10000:
        raise ValueError('Invalid script limit')
    path = Path(path)
    if path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('Archive exceeds benchmark size limit')
    with ZipFile(path) as zipped:
        members = zipped.infolist()
        names = [m.filename for m in members]
        if (len(names) != len(set(names)) or len(names) > 15000
                or sum(m.file_size for m in members) > 128 * 1024 * 1024):
            raise ValueError('Duplicate members or archive size limit')
        for member in members:
            name = PurePosixPath(member.filename)
            if (name.is_absolute() or '..' in name.parts or '\\' in member.filename
                    or ':' in member.filename or member.file_size > 16 * 1024 * 1024
                    or (member.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('Unsafe archive member')
        prefix = 'manifest' if language == 'sql' else 'ground_truth'
        def rows(name):
            return list(csv.DictReader(io.StringIO(zipped.read(name).decode('utf-8-sig'))))
        inventory = rows(prefix + '/file_inventory.csv')
        paths = [row['path'] for row in inventory]
        scripts = {n for n in names if n.lower().endswith('.' + language)}
        if len(paths) != len(set(paths)) or set(paths) != scripts:
            raise ValueError('Source inventory does not match archive members')
        expected = defaultdict(set)
        edge_file = 'lineage_edges.csv' if language == 'sql' else 'direct_dependency_edges.csv'
        for row in rows(prefix + '/' + edge_file):
            source_path = row['script_path'] if language == 'sql' else row['file']
            if source_path not in scripts:
                raise ValueError('Edge manifest names an unknown source')
            edge = (row['source_asset'], row['target_asset']) if language == 'sql' else (row['source'], row['target'])
            expected[source_path].add(tuple(value.casefold() for value in edge))
        # Verify every byte before any provider call, including unselected source members.
        for row in inventory:
            raw = zipped.read(row['path'])
            if hashlib.sha256(raw).hexdigest() != row['sha256']:
                raise ValueError('Source checksum mismatch')
        selected = [row for row in inventory if split == 'all' or partition(row['scenario']) == split]
        groups = defaultdict(list)
        for row in selected:
            groups[row['scenario']].append(row)
        for group in groups.values():
            group.sort(key=lambda row: hashlib.sha256(row['path'].encode()).hexdigest())
        # Round-robin scenarios avoids a limit selecting only the first directory.
        selected = [group[i] for i in range(max(map(len, groups.values()), default=0))
                    for _, group in sorted(groups.items()) if i < len(group)]
        if limit:
            selected = selected[:limit]
        cases = []
        for row in selected:
            raw = zipped.read(row['path'])
            code = raw.decode('utf-8-sig')
            if language == 'sql':
                code = mask_answer_header(code)
            dialect = {'ansi': '', 'sqlserver': 'tsql', 'postgresql': 'postgres'}.get(row.get('dialect', ''), row.get('dialect', ''))
            cases.append({'id': row['path'], 'source': row['path'], 'code': code, 'language': language,
                          'job': 'benchmark', 'dialect': dialect, 'scenario': row['scenario'],
                          'expected_edges': expected[row['path']], 'original_sha256': row['sha256'],
                          'evaluation_sha256': hashlib.sha256(code.encode()).hexdigest()})
    return cases, {'name': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                   'scripts': len(inventory), 'selected_scripts': len(cases), 'split': split,
                   'split_version': SPLIT_VERSION, 'selected_scenarios': sorted({case['scenario'] for case in cases}),
                   'answer_headers_masked': language == 'sql'}


def _table_pairs(prediction):
    # Supplied manifests are per-script pairs, without operation/version/column labels.
    return {(s.casefold(), t.casefold()) for _, s, t in prediction.get('table_edges', [])
            if s.casefold() != t.casefold()}


def evaluate_archive(path, language, *, split='development', limit=None, live=False,
                     key_env='DATAFORGE_OMNIROUTE_API_KEY', max_attempts=40, max_seconds=600):
    if live and os.environ.get('DATAFORGE_AI_BENCHMARK_LIVE') != '1':
        raise ValueError('Live benchmark needs explicit environment opt-in')
    if live and (split == 'all' or limit is None):
        raise ValueError('Live benchmark requires an explicit development/holdout split and script limit')
    if not 1 <= max_attempts <= 2000 or not 30 <= max_seconds <= 14400:
        raise ValueError('Invalid benchmark attempt/time ceilings')
    cases, inventory = load_archive(path, language, split=split, limit=limit)
    if live and not cases:
        raise ValueError('Selected live split contains no scripts')
    started = time.monotonic()
    parser, parser_failures = {}, {}
    for case in cases:
        context = _context(case)
        facts = normalize_parser_facts(context.parser_result, context)
        parser[case['id']] = {(f.source.casefold(), f.target.casefold()) for f in facts
                             if f.kind == 'table_edge' and f.source.casefold() != f.target.casefold()}
        parser_failures[case['id']] = [d.message for d in context.parser_result.diagnostics]
    modes = {'parser': parser}
    abstentions = {'parser': {key: bool(value) for key, value in parser_failures.items()}}
    stats = {'requests': 0, 'usage_known': False, 'input_tokens': None, 'output_tokens': None,
             'processed': len(cases), 'failed_cases': 0}
    if live:
        predictions, stats = _live_predictions(cases, key_env=key_env,
                                               max_attempts=max_attempts, max_seconds=max_seconds, max_tokens=8192)
        modes['ai'] = {key: _table_pairs(value) for key, value in predictions.items()}
        modes['hybrid'] = {key: _table_pairs(value) for key, value in stats['hybrid_predictions'].items()}
        abstentions['ai'] = {key: value.get('abstain', False) for key, value in predictions.items()}
        abstentions['hybrid'] = {key: value.get('abstain', False) for key, value in stats['hybrid_predictions'].items()}
    results = {}
    for mode, predictions in modes.items():
        actual, expected = set(), set()
        details = []
        for case in cases:
            key = case['id']
            observed, gold = predictions.get(key, set()), case['expected_edges']
            actual.update((key, *pair) for pair in observed)
            expected.update((key, *pair) for pair in gold)
            details.append({'source': key, 'scenario': case['scenario'], 'processed': key in predictions,
                            'original_sha256': case['original_sha256'], 'evaluation_sha256': case['evaluation_sha256'],
                            'false_positives': sorted(observed - gold), 'omissions': sorted(gold - observed),
                            'diagnostics': parser_failures[key] if mode == 'parser' else [],
                            'abstained': abstentions[mode].get(key, True),
                            'failure': stats.get('failures_by_case', {}).get(key) if mode != 'parser' else None})
        results[mode] = {'table_edges': score_sets(actual, expected), 'processed_scripts': len(predictions), 'cases': details}
    return {'archive': inventory, 'language': language, 'source': 'live_archive' if live else 'parser_baseline',
            'requests': stats['requests'], 'usage_known': stats['usage_known'],
            'input_tokens': stats['input_tokens'], 'output_tokens': stats['output_tokens'],
            'failed_cases': stats['failed_cases'], 'modes': results, 'column_gold': 'unavailable',
            'resolved_models': stats.get('resolved_models', []),
            'receipts': stats.get('receipts', []),
            'release_gate': 'insufficient_evidence', 'elapsed_seconds': round(time.monotonic() - started, 3),
            'limitations': ['Table manifest agreement only; no independent column/role/scope/version labels in supplied archives.',
                            'Fixture manifests describe intended dependencies; source adjudication is required for disputed edges.',
                            'Repeated templates are grouped by scenario; script predictions remain correlated.',
                            'Offline and incomplete live samples cannot qualify live accuracy; zero predictions have unknown precision.',
                            'Hybrid reuses the same extraction calls; no independent reviewer or database execution.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--language', required=True, choices=['sql', 'sas'])
    parser.add_argument('--split', default='development', choices=['development', 'holdout', 'all'])
    parser.add_argument('--limit', type=int)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--key-env', default='DATAFORGE_OMNIROUTE_API_KEY')
    parser.add_argument('--max-attempts', type=int, default=40)
    parser.add_argument('--max-seconds', type=int, default=600)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    report = evaluate_archive(args.archive, args.language, split=args.split, limit=args.limit,
                              live=args.live, key_env=args.key_env, max_attempts=args.max_attempts,
                              max_seconds=args.max_seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('language', 'source', 'requests', 'release_gate', 'elapsed_seconds')}))
    return int(args.live and report['modes']['ai']['processed_scripts'] < report['archive']['selected_scripts'])


if __name__ == '__main__':
    raise SystemExit(main())
