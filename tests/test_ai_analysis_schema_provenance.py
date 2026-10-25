"""Accepted declarations and schema citations share real statement identities."""


from dataforge.ai_reconciliation import reconcile_candidates
from dataforge.ai_validation import validate_project_response
from dataforge.parsers.sql import parse_sql
from tests.test_ai_analysis_validation import context, response


def test_hybrid_keeps_declaration_only_operation_and_ai_requires_validated_declaration():
    ctx = context("CREATE TABLE raw.a (id INT);")
    parsed = parse_sql(ctx['source_text'])
    empty = validate_project_response(response(ctx), ctx)
    hybrid = reconcile_candidates(parsed, empty, 'hybrid', context=ctx)
    assert len(hybrid.operations) == 1 and hybrid.operations[0].evidence_key
    assert not reconcile_candidates(parsed, empty, 'ai', context=ctx).operations
    accepted = validate_project_response(response(ctx, assets=[{'name': 'raw.a', 'role': 'declaration'}]), ctx)
    ai = reconcile_candidates(parsed, accepted, 'ai', context=ctx)
    assert len(ai.operations) == 1 and ai.operations[0].table_pairs == []
    assert ai.operations[0].targets[0].name == 'raw.a'
