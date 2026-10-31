"""Host-owned evidence and identity checks for focused SQL/SAS proposals.

The catalog supplies identities, never permission to invent or reject source names.
This module has no provider, scheduler, persistence or UI side effects.
"""
from __future__ import annotations

import re
from dataclasses import asdict

import sqlglot

from dataforge.ai_context_index import IDENTIFIER, _declaration_text, referenced_asset_names
from dataforge.asset_identity import AssetResolver, job_assets, source_job
from dataforge.models import ParseResult, canonical, statements
from dataforge.parsers.sas import dataset_ref, parse_sas
from dataforge.parsers.sql import parse_sql

MESSAGES = {
    'evidence_outside_selection': 'Claim line range is outside the authorized source selection.',
    'evidence_not_found': 'Evidence quote does not match its supplied location and has no exact occurrence in the selected source.',
    'ambiguous_evidence': 'Evidence is ambiguous within the selected source; supply coordinates that identify one occurrence.',
    'unavailable_evidence': 'Redacted or unavailable evidence cannot be verified.',
    'unsupported_relationship': 'Proposed resource or relationship lacks bound executable read/write evidence for this operation in the same statement or SAS block.',
    'ambiguous_identity': 'Resource identity is ambiguous; qualify the name or resolve conflicting scope/job identities.',
    'identity_changed': 'Resource identity changed since validation; request assistance again.',
    'source_changed': 'Source changed since the request; request assistance again.',
    'job_changed': 'Source job/session changed since the request; request assistance again.',
    'settings_changed': 'Parsing or identity settings changed since the request; request assistance again.',
    'invalid_response': 'Response is not valid JSON matching the focused task schema.',
    'request_failed': 'Provider request failed; inspect provider connectivity, authorization and capacity.',
    'request_busy': 'AI assistance capacity is busy; wait for the active request to finish and retry.',
    'preparation_changed': 'Request source, redaction, parsing settings or profile changed; refresh the evidence preview.',
    'request_budget_exceeded': 'Request exceeds the confirmed input allowance or source disclosure policy; refresh the preview and inspect its blockers.',
    'external_requests_disabled': 'External LLM requests are disabled in Security and privacy.',
    'full_source_disabled': 'Complete source transmission is disabled; select a statement range or change privacy settings.',
}


class GroundingError(ValueError):
    """A bounded public error; never includes model output or raw source."""

    def __init__(self, code, claim=None):
        self.failure = {'code': code, 'message': MESSAGES[code]}
        if claim is not None:
            self.failure['claim_index'] = claim
        super().__init__(MESSAGES[code])


def resource_key(name, settings):
    """Use the same case policy for evidence references and accepted identities."""
    return name.strip() if settings.get('case_sensitive') else canonical(name)


def _executable_text(code, extension, settings):
    if extension == '.sas':
        clean = re.sub(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|/\*[\s\S]*?\*/|--[^\n]*",
            lambda m: ''.join('\n' if c == '\n' else ' ' for c in m[0]), code)
        masked = ['\n' if char == '\n' else ' ' for char in code]
        cursor = 0
        # The existing SAS splitter skips datalines/cards payloads. Statement
        # comments (%* and *) are data too, including multiline comments.
        for statement, _, _ in statements(code, sas=True):
            offset = code.find(statement, cursor)
            cursor = offset + len(statement)
            if _declaration_text(statement).lstrip().startswith(('*', '%*')):
                continue
            masked[offset:cursor] = clean[offset:cursor]
        return ''.join(masked)
    # Token ranges preserve dialect-specific nested comments and string
    # boundaries. They are a denial guard, never additional disclosed evidence.
    masked = ['\n' if char == '\n' else ' ' for char in code]
    try:
        for token in sqlglot.Dialect.get_or_raise(settings.get('dialect') or None).tokenize(code):
            if 'STRING' not in token.token_type.name:
                masked[token.start:token.end + 1] = code[token.start:token.end + 1]
    except sqlglot.errors.TokenError:
        raise GroundingError('unsupported_relationship') from None
    return ''.join(masked)


def _operations(code, extension, settings):
    if extension == '.sas':
        # Runtime/macro expansion cannot establish original source identities.
        return parse_sas(code, settings.get('library_mappings'), {}, settings.get('dialect', '')).operations
    parsed = parse_sql(code, settings.get('dialect', ''))
    operations = list(parsed.operations)
    # A narrow syntax witness for an INSERT/SELECT whose whole statement is
    # unsupported by the configured parser (e.g. backticks plus MySQL upsert).
    # Normalize identifier delimiters, not dialect settings or source evidence.
    for original, first, last in statements(code):
        masked = _declaration_text(original)
        if not re.match(r'\s*INSERT\s+INTO\b', masked, re.I):
            continue
        prefix = original
        suffix = re.search(r'\bON\s+DUPLICATE\s+KEY\s+UPDATE\b', masked, re.I)
        if suffix:
            # Only the literal VALUES(column) upsert form has a bounded witness.
            tail = masked[suffix.end():].strip().rstrip(';').strip()
            ident = r'(?:`\w+`|"\w+"|\w+)'
            assignment = ident + r'\s*=\s*VALUES\s*\(\s*' + ident + r'\s*\)'
            if not re.fullmatch(assignment + r'(?:\s*,\s*' + assignment + r')*', tail, re.I):
                continue
            prefix = original[:suffix.start()]
        normalized = re.sub(r"'(?:''|[^'])*'|--[^\n]*|/\*[\s\S]*?\*/|`((?:``|[^`])*)`",
            lambda m: '"' + m[1].replace('``', '`').replace('"', '""') + '"' if m[1] is not None else m[0], prefix)
        for op in parse_sql(normalized, settings.get('dialect', '')).operations:
            if op.kind == 'INSERT' and op.sources and op.targets:
                op.code, op.start, op.end = original, first, last
                operations.append(op)
    return operations


def ground_response(response, source, first, last, settings, *, rebind=True):
    """Validate exact evidence and executable roles; return host corrections and refs.

    Mutates only the caller-owned response coordinates. Confidence never affects
    eligibility. Evidence is checked in the entire authorized selection, so a
    quote embedded in a comment/string or spliced across operations cannot pass.
    """
    if source['extension'] not in {'.sql', '.sas'}:
        raise GroundingError('unsupported_relationship')
    lines = source['raw_content'].splitlines()
    if not 1 <= first <= last <= len(lines):
        raise GroundingError('evidence_outside_selection')
    selection = '\n'.join(lines[first - 1:last])
    ops = _operations(selection, source['extension'], settings)
    original = '\n'.join(lines)
    original_ops = _operations(original, source['extension'], settings)
    executable = _executable_text(original, source['extension'], settings)
    def norm(name):
        return resource_key(name, settings)
    corrections, refs, citations, declarations = [], {}, [], set()
    for index, claim in enumerate(response.claims):
        if not first <= claim.start_line <= claim.end_line <= last:
            raise GroundingError('evidence_outside_selection', index)
        if '[REDACTED' in claim.quote.upper():
            raise GroundingError('unavailable_evidence', index)
        span = '\n'.join(lines[claim.start_line - 1:claim.end_line])
        supplied = [claim.start_line, claim.end_line]
        if claim.quote not in span:
            if not rebind:
                raise GroundingError('evidence_not_found', index)
            start = selection.find(claim.quote)
            if start < 0:
                raise GroundingError('evidence_not_found', index)
            if selection.find(claim.quote, start + 1) >= 0:
                raise GroundingError('ambiguous_evidence', index)
            claim.start_line = first + selection.count('\n', 0, start)
            claim.end_line = claim.start_line + claim.quote.count('\n')
            corrections.append({'claim_index': index, 'reported': supplied,
                                'corrected': [claim.start_line, claim.end_line], 'method': 'unique_exact_quote'})
        else:
            first_match = span.find(claim.quote)
            if span.find(claim.quote, first_match + 1) >= 0:
                raise GroundingError('ambiguous_evidence', index)
        offset = sum(len(line) + 1 for line in lines[:claim.start_line - 1]) + span.find(claim.quote)
        if corrections and corrections[-1]['claim_index'] == index:
            span = '\n'.join(lines[claim.start_line - 1:claim.end_line])
            offset = sum(len(line) + 1 for line in lines[:claim.start_line - 1]) + span.find(claim.quote)
        # Inspect the quote at its actual original location. Extracting the body
        # of a comment/string must never turn it into executable source.
        names = {canonical(n) for n in referenced_asset_names(executable[offset:offset + len(claim.quote)],
                                                            [claim.source, claim.target])}
        claim_source, claim_target = claim.source, claim.target
        if source['extension'] == '.sas':
            mappings = settings.get('library_mappings')
            names = {canonical(dataset_ref(n, mappings).name) for n in
                     re.findall(IDENTIFIER, executable[offset:offset + len(claim.quote)])}
            # Stored responses already use host identities. Prefer actual
            # operation refs before applying a lexical library mapping again.
            normalized = []
            relevant = [op for op in ops if op.kind.upper() == claim.operation.upper() and claim.quote in op.code]
            for name, role in [(claim.source, 'sources'), (claim.target, 'targets')]:
                actual = {norm(ref.name): ref.name for op in relevant for ref in getattr(op, role)}
                mapped = dataset_ref(name, mappings).name
                normalized.append(actual.get(norm(name), actual.get(norm(mapped), mapped)))
            claim_source, claim_target = normalized
        if not any(op.kind.upper() == claim.operation.upper()
                   and any(norm(ref.name) == norm(claim_source) for ref in op.sources)
                   and any(norm(ref.name) == norm(claim_target) for ref in op.targets)
                   for op in _operations(claim.quote, source['extension'], settings)):
            raise GroundingError('unsupported_relationship', index)
        if not any(op.kind.upper() == claim.operation.upper() and claim.quote in op.code
                   and op.start <= claim.start_line <= claim.end_line <= op.end
                   and any(norm(ref.name) == norm(claim_source) for ref in op.sources)
                   and any(norm(ref.name) == norm(claim_target) for ref in op.targets) for op in original_ops):
            raise GroundingError('unsupported_relationship', index)
        matches = []
        for op in ops:
            if (op.kind.upper() != claim.operation.upper() or claim.quote not in op.code
                    or not first + op.start - 1 <= claim.start_line <= claim.end_line <= first + op.end - 1):
                continue
            for src in op.sources:
                for tgt in op.targets:
                    if ({canonical(claim_source), canonical(claim_target)} <= names
                            and norm(src.name) == norm(claim_source)
                            and norm(tgt.name) == norm(claim_target)):
                        matches.append((src, tgt))
        if not matches:
            raise GroundingError('unsupported_relationship', index)
        for ref in matches[0]:
            refs[norm(ref.name)] = ref
        if claim.operation.upper() in {'CREATE', 'DATA'} and not matches[0][1].temporary:
            declarations.add(norm(matches[0][1].name))
        claim.source, claim.target = (ref.name for ref in matches[0])
        claim.operation = claim.operation.upper()
        citations.append({'claim_index': index, 'file_id': source.get('file_id'),
                          'content_hash': source.get('content_hash'),
                          'start_line': claim.start_line, 'end_line': claim.end_line})
    return {'corrections': corrections, 'references': refs, 'citations': citations,
            'persistent_declarations': sorted(declarations)}


def resolve_resources(workspace, source, settings, references, assets, persistent_declarations=()):
    """Reuse exact identities, otherwise plan new identities with the host resolver."""
    def norm(name):
        return resource_key(name, settings)
    job = source_job(source, settings)
    visible = job_assets(assets, job)
    grouped = {}
    for asset in visible:
        grouped.setdefault(norm(asset['name']), []).append(asset)
    config = {'case_sensitive': False, **settings}
    parsed = ParseResult(assets=list(references.values()))
    resolver = AssetResolver(workspace, [(source, parsed)], config)
    resources, bindings = [], {}
    for name, ref in references.items():
        candidates = grouped.get(norm(ref.name), [])
        # A bare identifier may otherwise be rebound by normal analysis to a
        # similarly named qualified resource. Leave this ambiguity unresolved.
        if not candidates and '.' not in ref.name and not ref.temporary:
            if any(norm(a['name']).rsplit('.', 1)[-1] == norm(ref.name) for a in visible):
                raise GroundingError('ambiguous_identity')
        if len(candidates) > 1 or (candidates and (
                candidates[0]['kind'] != ref.kind or (ref.temporary and not candidates[0]['temporary'])
                or (name in persistent_declarations and candidates[0]['temporary']))):
            raise GroundingError('ambiguous_identity')
        if candidates:
            aid, action = candidates[0]['asset_id'], 'reuse'
            # A SQL read may inherit a temporary identity declared by SAS in
            # the same job. Catalog collisions were rejected above.
            ref.temporary = bool(candidates[0]['temporary'])
            row = None
        else:
            aid, _ = resolver.resolve(ref, source, parsed)
            if any(a['asset_id'] == aid for a in assets):
                raise GroundingError('ambiguous_identity')
            row, action = resolver.registry[aid], 'create'
        bindings[name] = aid
        resources.append({'name': ref.name, 'asset_id': aid, 'kind': ref.kind, 'temporary': ref.temporary,
                          'job_id': job, 'action': action, 'reference': asdict(ref), 'row': row})
    return resources, bindings


def validate_saved_response(response, details, workspace, source, settings, assets):
    """Revalidate acceptance authority identically at explicit merge and refresh."""
    if source['workspace_id'] != workspace or source['content_hash'] != details['content_hash']:
        raise GroundingError('source_changed')
    if details.get('job_id', 'workspace') != source_job(source, settings):
        raise GroundingError('job_changed')
    saved_settings = details.get('settings', settings)
    # Compare effective identity/semantic settings for this source. CSV options
    # or a dialect mapping for another folder cannot invalidate accepted facts.
    if any(saved_settings.get(key) != settings.get(key)
           for key in ('dialect', 'library_mappings', 'macros', 'case_sensitive')):
        raise GroundingError('settings_changed')
    # Historical schema 1 saved no selection: permit only exact saved claim
    # locations, without new evidence searches or coordinate corrections.
    bounds = details.get('selection', {'first': min((c.start_line for c in response.claims), default=1),
        'last': max((c.end_line for c in response.claims), default=1)})
    grounded = ground_response(response, source, bounds['first'], bounds['last'], settings, rebind=False)
    resources, bindings = resolve_resources(workspace, source, settings, grounded['references'], assets,
                                            grounded['persistent_declarations'])
    prior = {resource_key(r['name'], settings): r['asset_id'] for r in (details.get('grounding') or {}).get('resources', [])}
    if prior and prior != bindings:
        raise GroundingError('identity_changed')
    return grounded, resources, bindings
