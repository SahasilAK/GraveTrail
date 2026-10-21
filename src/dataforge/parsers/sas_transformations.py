"""Bounded DATA-step derivations; unknown SAS runtime behavior stays explicit."""
from __future__ import annotations

import re
from typing import Any

from dataforge.models import Diagnostic, Operation

NAME = r'[A-Za-z_]\w*'
STRING = r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\""
ASSIGNMENT = re.compile(rf'\s*({NAME})\s*=\s*(.+?)\s*;?$', re.S)
SUPPORTED_FUNCTIONS = frozenset({
    'sum', 'mean', 'min', 'max', 'coalesce', 'coalescec', 'abs', 'round', 'floor', 'ceil', 'int',
    'mod', 'sqrt', 'log', 'log10', 'exp', 'sign', 'n', 'nmiss', 'cmiss', 'missing',
    'length', 'lengthn', 'strip', 'trim', 'left', 'right', 'upcase', 'lowcase', 'propcase',
    'substr', 'substrn', 'compress', 'compbl', 'cat', 'cats', 'catt', 'catx', 'tranwrd', 'translate',
})


def derivation(table: str, column: str, expression: str, *, scope: str = '', version: str = '',
               inputs: list[dict[str, str]] | None = None, category: str = 'projection',
               coverage: list[str] | None = None, ordinal: int = 0) -> dict[str, Any]:
    """Build one DATA-step derivation record with its status from coverage.

    Args:
        table: Target dataset name.
        column: Target column name.
        expression: Original SAS expression or statement evidence.
        scope: Scope identifier for the generated variable version.
        version: Target variable version identifier.
        inputs: Source column dependencies.
        category: Derivation category label.
        coverage: Unresolved reasons attached to the record.
        ordinal: Position of the record within the operation.

    Returns:
        Derivation mapping in the persisted parser result shape.
    """
    coverage = coverage or []
    return {'target_table': table, 'target_column': column, 'scope': scope,
            'target_version': version, 'expression': expression, 'category': category,
            'status': 'unresolved' if coverage else 'verified', 'inputs': inputs or [],
            'coverage': coverage, 'branch': 0, 'ordinal': ordinal}


def dependency(table: str, column: str, *, scope: str = '', version: str = '') -> dict[str, str]:
    """Build one source-column dependency record.

    Args:
        table: Source dataset name.
        column: Source column name.
        scope: Scope containing the source variable version.
        version: Source variable version identifier.

    Returns:
        Dependency mapping with the value role.
    """
    return {'table': table, 'column': column, 'role': 'value', 'scope': scope, 'version': version}


def _names(value: str) -> list[str]:
    """Parse and normalize a simple whitespace-separated SAS variable list.

    Args:
        value: List text from a KEEP or DROP option.

    Returns:
        Case-folded variable names.

    Raises:
        ValueError: If the list contains unsupported names or range syntax.
    """
    names = value.strip().split()
    if not names or any(not re.fullmatch(NAME, name) or name.casefold() in {
            '_all_', '_numeric_', '_character_'} for name in names):
        raise ValueError('SAS variable lists/ranges require a known schema')
    return [name.casefold() for name in names]


def _renames(value: str) -> dict[str, str]:
    """Parse a plain SAS old-name to new-name mapping.

    Args:
        value: RENAME option text.

    Returns:
        Case-folded source-to-target column mapping.

    Raises:
        ValueError: If the mapping is empty, malformed, or conflicting.
    """
    pairs = list(re.finditer(rf'({NAME})\s*=\s*({NAME})', value))
    remainder = re.sub(rf'{NAME}\s*=\s*{NAME}', '', value).strip()
    if not pairs or remainder:
        raise ValueError('SAS RENAME is not a plain variable mapping')
    mapping = {m[1].casefold(): m[2].casefold() for m in pairs}
    if len(mapping) != len(pairs) or len(set(mapping.values())) != len(mapping):
        raise ValueError('SAS RENAME has conflicting variable mappings')
    return mapping


def _dataset(statement: str, keyword: str) -> dict[str, list[str] | dict[str, str] | None]:
    """Read one dataset and its supported KEEP, DROP, and RENAME options.

    Args:
        statement: DATA or SET statement to inspect.
        keyword: Expected statement keyword.

    Returns:
        Parsed options mapping with ``keep``, ``drop``, and ``rename`` entries.

    Raises:
        ValueError: If the dataset or its options use unsupported syntax.
    """
    match = re.fullmatch(rf'\s*{keyword}\s+({NAME}(?:\.{NAME})?)\s*(.*?)\s*;?', statement, re.I | re.S)
    if not match:
        raise ValueError('SAS column transformations require a single plain dataset')
    tail = match[2].strip().rstrip(';').strip()
    options = {'keep': None, 'drop': [], 'rename': {}}
    if not tail:
        return options
    if not (tail.startswith('(') and tail.endswith(')')):
        raise ValueError('SAS column transformations require a single dataset with simple options')
    tail = tail[1:-1].strip()
    while tail:
        key = re.match(r'(keep|drop|rename)\s*=\s*', tail, re.I)
        if not key:
            raise ValueError('Unsupported SAS dataset option in column transformations')
        name = key[1].casefold()
        tail = tail[key.end():]
        if name == 'rename':
            mapping = re.match(r'\(([^()]*)\)', tail)
            if not mapping:
                raise ValueError('SAS RENAME option requires a plain mapping')
            options[name] = _renames(mapping[1])
            tail = tail[mapping.end():].strip()
        else:
            value = re.split(r'\b(?:keep|drop|rename)\s*=', tail, maxsplit=1, flags=re.I)[0]
            options[name] = _names(value)
            tail = tail[len(value):].strip()
    return options


def _expression_inputs(expression: str, source: str, state: dict[str, dict[str, Any]],
                       source_columns: dict[str, str], known_source: bool,
                       unavailable: set[str]) -> tuple[list[dict[str, str]], list[str]]:
    """Resolve referenced variables to known inputs or coverage diagnostics.

    Args:
        expression: SAS assignment expression.
        source: Single source dataset name, if known.
        state: Current DATA-step variable versions.
        source_columns: Known output-to-source column mapping.
        known_source: Whether the source schema is complete for this step.
        unavailable: Names not available as pass-through source columns.

    Returns:
        Dependency records and unresolved coverage messages.
    """
    stripped = re.sub(STRING, ' ', expression)
    # Date/time literals and hex/format notation need their own grammar; do not guess.
    if (re.search(rf'(?:{STRING})\s*[A-Za-z_]', expression) or re.search(r'[&%\[\]{}:]', stripped)
            or re.search(rf'\b{NAME}\.|\.{NAME}\b', stripped)):
        return [], ['Unsupported or dynamic SAS assignment expression']
    tokens = re.finditer(rf'{NAME}|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', stripped)
    inputs, coverage = [], []
    for token in tokens:
        name = token[0].casefold()
        if name[0].isdigit() or name.startswith('.'):
            continue
        if name in {'and', 'or', 'not', 'eq', 'ne', 'gt', 'lt', 'ge', 'le', 'in'}:
            continue
        if name in {'_n_', '_error_'}:
            coverage.append('SAS automatic runtime variable is unresolved')
            continue
        if stripped[token.end():].lstrip().startswith('('):
            if name not in SUPPORTED_FUNCTIONS:
                coverage.append(f'SAS function {token[0]} has unsupported or runtime semantics')
            continue
        if name in state:
            item = state[name]
            inputs.append(dependency(item['target_table'], name, scope=item['scope'],
                                     version=item['target_version']))
            if item['status'] == 'unresolved':
                coverage.append('SAS assignment depends on an unresolved variable version')
        elif source and name not in unavailable and (not known_source or name in source_columns):
            inputs.append(dependency(source, source_columns.get(name, name)))
        else:
            coverage.append(f'SAS variable {token[0]} has no established input')
    if re.search(r'\bof\b', stripped, re.I):
        coverage.append('SAS variable-list function is unresolved')
    return list({tuple(i.items()): i for i in inputs}.values()), list(dict.fromkeys(coverage))


def data_step_derivations(operation: Operation, block: list[tuple[str, int, int, str, int, int]]) -> tuple[list[dict[str, Any]], list[Diagnostic]]:
    """Build ordered DATA-step variable versions and final columns conservatively.

    Args:
        operation: Parsed SAS DATA operation to describe.
        block: Buffered source statements with line and character offsets.

    Returns:
        Derivation records and diagnostics for unsupported or incomplete cases.
    """
    targets = [t.name for t in operation.targets if t.kind == 'table']
    if not targets:
        return [], []
    statements = [(entry[0], entry[3]) for entry in block]
    body = statements[1:]
    coverage = []
    sets = [clean for _, clean in body if re.match(r'\s*set\b', clean, re.I)]
    if len(sets) > 1 or len(operation.sources) > 1:
        coverage.append('Multiple SAS input datasets/SET statements are unresolved for column transformations')
    if sets:
        before_set = body[:next(index for index, (_, clean) in enumerate(body) if clean == sets[0])]
        if any(ASSIGNMENT.fullmatch(clean) for _, clean in before_set):
            coverage.append('SAS assignment before SET may depend on retained values; column transformations unresolved')
    for _, clean in body:
        plain = re.sub(STRING, ' ', clean)
        if re.match(r'\s*(merge|update|modify|by|array|do|end|if|else|retain|output|input|infile|'
                    r'call|where|delete|stop|link|goto|select|when|otherwise)\b', plain, re.I):
            coverage.append('SAS procedural/MERGE BY/array/loop/conditional retention transformations are unresolved')
        elif not (ASSIGNMENT.fullmatch(clean) or re.match(r'\s*(set|keep|drop|rename|run)\b', clean, re.I)):
            coverage.append('Unsupported SAS DATA statement in column transformations')
    try:
        output_options = _dataset(statements[0][1], 'data')
        source_options = _dataset(sets[0], 'set') if sets else {'keep': None, 'drop': [], 'rename': {}}
        if any(old in source_options['drop'] or (
                source_options['keep'] is not None and old not in source_options['keep'])
                for old in source_options['rename']):
            coverage.append('SAS input RENAME references a variable removed by input KEEP/DROP')
        if source_options['keep'] is not None:
            input_names = [source_options['rename'].get(name, name) for name in source_options['keep']
                           if name not in source_options['drop']]
            if len(set(input_names)) != len(input_names):
                coverage.append('SAS input RENAME has conflicting column names')
    except ValueError as error:
        coverage.append(str(error))
        output_options = source_options = {'keep': None, 'drop': [], 'rename': {}}
    if coverage:
        message = '; '.join(dict.fromkeys(coverage))
        return ([derivation(target, '', operation.code, category='unsupported', coverage=[message])
                 for target in targets], [Diagnostic(message, operation.start)])

    source = operation.sources[0].name if sets and operation.sources else ''
    source_columns = {source_options['rename'].get(n, n): n for n in source_options['keep'] or []
                      if n not in source_options['drop']}
    known_source = source_options['keep'] is not None
    if not known_source:
        source_columns.update({new: old for old, new in source_options['rename'].items()
                               if old not in source_options['drop']})
    dropped_input = {source_options['rename'].get(n, n) for n in source_options['drop']}
    unavailable = dropped_input | {old for old, new in source_options['rename'].items() if old != new}
    state, versions, steps = {}, {}, []
    keep, drop, rename = None, set(), {}
    for body_index, (raw, clean) in enumerate(body):
        if match := re.match(r'\s*(keep|drop|rename)\s+(.+?)\s*;?$', clean, re.I | re.S):
            try:
                if match[1].casefold() == 'rename':
                    rename.update(_renames(match[2].rstrip(';')))
                elif match[1].casefold() == 'keep':
                    keep = set(_names(match[2].rstrip(';')))
                else:
                    drop.update(_names(match[2].rstrip(';')))
            except ValueError as error:
                coverage.append(str(error))
            continue
        assignment = ASSIGNMENT.fullmatch(clean)
        if not assignment:
            continue
        name, expression = assignment[1].casefold(), assignment[2].rstrip(';')
        inputs, errors = _expression_inputs(expression, source, state, source_columns, known_source, unavailable)
        macro_text = re.sub(r"'(?:''|[^'])*'|/\*.*?\*/", ' ', raw, flags=re.S)
        if re.search(r'[&%][A-Za-z_]', macro_text):
            errors.append('SAS macro-expanded assignment has unresolved original expression')
        versions[name] = versions.get(name, 0) + 1
        step = derivation(targets[0], name, raw, scope='data-step', version=str(versions[name]),
                          inputs=inputs, category='expression' if inputs or errors else 'constant',
                          coverage=errors, ordinal=len(steps))
        step['_expression_offset'] = block[body_index + 1][4] - block[0][4]
        state[name] = step
        steps.append(step)

    candidates = set(source_columns) | set(state) | set(rename) | set(output_options['rename'])
    # Explicit KEEP establishes only the requested output columns, never the whole source schema.
    if keep is not None:
        candidates = keep
    if output_options['keep'] is not None:
        candidates = set(output_options['keep']) if keep is None else candidates & set(output_options['keep'])
    candidates -= drop | set(output_options['drop'])
    rename.update(output_options['rename'])
    output_names = [rename.get(name, name) for name in candidates]
    if len(set(output_names)) != len(output_names):
        coverage.append('SAS output RENAME has conflicting column names')
    for target in targets:
        for name in sorted(candidates):
            errors = list(coverage)
            if name in state:
                item = state[name]
                inputs = [dependency(item['target_table'], name, scope=item['scope'], version=item['target_version'])]
                errors.extend(item['coverage'])
            elif source and (not known_source or name in source_columns) and name not in unavailable:
                inputs = [dependency(source, source_columns.get(name, name))]
            else:
                inputs = []
                errors.append('SAS output variable has no established input')
            steps.append(derivation(target, rename.get(name, name), operation.code, inputs=inputs,
                                    coverage=errors, ordinal=len(steps)))
        if source and not known_source and keep is None and output_options['keep'] is None:
            steps.append(derivation(target, '', operation.code, category='wildcard',
                                    coverage=['SAS SET passthrough columns require an explicit KEEP or known schema']))
        if coverage:
            steps.append(derivation(target, '', operation.code, category='unsupported', coverage=coverage))
    return steps, [Diagnostic(message, operation.start) for message in coverage]


def proc_derivations(operation: Operation) -> list[dict[str, Any]]:
    """Mark PROC output transformations unsupported for each target dataset.

    Args:
        operation: Parsed PROC operation.

    Returns:
        Unresolved derivation records for the operation's targets.
    """
    return [derivation(target.name, '', operation.code, category='unsupported',
                       coverage=[f'{operation.kind} column transformations are unsupported'])
            for target in operation.targets]
