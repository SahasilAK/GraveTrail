import pytest
from pydantic import ValidationError

from dataforge.ai_analysis_models import (
    AnalysisRequest,
    AnalysisUnit,
    DerivationCandidate,
    EvidenceCitation,
    LineageReviewResponse,
    ProjectLineageResponse,
)


def unit():
    return AnalysisUnit(unit_id='unit', file_id='file', content_hash='hash', path='a.sql', extension='.sql', job_id='', first=1,last=1,start_offset=0,end_offset=9,code='select 1;')


def test_request_strict_and_bounded():
    assert AnalysisRequest(mode='hybrid').max_provider_attempts is None
    for values in ({'mode':'other'}, {'max_seconds':1}, {'max_provider_attempts':True}, {'surprise':1}):
        with pytest.raises(ValidationError):
            AnalysisRequest(**values)


def test_immutable_units_and_exact_citations():
    u = unit()
    with pytest.raises(ValidationError):
        u.code = 'changed'
    evidence = EvidenceCitation.from_unit(u)
    assert evidence.quote == u.code
    evidence.assert_unit(u)
    with pytest.raises(ValueError):
        evidence.model_copy(update={'quote':'select'}).assert_unit(u)


def test_response_unit_accounting_and_caps():
    u = unit()
    response = ProjectLineageResponse(unit_id='unit', coverage={'status':'no_operations'})
    response.assert_unit(u)
    with pytest.raises(ValueError):
        response.assert_unit(u.model_copy(update={'unit_id':'different'}))
    with pytest.raises(ValidationError):
        ProjectLineageResponse(unit_id='unit', unresolved_symbols=['x'] * 101)


def test_review_requires_exact_candidate_decisions():
    result = LineageReviewResponse(decisions=[{'candidate_id':'a','decision':'insufficient_evidence','evidence':[]}])
    result.assert_candidates({'a'})
    with pytest.raises(ValueError):
        result.assert_candidates({'b'})
    with pytest.raises(ValidationError):
        LineageReviewResponse(decisions=[{'candidate_id':'a','decision':'supported','evidence':[]}] * 2)


def test_review_verdict_needs_original_evidence():
    with pytest.raises(ValidationError):
        LineageReviewResponse(decisions=[{'candidate_id':'a','decision':'supported','evidence':[]}])


def test_host_locates_only_unique_exact_expression_when_offsets_omitted():
    evidence = EvidenceCitation.from_unit(unit())
    values = dict(target_table='out', target_column='flag', expression='1', category='constant', evidence=evidence)
    claim = DerivationCandidate(**values)
    assert (claim.expression_start_offset, claim.expression_end_offset) == (7, 8)
    # Explicit wrong coordinates, ambiguous text and absent text remain rejected.
    with pytest.raises(ValidationError):
        DerivationCandidate(**values, expression_start_offset=0, expression_end_offset=1)
    for code in ('select 1,1;', 'select 2;'):
        other = unit().model_copy(update={'code': code, 'end_offset': len(code)})
        with pytest.raises(ValidationError):
            DerivationCandidate(**(values | {'evidence': EvidenceCitation.from_unit(other)}))
    with pytest.raises(ValidationError):
        DerivationCandidate(**values, expression_start_offset=7)


def test_holdout_fixture_labels_are_separate_from_prompt_examples():
    import json
    from pathlib import Path
    folder=Path(__file__).parent/'fixtures'/'ai_analysis'
    gold=json.loads((folder/'expected.json').read_text())
    assert gold['version']==1 and len(gold['cases'])>=14
    assert {case['language'] for case in gold['cases']}=={'sql','sas'}
    for case in gold['cases']:
        assert case['split']=='holdout' and (folder/case['source']).is_file()
        assert 'abstentions' in case['expected']
