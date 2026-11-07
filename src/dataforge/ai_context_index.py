"""AI-only, run-local definition lookup rebuilt from pinned source and results."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from dataforge.ai_analysis_models import ContextEntry, SourceReference
from dataforge.models import canonical, stable_id

IDENTIFIER = r'(?:"(?:""|[^"])+"|`(?:``|[^`])+`|\[(?:\]\]|[^\]])+\]|[\w]+)(?:\.(?:"(?:""|[^"])+"|`(?:``|[^`])+`|\[(?:\]\]|[^\]])+\]|[\w]+))*'


def _symbol_key(name):
    return name.strip() if any(q in name for q in '"`[') else canonical(name)


def _declaration_text(code):
    return re.sub(r"'(?:''|[^'])*'|--[^\r\n]*|/\*[\s\S]*?\*/",
                  lambda m: ''.join('\n' if c == '\n' else ' ' for c in m[0]), code)


def referenced_asset_names(code, known):
    """Select every known name referenced by this source, independently of budget."""
    # Reuse project context's quote-aware lexer and comment/literal masking.
    symbols = {canonical(name) for name in re.findall(r'[#@$]*' + IDENTIFIER, _declaration_text(code))}
    return sorted(name for name in known if canonical(name) in symbols)


@dataclass
class ContextIndex:
    workspace: str
    sources: dict
    entries: list[ContextEntry]
    revision: str
    denied: list[str] = field(default_factory=list)
    by_symbol: dict = field(default_factory=dict)


@dataclass
class ContextSelection:
    entries: list[ContextEntry] = field(default_factory=list)
    wire: list[dict] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    omitted: list[str] = field(default_factory=list)
    fingerprint: str = ''


def _allowed(entry, sources):
    return bool(entry.evidence) and all(r.file_id in sources and
        sources[r.file_id].content_hash == r.content_hash and
        0 <= r.start_offset < r.end_offset <= len(sources[r.file_id].code) for r in entry.evidence)


def build_context_index(prepared, saved_extractions):
    sources = {s.file_id: s for s in prepared.sources}
    entries, denied = [], []
    for source in sources.values():
        # Only explicit lexical declarations: no static semantic extraction.
        pattern = (r'(?im)%macro\s+([\w.]+)' if source.source_kind == 'sas' else
                   r'(?i)\bcreate\s+(?:or\s+replace\s+)?(?:table|view|function|procedure)\s+(' + IDENTIFIER + ')')
        masked = _declaration_text(source.code)
        for match in re.finditer(pattern, masked):
            end = masked.find(';', match.end())
            end = len(source.code) if end < 0 else end + 1
            if source.source_kind == 'sas':
                mend = re.search(r'(?i)%mend\b[^;]*;', masked[match.end():])
                if mend:
                    end = match.end() + mend.end()
            reference = SourceReference(file_id=source.file_id, content_hash=source.content_hash,
                                        start_offset=match.start(), end_offset=end)
            entries.append(ContextEntry(entry_id=stable_id(prepared.workspace, source.file_id, str(match.start())),
                symbol=match[1], source_kind=source.source_kind, scope=source.job_id if source.source_kind == 'sas' else '',
                kind='macro' if source.source_kind == 'sas' else 'resource',
                evidence=[reference], origin='source_declared'))
        if source.source_kind == 'sas':
            for kind, declaration in [('parameter', r'(?i)%let\s+(\w+)\s*='), ('library', r'(?i)\blibname\s+(\w+)\b')]:
                for match in re.finditer(declaration, masked):
                    end = masked.find(';', match.end())
                    end = len(source.code) if end < 0 else end + 1
                    entries.append(ContextEntry(entry_id=stable_id(prepared.workspace, source.file_id, str(match.start())),
                        symbol=match[1], source_kind='sas', scope=source.job_id, kind=kind, origin='source_declared',
                        evidence=[SourceReference(file_id=source.file_id, content_hash=source.content_hash,
                                                  start_offset=match.start(), end_offset=end)]))
        if source.source_kind == 'dbt':
            for resource in json.loads(source.context_json).get('resources', []):
                definition = resource.get('definition', {}).get('source', {})
                fid = definition.get('file_id')
                if fid in sources:
                    ref_source = sources[fid]
                    if not ref_source.code:
                        continue
                    entries.append(ContextEntry(entry_id=resource['resource_id'], symbol=resource['name'],
                        source_kind='dbt', scope=resource.get('project_id', ''), kind=resource.get('resource_type', 'resource'),
                        evidence=[SourceReference(file_id=fid, content_hash=ref_source.content_hash,
                            start_offset=0, end_offset=len(ref_source.code))], origin='source_declared'))
            for config in json.loads(source.context_json).get('configuration_sources', []):
                fid = config['file_id']
                if fid in sources and sources[fid].code:
                    ref_source = sources[fid]
                    entries.append(ContextEntry(entry_id='dbt-config:' + fid, symbol='dbt-config:' + fid,
                        source_kind='dbt', scope=source.job_id, kind='configuration', origin='source_declared',
                        evidence=[SourceReference(file_id=fid, content_hash=ref_source.content_hash,
                                                  start_offset=0, end_offset=len(ref_source.code))]))
    for extraction in saved_extractions:
        for entry in extraction.definitions:
            if _allowed(entry, sources):
                entries.append(entry.model_copy(update={'origin': 'ai_inferred', 'revision': extraction.revision}))
            else:
                denied.append(entry.entry_id)
    unique = {json.dumps(e.model_dump(), sort_keys=True): e for e in entries}
    entries = [unique[k] for k in sorted(unique)]
    revision = hashlib.sha256(json.dumps([e.model_dump() for e in entries], sort_keys=True).encode()).hexdigest()
    by_symbol = {}
    for entry in entries:
        by_symbol.setdefault(_symbol_key(entry.symbol), []).append(entry)
        if entry.source_kind == 'dbt':
            by_symbol.setdefault(entry.entry_id, []).append(entry)
    return ContextIndex(prepared.workspace, sources, entries, revision, denied, by_symbol)


def context_for_part(index, part, budget, *, symbols=None):
    source = index.sources.get(part.file_id)
    if source is None or source.content_hash != part.content_hash:
        raise ValueError('Part is outside pinned disclosure set')
    code = source.code[part.start_offset:part.end_offset]
    names = set(symbols) if symbols is not None else set(re.findall(IDENTIFIER, code))
    if part.source_kind == 'sas':
        names.update(name.split('.', 1)[0] for name in list(names) if '.' in name)
    if part.source_kind == 'dbt' and symbols is None:
        names.update(r['resource_id'] for r in json.loads(source.context_json).get('resources', []))
        names.update('dbt-config:' + c['file_id'] for c in json.loads(source.context_json).get('configuration_sources', []))
    result, used = ContextSelection(), 0
    for name in sorted(names):
        candidates = [e for e in index.by_symbol.get(_symbol_key(name), []) if e.available
            and e.source_kind == part.source_kind and (not e.scope or e.scope == part.scope)
            and not all(r.file_id == part.file_id and part.start_offset <= r.start_offset and
                        r.end_offset <= part.end_offset for r in e.evidence)]
        # A declaration repeated in saved AI output is the same definition.
        definitions = {}
        for entry in candidates:
            key = tuple((r.file_id, r.content_hash, r.start_offset, r.end_offset) for r in entry.evidence)
            if key not in definitions or entry.origin != 'ai_inferred':
                definitions[key] = entry
        if len(definitions) != 1:
            if candidates:
                result.unresolved.append(name)
            continue
        entry = next(iter(definitions.values()))
        if any(e.entry_id == entry.entry_id for e in result.entries):
            continue
        if not _allowed(entry, index.sources):
            result.unresolved.append(name)
            continue
        wire = {**entry.model_dump(), 'source': '\n'.join(index.sources[r.file_id].code[r.start_offset:r.end_offset]
                                                        for r in entry.evidence)}
        size = len(json.dumps(wire, ensure_ascii=False).encode())
        if used + size > budget:
            result.omitted.append(entry.entry_id)
            continue
        used += size
        result.entries.append(entry)
        result.wire.append(wire)
    result.fingerprint = hashlib.sha256(json.dumps(result.wire, sort_keys=True).encode()).hexdigest()
    return result


def restore_part_context(index, part):
    """Rehydrate exactly pinned definitions, even if new fitting changes ranges."""
    wire = []
    for entry_id in part.context_ids:
        candidates = [e for e in index.entries if e.entry_id == entry_id]
        if len(candidates) != 1 or not _allowed(candidates[0], index.sources):
            raise ValueError('pinned_context_unavailable')
        entry = candidates[0]
        if any(r not in part.context_references for r in entry.evidence):
            raise ValueError('pinned_context_unavailable')
        wire.append({**entry.model_dump(), 'source': '\n'.join(
            index.sources[r.file_id].code[r.start_offset:r.end_offset] for r in entry.evidence)})
    fingerprint = hashlib.sha256(json.dumps(wire, sort_keys=True).encode()).hexdigest()
    if part.context_hashes and part.context_hashes != [fingerprint]:
        raise ValueError('pinned_context_unavailable')
    return wire


@dataclass(frozen=True)
class CompletionWork:
    part: object
    original_part_id: str
    missing_symbols: tuple[str, ...]
    context: ContextSelection
    catalog_revision: str
    superseded_revision: int


def plan_context_completion(extractions, frozen_index, *, completed=frozenset(), budget=1000000):
    works = []
    for part, item in extractions:
        if part.work_kind != 'extraction' or part.part_id in completed or not item.missing_context:
            continue
        symbols = {m.symbol for m in item.missing_context if m.status == 'unresolved' and
                   (not m.scope or m.scope == part.scope)}
        selection = context_for_part(frozen_index, part, budget, symbols=symbols)
        new_ids = {e.entry_id for e in selection.entries} - set(part.context_ids)
        if not new_ids:
            continue
        if not selection.entries or all(m.consumed_fingerprint == selection.fingerprint for m in item.missing_context):
            continue
        completion = part.model_copy(update={
            'part_id': stable_id('completion5', part.part_id, frozen_index.revision),
            'work_kind': 'context_completion', 'context_ids': [e.entry_id for e in selection.entries],
            'context_hashes': [selection.fingerprint],
            'context_references': [r for e in selection.entries for r in e.evidence]})
        works.append(CompletionWork(completion, part.part_id, tuple(sorted(symbols)), selection,
                                    frozen_index.revision, item.revision))
    return works
