"""Small extraction-specific helpers; durable state lives in the existing run journal."""
from time import monotonic, sleep

from dataforge.ai_analysis_models import SourceReference
from dataforge.models import stable_id


def recovery_wait(seconds, check):
    """Wait between passes without holding an HTTP slot; Stop stays responsive."""
    until = monotonic() + seconds
    while True:
        check()
        remaining = until - monotonic()
        if remaining <= 0:
            return
        sleep(min(.2, remaining))


def validation_failure(exc):
    # These are host-owned literals, not exception messages from providers/schema.
    paths = {'unexpected_extraction_part': 'part_id', 'invalid_source_reference': 'evidence',
        'missing_source_reference': 'evidence', 'operation_missing_own_source_reference': 'operations.evidence',
        'unknown_dbt_resource_identity': 'operations.reads.identity',
        'conflicting_operation_identity': 'operations.operation_id',
        'unknown_superseded_fact': 'superseded_fact_ids', 'unknown_superseded_operation': 'superseded_operation_ids'}
    code = str(exc)
    return {'code': code if code in paths else 'invalid_source_or_internal_reference', 'path': paths.get(code, '')}


def response_metadata(metadata, usage):
    """Allowlist diagnostic values; custom provider fields may echo arbitrary text."""
    finishes = {'stop', 'end_turn', 'STOP', 'length', 'max_tokens', 'MAX_TOKENS', 'model_length',
                'tool_calls', 'stop_sequence', 'content_filter', 'SAFETY'}
    finish = metadata.get('finish_reason')
    usage = usage if isinstance(usage, dict) else {}
    usage = {k: v for k, v in usage.items() if k in {'input_tokens', 'output_tokens', 'prompt_tokens',
        'completion_tokens', 'promptTokenCount', 'candidatesTokenCount', 'total_tokens', 'totalTokenCount'}
        and type(v) is int and v >= 0}
    known = bool({'input_tokens', 'prompt_tokens', 'promptTokenCount'} & usage.keys() and
                 {'output_tokens', 'completion_tokens', 'candidatesTokenCount'} & usage.keys())
    return {'finish_reason': finish if isinstance(finish, str) and finish in finishes else 'other',
        'truncated': metadata.get('truncated') is True, 'usage_known': known, 'usage': usage}


def split_truncated_part(parent, source, depth):
    """One evidenced split per planned part, with exact cores and bounded context.

    Prefer a statement/line boundary. A long indivisible statement can use two
    ranges with overlap; repeated truncation of these children needs repair or a
    changed output allowance, not endless halving into meaningless fragments.
    """
    if depth or parent.work_kind != 'extraction':
        return []
    start, end = parent.start_offset, parent.end_offset
    middle = (start + end) // 2
    boundaries = [i + 1 for i in range(start, end - 1) if source.code[i] in ';\n'
                  and start + (end - start) // 4 <= i + 1 <= end - (end - start) // 4]
    if boundaries:
        middle = min(boundaries, key=lambda i: abs(i - middle))
    elif min(middle - start, end - middle) < 256:
        return []
    children = []
    for a, b, x, y in [(start, middle, middle, min(end, middle + 256)),
                          (middle, end, max(start, middle - 256), middle)]:
        overlap = SourceReference(file_id=parent.file_id, content_hash=parent.content_hash, start_offset=x, end_offset=y)
        children.append(parent.model_copy(update={
            'part_id': stable_id('extraction5', parent.file_id, parent.content_hash, str(a), str(b)),
            'start_offset': a, 'end_offset': b, 'overlap': [*parent.overlap, overlap]}))
    return children
