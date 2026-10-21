from dataforge.ai_analysis_models import ClaimDecision, ValidationReport


def test_resolution_is_bounded_and_never_promotes_unvalidated_claims():
    from dataforge.ai_resolution import apply_resolution, plan_resolution
    report = ValidationReport(unresolved=[ClaimDecision(candidate_id='candidate', reason='ambiguous', status='unresolved')])
    assert plan_resolution(report)['candidate_ids'] == ['candidate']
    report.resolution_rounds = 2
    assert plan_resolution(report) is None
    result, progress = apply_resolution(report, ValidationReport())
    assert not result.accepted and not progress and result.resolution_done
