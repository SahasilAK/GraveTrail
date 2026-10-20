"""Reconciliation matrix without providers, files, or persistence."""
import pytest

from dataforge.ai_analysis_models import ClaimDecision, ValidationReport
from dataforge.ai_reconciliation import normalize_parser_facts, reconcile_candidates
from dataforge.ai_validation import validate_project_response
from dataforge.parsers.sql import parse_sql
from tests.test_ai_analysis_validation import context, derivation, edge, response


@pytest.mark.parametrize("mode,expected", [("hybrid", 1), ("ai", 0)])
def test_parser_only_is_omission_not_contradiction(mode, expected):
    ctx = context("CREATE TABLE mart.b AS SELECT x FROM raw.a;")
    report = reconcile_candidates(parse_sql(ctx["source_text"]), ValidationReport(), mode, context=ctx)
    assert len(report.operations) == expected
    assert report.omissions and not report.conflicts


@pytest.mark.parametrize("mode,status", [("hybrid", "verified"), ("ai", "inferred")])
def test_agreement_has_one_logical_fact_both_supports_and_one_writer(mode, status):
    ctx = context("CREATE TABLE mart.b AS SELECT a.x + a.y AS total FROM raw.a a;")
    parsed = parse_sql(ctx["source_text"])
    ai = validate_project_response(response(ctx, relationships=[edge()], derivations=[derivation()]), ctx)
    report = reconcile_candidates(parsed, ai, mode, context=ctx)
    edges = [f for f in report.facts if f.kind == "table_edge"]
    assert len(edges) == 1 and edges[0].status == status and edges[0].origin == "both"
    assert len(report.operations) == 1
    assert len(report.operations[0].derivations) == 1
    assert report.operations[0].evidence_key == edges[0].evidence_key
    assert {support["origin"] for support in report.supports} == {"parser", "ai"}
    assert report.operations[0].table_pairs == [(0, 0)]


def test_same_pair_two_statements_has_two_operation_keys():
    ctx = context("CREATE TABLE mart.b AS SELECT x FROM raw.a; CREATE TABLE mart.b AS SELECT y FROM raw.a;")
    parsed = parse_sql(ctx["source_text"])
    report = reconcile_candidates(parsed, ValidationReport(), "hybrid", context=ctx)
    assert len(report.operations) == 2
    assert len({op.evidence_key for op in report.operations}) == 2


def test_ai_only_addition_stays_inferred_and_parser_gap_does_not_become_second_writer():
    ctx = context("UPDATE mart.b SET total = a.x FROM raw.a a;")
    ai = validate_project_response(response(ctx, derivations=[derivation("a.x", category="direct", inputs=[
        {"table": "raw.a", "column": "x", "role": "value"}])]), ctx)
    assert ai.accepted
    report = reconcile_candidates(parse_sql(ctx["source_text"]), ai, "hybrid", context=ctx)
    assert len(report.operations) == 1
    addition = next(f for f in report.facts if f.kind == "derivation" and f.column == "total")
    assert addition.status == "inferred" and addition.origin == "ai"
    assert report.ai_only


def test_complete_semantic_identity_handles_syntax_but_not_role_branch_or_version():
    ctx = context("CREATE TABLE mart.b AS SELECT a.x + a.y AS total FROM raw.a a;")
    parser = normalize_parser_facts(parse_sql(ctx["source_text"]), ctx)
    deriv = next(f for f in parser if f.kind == "derivation")
    ai = deriv.model_copy(deep=True, update={"expression": "A.x+A.y AS total", "origin": "ai", "status": "inferred"})
    report = reconcile_candidates(parser, ValidationReport(accepted=[ai]), "hybrid", context=ctx)
    assert not report.conflicts
    assert next(f for f in report.facts if f.kind == "derivation").origin == "both"
    for field, value in [("branch", 1), ("version", "99")]:
        distinct = ai.model_copy(deep=True, update={field: value})
        report = reconcile_candidates(parser, ValidationReport(accepted=[distinct]), "hybrid", context=ctx)
        assert len([f for f in report.facts if f.kind == "derivation"]) == 2
    changed = ai.model_copy(deep=True)
    changed.inputs[0].role = "join"
    report = reconcile_candidates(parser, ValidationReport(accepted=[changed]), "hybrid", context=ctx)
    assert report.conflicts
    assert all(f.status == "unresolved" for f in report.facts if f.kind == "derivation")
    assert all(d["status"] == "unresolved" for d in report.operations[0].derivations)


def test_unsupported_ai_criticism_does_not_demote_parser():
    ctx = context("CREATE TABLE mart.b AS SELECT x FROM raw.a;")
    ai = ValidationReport(unresolved=[ClaimDecision(candidate_id="c", reason="review disagrees", status="unresolved")])
    report = reconcile_candidates(parse_sql(ctx["source_text"]), ai, "hybrid", context=ctx)
    assert not report.conflicts
    assert all(f.status == "verified" for f in report.facts)


def test_sparse_explicit_pairs_are_reconstructed_without_cross_product():
    ctx = context("CREATE TABLE mart.b AS SELECT x FROM raw.a;")
    base = normalize_parser_facts(parse_sql(ctx["source_text"]), ctx)[0]
    other = base.model_copy(deep=True, update={"source": "raw.c", "target": "mart.d", "origin": "ai"})
    for fact in (base, other):
        host = fact.detail["operation"]
        host["sources"] = [{"name": "raw.a"}, {"name": "raw.c"}]
        host["targets"] = [{"name": "mart.b"}, {"name": "mart.d"}]
    report = reconcile_candidates([], ValidationReport(accepted=[base, other]), "ai", context=ctx)
    assert len(report.operations) == 1
    assert report.operations[0].table_pairs == [(0, 0), (1, 1)]


def test_declaration_only_and_direct_usage_survive_ai_mode_without_table_edges():
    ctx = context("CREATE TABLE fresh (id INTEGER); SELECT x FROM raw.a;")
    ai = validate_project_response(response(ctx, assets=[{"name": "fresh", "role": "declaration"}],
                                            columns=[{"table": "raw.a", "column": "x", "context": "SELECT"}]), ctx)
    report = reconcile_candidates(parse_sql(ctx["source_text"]), ai, "ai", context=ctx)
    assert any(a.name == "fresh" for a in report.assets)
    assert len(report.operations) == 2 and any(operation.usages for operation in report.operations)
    assert all(operation.table_pairs == [] for operation in report.operations)


def test_file_parser_is_scoped_to_current_unit_only():
    code = "CREATE TABLE mart.b AS SELECT x FROM raw.a;\nCREATE TABLE mart.d AS SELECT y FROM raw.c;"
    ctx = context(code)
    boundary = code.index("\n")
    ctx["unit"].update(code=code[:boundary], end_offset=boundary, last=1)
    report = reconcile_candidates(parse_sql(code), ValidationReport(), "hybrid", context=ctx)
    assert len(report.operations) == 1
    assert report.operations[0].targets[0].name == "mart.b"


def test_invalid_mode_fails_closed():
    with pytest.raises(ValueError, match="mode"):
        reconcile_candidates([], ValidationReport(), "guess")


def test_ai_mode_locally_established_conflict_cannot_bypass_parser_comparison():
    ctx = context("CREATE TABLE mart.b AS SELECT a.x + a.y AS total FROM raw.a a;")
    parser = normalize_parser_facts(parse_sql(ctx["source_text"]), ctx)
    model = next(f for f in parser if f.kind == "derivation").model_copy(deep=True)
    model.origin = "ai"
    model.inputs[0].role = "join"
    report = reconcile_candidates(parser, ValidationReport(accepted=[model]), "ai", context=ctx)
    assert report.conflicts
    assert all(f.status == "unresolved" for f in report.facts)


def test_existing_parser_uncertainty_is_not_mislabeled_as_a_conflict():
    ctx = context("CREATE TABLE mart.b AS SELECT mystery(x) AS total FROM raw.a;")
    report = reconcile_candidates(parse_sql(ctx["source_text"]), ValidationReport(), "hybrid", context=ctx)
    assert not report.conflicts
    assert "Locally established semantic conflict" not in report.operations[0].derivations[0]["coverage"]
