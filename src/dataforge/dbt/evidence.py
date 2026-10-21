"""Exact source slices and supplementary dbt evidence integrity."""
import json

from dataforge.dbt.models import EvidenceRef, SourceRef


def evidence(source, text, start=0, end=None, *, pointer=None, origin='source_static'):
    if not isinstance(source, SourceRef):
        source = SourceRef(source['file_id'], source['content_hash'], source['relative_path'])
    end = len(text) if end is None else end
    return EvidenceRef(source, text.count('\n', 0, start) + 1,
        text.count('\n', 0, max(start, end - 1)) + 1, start, end, text[start:end], pointer, origin)


def validate_dbt_evidence(store, workspace):
    invalid = []
    refs = store.rows('SELECT * FROM dbt_evidence WHERE workspace_id=?', [workspace])
    for ref in refs:
        try:
            source = store.file(ref['file_id'], ref['content_hash'])
            text = source['raw_content']
            if text[ref['start_offset']:ref['end_offset']] != ref['excerpt']:
                raise ValueError('evidence differs')
            if ref['json_pointer'] is not None:
                value = json.loads(text)
                for component in ref['json_pointer'].removeprefix('/').split('/'):
                    key = component.replace('~1', '/').replace('~0', '~')
                    value = value[int(key)] if isinstance(value, list) else value[key]
                if value != json.loads(ref['excerpt']):
                    raise ValueError('JSON pointer evidence differs')
        except (ValueError, OSError, KeyError, IndexError, TypeError):
            invalid.append({'evidence_id': ref['evidence_id'], 'reason': 'missing_or_invalid_original_evidence'})
    return {'checked': len(refs), 'invalid': invalid, 'invalid_count': len(invalid)}
