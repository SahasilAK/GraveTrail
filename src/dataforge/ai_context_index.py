"""AI-only, run-local definition lookup rebuilt from pinned source and results."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from dataforge.ai_analysis_models import ContextEntry, SourceReference
from dataforge.models import canonical, stable_id


@dataclass
class ContextIndex:
    workspace: str
    sources: dict
    entries: list[ContextEntry]
    revision: str
    denied: list[str] = field(default_factory=list)


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
                   r'(?i)\bcreate\s+(?:or\s+replace\s+)?(?:table|view|function|procedure)\s+([\w.]+)')
        for match in re.finditer(pattern, source.code):
            end = source.code.find(';', match.end())
            end = len(source.code) if end < 0 else end + 1
            if source.source_kind == 'sas':
                mend = re.search(r'(?i)%mend\b[^;]*;', source.code[match.end():])
                if mend:
                    end = match.end() + mend.end()
            reference = SourceReference(file_id=source.file_id, content_hash=source.content_hash,
                                        start_offset=match.start(), end_offset=end)
            entries.append(ContextEntry(entry_id=stable_id(prepared.workspace, source.file_id, str(match.start())),
                symbol=match[1], source_kind=source.source_kind, scope=source.job_id if source.source_kind == 'sas' else '',
                kind='macro' if source.source_kind == 'sas' else 'resource',
                evidence=[reference], origin='source_declared'))
        if source.source_kind == 'dbt':
            for resource in json.loads(source.context_json).get('resources', []):
                definition = resource.get('definition', {}).get('source', {})
                fid = definition.get('file_id')
                if fid in sources:
                    ref_source = sources[fid]
                    if not ref_source.code:
                        continue
                    entries.append(ContextEntry(entry_id=resource['resource_id'], symbol=resource['name'],
                        source_kind='dbt', scope=resource.get('package_name', ''), kind=resource.get('resource_type', 'resource'),
                        evidence=[SourceReference(file_id=fid, content_hash=ref_source.content_hash,
                            start_offset=0, end_offset=len(ref_source.code))], origin='source_declared'))
    for extraction in saved_extractions:
        for entry in extraction.definitions:
            if _allowed(entry, sources):
                entries.append(entry.model_copy(update={'origin': 'ai_inferred', 'revision': extraction.revision}))
            else:
                denied.append(entry.entry_id)
    unique = {json.dumps(e.model_dump(), sort_keys=True): e for e in entries}
    entries = [unique[k] for k in sorted(unique)]
    revision = hashlib.sha256(json.dumps([e.model_dump() for e in entries], sort_keys=True).encode()).hexdigest()
    return ContextIndex(prepared.workspace, sources, entries, revision, denied)


def context_for_part(index, part, budget, *, symbols=None):
    source = index.sources.get(part.file_id)
    if source is None or source.content_hash != part.content_hash:
        raise ValueError('Part is outside pinned disclosure set')
    code = source.code[part.start_offset:part.end_offset]
    names = set(symbols) if symbols is not None else set(re.findall(r'[\w.]+', code))
    result, used = ContextSelection(), 0
    for name in sorted(names):
        candidates = [e for e in index.entries if e.available and canonical(e.symbol) == canonical(name)
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
