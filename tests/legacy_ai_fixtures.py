"""Historical wire/checkpoint fixtures, independent of the retired build planner."""
from types import SimpleNamespace

from dataforge.ai_analysis_models import AnalysisUnit
from dataforge.ai_context import _unit_spans
from dataforge.models import stable_id


def legacy_units(prepared, **_):
    units = []
    for source in prepared.sources:
        for start, end in _unit_spans(source.code, source.extension):
            units.append(AnalysisUnit(unit_id=stable_id(source.file_id, source.content_hash, str(start), str(end)),
                file_id=source.file_id, content_hash=source.content_hash, path=source.path, extension=source.extension,
                job_id=source.job_id, first=source.code.count('\n', 0, start)+1,
                last=source.code.count('\n', 0, end)+1, start_offset=start, end_offset=end, code=source.code[start:end]))
    return SimpleNamespace(units=tuple(units))
