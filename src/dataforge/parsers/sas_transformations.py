"""Bounded DATA-step derivations; unknown SAS runtime behavior stays explicit."""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from dataforge.models import AssetRef, Diagnostic, Operation

NAME = r'[A-Za-z_]\w*'
STRING = r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\""
ASSIGNMENT = re.compile(rf'\s*({NAME})\s*=\s*(.+?)\s*;?$', re.S)
ROW_FILTER = re.compile(r'\s*(if|where)\s+(.+?)\s*;?$', re.I | re.S)
LENGTH = re.compile(rf'\s*length\s+((?:{NAME}\s+\$?\d+\s*)+);?$', re.I)
RETAIN_LITERAL = re.compile(rf'\s*retain\s+({NAME})\s+(-?\d+(?:\.\d+)?)\s*;?$', re.I)
IF_ASSIGNMENT = re.compile(rf'\s*if\s+(.+?)\s+then\s+({NAME})\s*=\s*(.+?)\s*;?$', re.I | re.S)
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


def passthrough(target, source, expression, inputs, coverage, *, exclude=(), ordinal=0):
    record = derivation(target, '', expression, category='wildcard',
                        inputs=[dependency(source, '*'), *inputs],
                        coverage=['SAS passthrough requires a complete input layout', *coverage], ordinal=ordinal)
    return record | {'wildcard_safe': True, 'scoped_wildcard': True, 'sas_passthrough': True,
                     'sas_exclude': sorted(exclude)}


def inline_data(operation, header, body):
    """Bind a plain INPUT list to retained inline data."""
    if (operation.sources or not re.fullmatch(rf'\s*data\s+{NAME}(?:\.{NAME})?\s*;?', header, re.I)
            or not any(re.fullmatch(r'(?:datalines|cards)4?\s*;', s, re.I) for _, s in body)):
        return []
    inputs = [raw for raw, clean in body if re.match(r'\s*input\b', clean, re.I)]
    if len(inputs) != 1 or not all(re.match(
            r'\s*(?:length|format|input|infile\s+datalines\b|datalines4?|cards4?|run)\b', clean, re.I)
            for _, clean in body):
        return []
    input_list = re.sub(r'^\s*input\s+', '', inputs[0], flags=re.I).strip().rstrip(';')
    field = rf'({NAME})(?:\s+(?::\$?(?:{NAME}|\d+)\.(?:\d+)?|\$(?:\d+\.)?))?'
    if not re.fullmatch(rf'{field}(?:\s+{field})*\s*', input_list):
        return []
    names = [match[1].casefold() for match in re.finditer(field, input_list)]
    if len(set(names)) != len(names):
        return []
    for _, clean in body:
        if re.match(r'\s*length\b', clean, re.I):
            length = LENGTH.fullmatch(clean)
            if not length or any(name.casefold() not in names for name in re.findall(NAME, length[1])):
                return []
        if re.match(r'\s*format\b', clean, re.I):
            formats = re.sub(r'^\s*format\s+', '', clean, flags=re.I).strip().rstrip(';')
            pair = rf'({NAME})\s+\$?(?:{NAME}|\d+)\.\d*'
            if (not re.fullmatch(rf'{pair}(?:\s+{pair})*\s*', formats)
                    or any(match[1].casefold() not in names for match in re.finditer(pair, formats))):
                return []
    return [derivation(target.name, name, inputs[0], category='inline_data', ordinal=position)
            for target in operation.targets if target.kind == 'table'
            for position, name in enumerate(names)]


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


def option_end(text: str) -> int:
    """Return the end of a balanced parenthesized SAS dataset option."""
    depth = 0
    for token in re.finditer(rf'{STRING}|[()]', text):
        if token[0] == '(':
            depth += 1
        elif token[0] == ')':
            depth -= 1
            if not depth:
                return token.end()
    raise ValueError('Unbalanced SAS dataset options')


def without_dataset_options(text: str) -> str:
    """Remove balanced option clauses before discovering dataset names."""
    parts = []
    while (start := text.find('(')) != -1:
        parts.append(text[:start])
        text = text[start + option_end(text[start:]):]
    return ' '.join([*parts, text])


def stack_inputs(statement, sources, targets):
    """Recognize one concatenating SET with optional IN= indicators."""
    dataset = rf'{NAME}(?:\.{NAME})?'
    entry = rf'{dataset}(?:\s*\(\s*in\s*=\s*({NAME})\s*\))?'
    text = re.sub(r'^\s*set\s+', '', statement, flags=re.I).strip().rstrip(';').strip()
    if not re.fullmatch(rf'{entry}(?:\s+{entry})+', text, re.I):
        return None
    entries = list(re.finditer(entry, text, re.I))
    flags = [(match[1].casefold(), source) for match, source in zip(entries, sources) if match[1]]
    if (len(entries) != len(sources) or len({name for name, _ in flags}) != len(flags)
            or any(source.casefold() in {target.casefold() for target in targets} for source in sources)):
        return None
    return flags


def merge_inputs(body, sources, targets):
    """Recognize an initial MERGE/BY with plain datasets and IN=/RENAME= options."""
    if (len(body) < 2 or len(sources) < 2 or len(targets) != 1
            or any(targets[0].casefold() == source.casefold() for source in sources)):
        return None
    merge = re.fullmatch(r'\s*merge\s+(.+?)\s*;', body[0][1], re.I | re.S)
    by = re.fullmatch(r'\s*by\s+(.+?)\s*;', body[1][1], re.I | re.S)
    if not merge or not by:
        return None
    dataset = rf'{NAME}(?:\.{NAME})?'
    entry = rf'{dataset}(?:\s*\(\s*((?:(?:in\s*=\s*{NAME}|rename\s*=\s*\([^()]+\))\s*)+)\))?'
    if not re.fullmatch(rf'{entry}(?:\s+{entry})+', merge[1], re.I):
        return None
    entries = re.findall(entry, merge[1], re.I)
    if len(entries) != len(sources):
        return None
    flags, inputs = [], []
    try:
        keys = _names(by[1])
        if len(set(keys)) != len(keys) or set(keys) & {'descending', 'groupformat', 'notsorted'}:
            return None
        for options, source in zip(entries, sources):
            renames = re.findall(r'\brename\s*=\s*\(([^()]+)\)', options, re.I)
            remaining = re.sub(r'\brename\s*=\s*\([^()]+\)', '', options, flags=re.I)
            indicators = re.findall(rf'\bin\s*=\s*({NAME})', remaining, re.I)
            if len(indicators) > 1 or len(renames) > 1:
                return None
            flags.extend((name.casefold(), source) for name in indicators)
            item = dependency(source, '*')
            if renames:
                item['sas_rename'] = _renames(renames[0])
            inputs.append(item)
    except ValueError:
        return None
    if len({name for name, _ in flags}) != len(flags):
        return None
    return flags, inputs, keys


def routed_outputs(operation, block, sources, targets):
    """Describe an exhaustive IF/ELSE OUTPUT chain over one unchanged input row."""
    dataset = rf'{NAME}(?:\.{NAME})?'
    header = re.fullmatch(rf'\s*data\s+({dataset}(?:\s+{dataset})+)\s*;', block[0][3], re.I)
    if (not header or len(sources) != 1 or len(block) < 5
            or not re.fullmatch(rf'\s*set\s+{dataset}\s*;', block[1][3], re.I)
            or not re.fullmatch(r'\s*run\s*;', block[-1][3], re.I)):
        return []
    declared = header[1].casefold().split()
    if len(declared) != len(targets) or len(set(declared)) != len(targets):
        return []
    bindings = dict(zip(declared, targets))
    filters, coverage, records = [], [], []
    branches = block[2:-1]
    for index, (raw, _, _, clean, _, end) in enumerate(branches):
        prefix = '' if index == 0 else r'else\s+'
        if index == len(branches) - 1:
            match = re.fullmatch(rf'\s*else\s+output\s+(?P<target>{dataset})\s*;', clean, re.I)
        else:
            match = re.fullmatch(rf'\s*{prefix}if\s+(.+?)\s+then\s+output\s+(?P<target>{dataset})\s*;', clean, re.I | re.S)
            if match:
                inputs, gaps = _expression_inputs(match[1], sources[0], {}, {}, False, set())
                for item in inputs:
                    item['role'] = 'row_filter'
                    if item not in filters:
                        filters.append(item)
                coverage.extend(gaps)
                if re.search(r'[&%][A-Za-z_]', raw):
                    coverage.append('SAS macro-expanded OUTPUT condition is unresolved')
        if not match or (target := bindings.pop(match['target'].casefold(), None)) is None:
            return []
        offset = block[0][4]
        evidence = operation.code[branches[0][4] - offset:end - offset]
        records.append(passthrough(target, sources[0], evidence, list(filters), coverage, ordinal=index)
                       | {'sas_routed': True})
    return records if not bindings else []


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
    options = {'keep': None, 'drop': [], 'rename': {}, 'where': None}
    if not tail:
        return options
    if not (tail.startswith('(') and tail.endswith(')')):
        raise ValueError('SAS column transformations require a single dataset with simple options')
    tail = tail[1:-1].strip()
    seen = set()
    while tail:
        key = re.match(r'(keep|drop|rename|where)\s*=\s*', tail, re.I)
        if not key:
            raise ValueError('Unsupported SAS dataset option in column transformations')
        name = key[1].casefold()
        if name in seen:
            raise ValueError('Repeated SAS dataset options are unresolved')
        seen.add(name)
        tail = tail[key.end():]
        if name == 'where':
            if keyword != 'set' or not tail.startswith('(') or options['where'] is not None:
                raise ValueError('SAS WHERE option requires one input predicate')
            end = option_end(tail)
            options['where'] = tail[1:end - 1]
            tail = tail[end:].strip()
        elif name == 'rename':
            mapping = re.match(r'\(([^()]*)\)', tail)
            if not mapping:
                raise ValueError('SAS RENAME option requires a plain mapping')
            options[name] = _renames(mapping[1])
            tail = tail[mapping.end():].strip()
        else:
            value = re.split(r'\b(?:keep|drop|rename|where)\s*=', tail, maxsplit=1, flags=re.I)[0]
            options[name] = _names(value)
            tail = tail[len(value):].strip()
    if options['where'] and (options['keep'] is not None or options['drop'] or options['rename']):
        raise ValueError('SAS WHERE mixed with input KEEP/DROP/RENAME is unresolved')
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
    from dataforge.parsers.sas_sql import _valid_typed_literal

    def strip_literal(match):
        literal, suffix = match[1], match[2]
        return ' ' if _valid_typed_literal(literal[1:-1], suffix.casefold()) else match[0]

    expression = re.sub(rf'({STRING})(dt|d|t)\b', strip_literal, expression, flags=re.I)
    stripped = re.sub(STRING, ' ', expression)
    # The literal YYMMN format changes representation and does not read a variable.
    stripped = re.sub(rf'\bput\s*\(\s*({NAME})\s*,\s*yymmn[1-9]\d*\.\s*\)', r'(\1)', stripped, flags=re.I)
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


def hash_lookup(operation, clean, resolve_ref):
    dataset = rf'{NAME}(?:\.{NAME})?'
    pattern = (
        rf'data\s+{dataset}\s*;\s*if\s+_n_\s*=\s*1\s+then\s+do\s*;'
        rf'\s*declare\s+hash\s+(?P<obj>{NAME})\s*\(\s*dataset\s*:\s*(?P<quote>[\'"])'
        rf'(?P<lookup>{dataset})(?P=quote)\s*\)\s*;'
        rf'\s*(?P=obj)\.definekey\s*\(\s*(?P<kq>[\'"])(?P<key>{NAME})(?P=kq)\s*\)\s*;'
        rf'\s*(?P=obj)\.definedata\s*\(\s*(?P<vq>[\'"])(?P<value>{NAME})(?P=vq)\s*\)\s*;'
        rf'\s*(?P=obj)\.definedone\s*\(\s*\)\s*;\s*end\s*;\s*set\s+{dataset}\s*;'
        rf'\s*(?P<rc>{NAME})\s*=\s*(?P=obj)\.find\s*\(\s*\)\s*;'
        r'\s*if\s+(?P=rc)\s+(?:ne\s+|\^=\s*|~=\s*)0\s+then\s+(?P=value)\s*=\s*0\s*;'
        r'\s*drop\s+(?P=rc)\s*;\s*run\s*;'
    )
    match = re.fullmatch(pattern, clean, re.I)
    if not match:
        return []
    source, target = operation.sources[0], operation.targets[0]
    lookup = resolve_ref(match['lookup'])
    key, value, rc = (match[name].casefold() for name in ('key', 'value', 'rc'))
    if len({key, value, rc}) != 3 or lookup.name.casefold() == target.name.casefold():
        return []
    if lookup.name.casefold() != source.name.casefold():
        operation.sources.append(lookup)
    return [
        derivation(target.name, value, operation.code, category='sas_hash_lookup', inputs=[
            dependency(lookup.name, value),
            dependency(lookup.name, key) | {'role': 'value_selection'},
            dependency(source.name, key) | {'role': 'value_selection'},
        ]),
        passthrough(target.name, source.name, operation.code, [], [], exclude={value, rc}, ordinal=1),
    ]


def fixed_array_step(operation, block, clean):
    dataset = rf'{NAME}(?:\.{NAME})?'
    pattern = (
        rf'data\s+{dataset}\s*;\s*set\s+{dataset}\s*;'
        rf'\s*retain\s+(?P<total>{NAME})\s+0\s*;'
        rf'\s*array\s+(?P<array>{NAME})\s*\[\s*(?P<size>[1-9]\d{{0,3}})\s*\]'
        rf'\s*(?P<variables>{NAME}(?:\s+{NAME})*)\s*;'
        rf'\s*do\s+(?P<index>{NAME})\s*=\s*1\s+to\s+dim\s*\(\s*(?P=array)\s*\)\s*;'
        r'\s*(?P=array)\s*\[\s*(?P=index)\s*\]\s*=\s*round\s*\('
        r'\s*(?P=array)\s*\[\s*(?P=index)\s*\]\s*,\s*(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)\s*\)\s*;'
        rf'\s*end\s*;\s*(?P=total)\s*\+\s*(?P<value>{NAME})\s*;'
        rf'\s*(?P<prior>{NAME})\s*=\s*lag\s*\(\s*(?P=value)\s*\)\s*;'
        r'\s*drop\s+(?P=index)\s*;\s*run\s*;'
    )
    match = re.fullmatch(pattern, clean, re.I)
    if not match:
        return []
    source, target = operation.sources[0].name, operation.targets[0].name
    variables = match['variables'].casefold().split()
    total, value, prior, index, array = (match[name].casefold() for name in ('total', 'value', 'prior', 'index', 'array'))
    if (len(variables) != int(match['size']) or value not in variables
            or len(set([*variables, total, prior, index, array])) != len(variables) + 4):
        return []
    steps = []
    scope = 'array-round'
    for column in variables:
        step = derivation(target, column, block[5][0], scope=scope, category='expression',
                          coverage=['Unresolved or ambiguous column ownership requires complete source schemas'])
        step['unqualified_columns'] = [{'column': column, 'role': 'value', 'sources': [{'table': source}]}]
        steps.append(step)
    origins = [dependency(target, value, scope=scope), dependency(source, '') | {'role': 'rowset'}]
    running = derivation(target, total, operation.code, inputs=list(origins), category='sas_retained_sum')
    running['sas_accumulator'] = source
    return [*steps,
            *(derivation(target, column, operation.code, inputs=[dependency(target, column, scope=scope)])
              for column in variables),
            running, derivation(target, prior, block[8][0], inputs=origins, category='sas_lag'),
            passthrough(target, source, operation.code, [], [], exclude={*variables, total, prior, index})]


def data_step_derivations(operation: Operation, block: list[tuple[str, int, int, str, int, int]],
                          resolve_ref: Callable[[str], AssetRef]) -> tuple[list[dict[str, Any]], list[Diagnostic]]:
    """Build ordered DATA-step variable versions and final columns conservatively.

    Args:
        operation: Parsed SAS DATA operation to describe.
        block: Buffered source statements with line and character offsets.
        resolve_ref: Apply SAS library mappings to a literal hash dataset.

    Returns:
        Derivation records and diagnostics for unsupported or incomplete cases.
    """
    targets = [t.name for t in operation.targets if t.kind == 'table']
    if not targets:
        return [], []
    statements = [(entry[0], entry[3]) for entry in block]
    body = statements[1:]
    if records := inline_data(operation, statements[0][1], body):
        return records, []
    coverage = []
    sets = [clean for _, clean in body if re.match(r'\s*set\b', clean, re.I)]
    sources = [source.name for source in operation.sources if source.kind == 'table']
    if (len(operation.sources) == len(operation.targets) == len(sets) == 1
            and len(sources) == 1 and sources[0].casefold() != targets[0].casefold()
            and not re.search(r'[&%][A-Za-z_]', operation.code)):
        clean = '\n'.join(statement for _, statement in statements)
        if records := hash_lookup(operation, clean, resolve_ref) or fixed_array_step(operation, block, clean):
            return records, []
    if records := routed_outputs(operation, block, sources, targets):
        return records, []
    stack = stack_inputs(sets[0], sources, targets) if len(sets) == 1 and len(sources) > 1 and len(targets) == 1 else None
    merge = merge_inputs(body, sources, targets) if not sets else None
    assigned = {match[1].casefold() for _, clean in body if (match := ASSIGNMENT.fullmatch(clean))}
    conditional = {}
    for index, (_, clean) in enumerate(body[:-1]):
        match = IF_ASSIGNMENT.fullmatch(clean)
        following = re.match(r'\s*else\s+(.+)', body[index + 1][1], re.I | re.S)
        alternative = ASSIGNMENT.fullmatch(following[1]) if following else None
        if match and alternative and match[2].casefold() == alternative[1].casefold():
            conditional[index] = (match[1], match[2], match[3], alternative[2])
            assigned.add(match[2].casefold())
    if merge and assigned & {name for name, _ in merge[0]}:
        coverage.append('SAS MERGE with assignments to IN= indicators is unresolved')
    if stack is None and merge is None and (len(sets) > 1 or len(operation.sources) > 1):
        coverage.append('Multiple SAS input datasets/SET statements are unresolved for column transformations')
    if sets:
        before_set = body[:next(index for index, (_, clean) in enumerate(body) if clean == sets[0])]
        if any(ASSIGNMENT.fullmatch(clean) or IF_ASSIGNMENT.fullmatch(clean) for _, clean in before_set):
            coverage.append('SAS assignment before SET may depend on retained values; column transformations unresolved')
    for index, (_, clean) in enumerate(body):
        plain = re.sub(STRING, ' ', clean)
        if merge and index < 2:
            continue
        if merge and re.match(r'\s*(where|retain)\b', plain, re.I):
            coverage.append('SAS MERGE with WHERE or explicit RETAIN is unresolved')
            continue
        if index in conditional or index - 1 in conditional:
            continue
        if (length := LENGTH.fullmatch(clean)) and all(
                name.casefold() in assigned for name in re.findall(NAME, length[1])):
            continue
        if RETAIN_LITERAL.fullmatch(clean):
            continue  # Input ownership and later writes are checked below.
        if ROW_FILTER.fullmatch(clean) and (not re.search(r'\bthen\b', plain, re.I)
                                            or re.search(r'\bthen\s+delete\s*;?$', plain, re.I)):
            continue
        if re.match(r'\s*(merge|update|modify|by|array|do|end|if|else|retain|output|input|infile|'
                    r'call|where|delete|stop|link|goto|select|when|otherwise)\b', plain, re.I):
            coverage.append('SAS procedural/MERGE BY/array/loop/conditional retention transformations are unresolved')
        elif not (ASSIGNMENT.fullmatch(clean) or re.match(r'\s*(set|keep|drop|rename|run)\b', clean, re.I)):
            coverage.append('Unsupported SAS DATA statement in column transformations')
    for keyword in ('keep', 'drop', 'rename'):
        if sum(bool(re.match(rf'\s*{keyword}\s+', clean, re.I)) for _, clean in body) > 1:
            coverage.append(f'Repeated SAS {keyword.upper()} statements are unresolved')
    try:
        output_options = _dataset(statements[0][1], 'data')
        source_options = (_dataset(sets[0], 'set') if sets and stack is None else
                          {'keep': None, 'drop': [], 'rename': {}, 'where': None})
        if any(old in source_options['drop'] or (
                source_options['keep'] is not None and old not in source_options['keep'])
                for old in source_options['rename']):
            coverage.append('SAS input RENAME references a variable removed by input KEEP/DROP')
        if source_options['keep'] is not None:
            input_names = [source_options['rename'].get(name, name) for name in source_options['keep']
                           if name not in source_options['drop']]
            if len(set(input_names)) != len(input_names):
                coverage.append('SAS input RENAME has conflicting column names')
        retained = [m[1].casefold() for _, clean in body if (m := RETAIN_LITERAL.fullmatch(clean))]
        if (len(retained) != len(set(retained)) or set(retained) & assigned
                or retained and sets and (source_options['keep'] is None or set(retained) & set(input_names))):
            coverage.append('SAS RETAIN requires literal initialization and an untouched variable')
    except ValueError as error:
        coverage.append(str(error))
        output_options = source_options = {'keep': None, 'drop': [], 'rename': {}, 'where': None}
    if coverage:
        message = '; '.join(dict.fromkeys(coverage))
        return ([derivation(target, '', operation.code, category='unsupported', coverage=[message])
                 for target in targets], [Diagnostic(message, operation.start)])

    combined = stack is not None or merge is not None
    source = targets[0] if combined else operation.sources[0].name if sets and operation.sources else ''
    source_columns = {source_options['rename'].get(n, n): n for n in source_options['keep'] or []
                      if n not in source_options['drop']}
    known_source = source_options['keep'] is not None
    if not known_source:
        source_columns.update({new: old for old, new in source_options['rename'].items()
                               if old not in source_options['drop']})
    dropped_input = {source_options['rename'].get(n, n) for n in source_options['drop']}
    indicators = merge[0] if merge else stack or []
    flags = {name for name, _ in indicators}
    unavailable = dropped_input | {old for old, new in source_options['rename'].items() if old != new}
    state, versions, steps = {}, {}, []
    filters, filter_coverage = [], []
    if source_options['where']:
        filters, filter_coverage = _expression_inputs(source_options['where'], source, {}, source_columns,
                                                      known_source, unavailable)
        for item in filters:
            item['role'] = 'row_filter'
    keep, drop, rename = None, set(), {}
    for body_index, (raw, clean) in enumerate(body):
        if body_index - 1 in conditional:
            continue
        conditional_assignment = conditional.get(body_index)
        if not conditional_assignment and (match := ROW_FILTER.fullmatch(clean)):
            if match[1].casefold() == 'where' and source_options['where']:
                continue  # A single SET's WHERE= overrides the DATA-step WHERE statement.
            predicate = re.sub(r'\bthen\s+delete\s*;?$', '', match[2], flags=re.I).rstrip(';')
            current = {} if match[1].casefold() == 'where' else state
            inputs, errors = _expression_inputs(predicate, source, current, source_columns, known_source, unavailable)
            for item in inputs:
                item['role'] = 'row_filter'
                if item not in filters:
                    filters.append(item)
            filter_coverage.extend(errors)
            continue
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
        assignment = ASSIGNMENT.fullmatch(clean) or RETAIN_LITERAL.fullmatch(clean)
        if conditional_assignment:
            predicate, name, when_true, when_false = conditional_assignment
            name = name.casefold()
            inputs, errors = _expression_inputs(predicate, source, state, source_columns, known_source, unavailable)
            for item in inputs:
                item['role'] = 'value_selection'
            for value in (when_true, when_false):
                values, gaps = _expression_inputs(value.rstrip(';'), source, state, source_columns,
                                                  known_source, unavailable)
                inputs.extend(item for item in values if item not in inputs)
                errors.extend(gaps)
            start = block[body_index + 1][4] - block[0][4]
            end = block[body_index + 2][5] - block[0][4]
            raw = operation.code[start:end]
        elif assignment:
            name, expression = assignment[1].casefold(), assignment[2].rstrip(';')
            inputs, errors = _expression_inputs(expression, source, state, source_columns, known_source, unavailable)
        else:
            continue
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

    # SAS order: statement KEEP/DROP, statement RENAME, then output options.
    # Output options therefore name the variable after the statement rename.
    # https://support.sas.com/documentation/cdl/en/lrcon/65287/HTML/default/p10abuffsctmo1n1dp2gasb34p76.htm
    before_rename = {new: old for old, new in rename.items()}
    option_names = set(output_options['rename']) | set(output_options['keep'] or [])
    candidates = set(source_columns) | set(state) | set(rename) | {
        before_rename.get(name, name) for name in option_names}
    # Explicit KEEP establishes only the requested output columns, never the whole source schema.
    if keep is not None:
        candidates = keep
    candidates -= drop | flags
    output_names = {}
    for name in candidates:
        renamed = rename.get(name, name)
        if output_options['keep'] is not None and renamed not in output_options['keep']:
            continue
        if renamed not in output_options['drop']:
            output_names[name] = output_options['rename'].get(renamed, renamed)
    if len(set(output_names.values())) != len(output_names):
        coverage.append('SAS output RENAME has conflicting column names')
    for target in targets:
        for name in sorted(output_names):
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
            steps.append(derivation(target, output_names[name], operation.code, inputs=[*inputs, *filters],
                                    coverage=[*errors, *filter_coverage], ordinal=len(steps)))
        if source and not known_source and keep is None and output_options['keep'] is None:
            if not (rename or source_options['rename']):
                steps.append(passthrough(target, source, operation.code, filters, filter_coverage,
                                         exclude=candidates | drop | set(output_options['drop']) | dropped_input | flags,
                                         ordinal=len(steps)))
            else:
                steps.append(derivation(target, '', operation.code, category='wildcard',
                                        coverage=['SAS SET passthrough with RENAME requires an explicit KEEP']))
        if coverage:
            steps.append(derivation(target, '', operation.code, category='unsupported', coverage=coverage))
    if combined:
        scope = 'merge-input' if merge else 'set-input'
        for step in steps:
            pending = []
            for item in step['inputs']:
                if item['table'] == source and not item['scope']:
                    item['scope'] = scope
                    if item['column'] not in {'*', *flags}:
                        pending.append(item)
            if pending:
                step['inputs'] = [item for item in step['inputs'] if item not in pending]
                step['scoped_columns'] = pending
                step['coverage'].append('Intermediate wildcard requires a complete output layout')
                step['status'] = 'unresolved'
        inputs = merge[1] if merge else [dependency(table, '*') for table in sources]
        evidence = operation.code if merge else sets[0]
        gap = ('SAS match MERGE requires complete input layouts and a common BY key on each input' if merge
               else 'SAS concatenated SET requires complete input layouts')
        layout = derivation(source, '', evidence, scope=scope, inputs=inputs, category='wildcard', coverage=[gap])
        layout.update(sas_stack=True, wildcard_safe=True, sas_flags=sorted(flags))
        if merge:
            layout['sas_merge_by'] = merge[2]
        flag_steps = [derivation(source, flag, evidence, scope=scope, category='indicator', ordinal=index + 1,
                                 inputs=[dependency(table, '') | {'role': 'rowset'}])
                      for index, (flag, table) in enumerate(indicators)]
        steps = [layout, *flag_steps, *steps]
    return steps, [Diagnostic(message, operation.start) for message in coverage]


def proc_derivations(operation: Operation, clean: str) -> list[dict[str, Any]]:
    """Mark PROC output transformations unsupported for each target dataset.

    Args:
        operation: Parsed PROC operation.
        clean: PROC statements without comments.

    Returns:
        Unresolved derivation records for the operation's targets.
    """
    if len(operation.sources) == len(operation.targets) == 1:
        source, target = operation.sources[0].name, operation.targets[0].name
        dataset = rf'{NAME}(?:\.{NAME})?'
        if (operation.kind == 'PROC APPEND' and source.casefold() != target.casefold()
                and re.fullmatch(rf'\s*proc\s+append\s+base\s*=\s*{dataset}\s+data\s*=\s*{dataset}'
                                 r'\s+force\s*;\s*run\s*;\s*', clean, re.I)):
            return [derivation(target, '', operation.code, category='sas_append',
                               inputs=[dependency(source, '*')],
                               coverage=['SAS PROC APPEND requires complete BASE and DATA layouts'])]
        if operation.kind == 'PROC SORT':
            sort = re.fullmatch(
                rf'\s*proc\s+sort\s+(?:(?:data|out)\s*=\s*{dataset}\s*|nodupkey\s*)+;'
                rf'\s*by\s+((?:{NAME}\s*)+);\s*run\s*;?\s*', clean, re.I)
            if sort:
                if source.casefold() == target.casefold():
                    return []  # In-place sorting preserves the origin of every value.
                role = 'row_filter' if re.search(r'\bnodupkey\b', clean, re.I) else 'order'
                keys = [dependency(source, name) | {'role': role} for name in sort[1].casefold().split()
                        if name != 'descending']
                return [passthrough(target, source, operation.code, keys, [])]
        if operation.kind in {'PROC SUMMARY', 'PROC MEANS'} and source.casefold() != target.casefold():
            statistic = rf'(?:sum|mean)\s*\(\s*({NAME})\s*\)\s*=\s*({NAME})'
            summary = re.fullmatch(
                rf'\s*proc\s+(?:summary|means)\s+data\s*=\s*{dataset}\s+nway\s*;'
                rf'\s*class\s+({NAME}(?:\s+{NAME})*)\s*;\s*var\s+({NAME}(?:\s+{NAME})*)\s*;'
                rf'\s*output\s+out\s*=\s*{dataset}\s+(?:sum\s*=\s*({NAME})|'
                rf'((?:{statistic})(?:\s+{statistic})*))\s*;\s*run\s*;?\s*',
                clean, re.I)
            if summary:
                groups = summary[1].casefold().split()
                variables = summary[2].casefold().split()
                pairs = ([(variables[0], summary[3].casefold())] if summary[3] and len(variables) == 1
                         else re.findall(statistic, summary[4].casefold()) if summary[4] else [])
                values = {output: value for value, output in pairs}
                names = [*groups, '_type_', '_freq_', *(output for _, output in pairs)]
                if (pairs and len(set(names)) == len(names)
                        and set(values.values()) <= set(variables)):
                    context = [dependency(source, name) | {'role': 'value_selection'} for name in groups]
                    context.append(dependency(source, '') | {'role': 'rowset'})
                    return [
                        derivation(target, name, operation.code, ordinal=index,
                                   inputs=[*([dependency(source, name)] if name in groups else
                                             [dependency(source, values[name])] if name in values else []), *context],
                                   category='aggregate' if name == '_freq_' or name in values else 'projection')
                        for index, name in enumerate(names)
                    ]
        if operation.kind == 'PROC TRANSPOSE' and source.casefold() != target.casefold():
            transpose = re.fullmatch(
                rf'\s*proc\s+transpose\s+data\s*=\s*{dataset}\s+out\s*=\s*{dataset}\s+prefix\s*=\s*({NAME})\s*;'
                rf'\s*by\s+({NAME}(?:\s+{NAME})*)\s*;\s*var\s+({NAME}(?:\s+{NAME})*)\s*;\s*run\s*;\s*',
                clean, re.I)
            if transpose:
                groups, values = (transpose[index].casefold().split() for index in (2, 3))
                if (len(set([*groups, *values, '_name_', '_label_'])) == len(groups) + len(values) + 2
                        and not set(groups) & {'descending', 'notsorted'}
                        and not any(re.fullmatch(rf'{transpose[1]}[1-9]\d*', name, re.I) for name in groups)):
                    context = [dependency(source, name) | {'role': 'value_selection'} for name in groups]
                    projections = [derivation(target, name, operation.code,
                                               inputs=[dependency(source, name), *context], ordinal=index)
                                   for index, name in enumerate(groups)]
                    return [*projections,
                            derivation(target, '_name_', operation.code, inputs=context,
                                       category='metadata', ordinal=len(groups)),
                            derivation(target, '*', operation.code, scope=f'transpose-values:{transpose[1]}', category='wildcard',
                                       inputs=[*(dependency(source, name) for name in values), *context],
                                       coverage=[f'SAS TRANSPOSE output {transpose[1]} columns depend on runtime BY-group sizes'])]
        if operation.kind == 'PROC RANK' and source.casefold() != target.casefold():
            rank = re.fullmatch(
                rf'\s*proc\s+rank\s+data\s*=\s*{dataset}\s+out\s*=\s*{dataset}\s+groups\s*=\s*[1-9]\d*\s*;'
                rf'\s*var\s+({NAME})\s*;\s*ranks\s+({NAME})\s*;\s*run\s*;?\s*', clean, re.I)
            if rank:
                value, output = rank[1].casefold(), rank[2].casefold()
                return [derivation(target, output, operation.code, category='rank',
                                   inputs=[dependency(source, value), dependency(source, '') | {'role': 'rowset'}]),
                        passthrough(target, source, operation.code, [], [], exclude=[output], ordinal=1)]
    return [derivation(target.name, '', operation.code, category='unsupported',
                       coverage=[f'{operation.kind} column transformations are unsupported'])
            for target in operation.targets]
