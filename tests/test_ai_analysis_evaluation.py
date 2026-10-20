"""The evaluator counts errors and abstentions; it cannot certify mocks as live quality."""
import json

import pytest

from scripts.benchmark_ai_analysis import evaluate, main, score_sets


def test_precision_recall_report_exact_counts_and_empty_predictions_are_unknown():
    metric = score_sets({("a",), ("invented",)}, {("a",), ("missing",)})
    assert metric == {"tp": 1, "fp": 1, "fn": 1, "predictions": 2, "expected": 2,
                      "precision": .5, "recall": .5}
    empty = score_sets(set(), {("real",)})
    assert empty["precision"] is None and empty["recall"] == 0


def test_offline_default_never_loads_provider_and_reports_insufficient_live_evidence(monkeypatch):
    monkeypatch.setattr("dataforge.llm.invoke_analysis_unit", lambda *a, **k: pytest.fail("offline called provider"))
    report = evaluate()
    assert report["source"] == "parser_baseline" and report["requests"] == 0
    assert report["languages"]["sql"]["table_edges"]["tp"] > 0
    assert report["languages"]["sql"]["value_dependencies"]["fn"] > 0  # UPDATE/MERGE parser gaps
    assert all(language["release_gate"]["status"] == "insufficient_evidence"
               for language in report["languages"].values())
    assert report["unit_coverage"]["processed"] == report["unit_coverage"]["total"]


def test_wrong_role_and_operation_are_false_predictions_not_pair_agreement():
    from scripts.benchmark_ai_analysis import score_case
    expected = {"table_edges": [[0, "a", "b"]], "direct_usages": [], "derivations": [],
                "value_dependencies": [[0, "b", "x", "", "", 0, 0, "a", "x", "", "", "value"]],
                "row_dependencies": [], "abstain": False}
    predicted = {**expected, "table_edges": [[10, "a", "b"]], "value_dependencies": [],
                 "row_dependencies": [[0, "b", "x", "", "", 0, 0, "a", "x", "", "", "join"]]}
    result = score_case(predicted, expected)
    assert result["table_edges"]["fp"] == 1 and result["table_edges"]["fn"] == 1
    assert result["value_dependencies"]["fn"] == 1 and result["row_dependencies"]["fp"] == 1


def test_external_predictions_are_not_live_evidence_and_no_predictions_are_insufficient(tmp_path):
    path = tmp_path / "predictions.json"
    path.write_text(json.dumps({"predictions": {}}))
    report = evaluate(predictions=path)
    assert report["source"] == "saved_predictions"
    assert all(language["table_edges"]["precision"] is None for language in report["languages"].values())
    assert all(language["release_gate"]["status"] == "insufficient_evidence"
               for language in report["languages"].values())


def test_live_requires_boolean_environment_before_credentials_or_network(monkeypatch):
    monkeypatch.delenv("DATAFORGE_AI_BENCHMARK_LIVE", raising=False)
    with pytest.raises(ValueError, match="DATAFORGE_AI_BENCHMARK_LIVE"):
        evaluate(live=True)


def test_main_prints_sanitized_summary_and_writes_explicit_output(tmp_path, capsys):
    path = tmp_path / "metrics.json"
    assert main(["--output", str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert json.loads(path.read_text()) == report
    assert "source_text" not in path.read_text() and "quote" not in path.read_text()


def test_live_requires_explicit_selected_fixture_ids(monkeypatch):
    monkeypatch.setenv("DATAFORGE_AI_BENCHMARK_LIVE", "1")
    with pytest.raises(ValueError, match="selected fixture"):
        evaluate(live=True)
    with pytest.raises(ValueError, match="Unknown fixture"):
        evaluate(case_ids=["private-project.sql"])


def test_gold_operation_offsets_and_two_job_identities_are_scored_independently():
    report = evaluate(case_ids=["same_line", "temporary_jobs:one", "temporary_jobs:two"])
    assert report["languages"]["sql"]["table_edges"]["tp"] == 2
    assert report["languages"]["sas"]["table_edges"]["tp"] == 2
    assert report["unit_coverage"]["total"] == 4


def test_both_project_archives_keep_manifest_edges_roots_and_work_behavior():
    from scripts.benchmark_ai_analysis import evaluate_projects

    report = evaluate_projects()
    assert set(report) == {"sql", "sas"}
    for language in report.values():
        assert language["logical_edges"]["tp"] == 128
        assert language["logical_edges"]["fp"] == language["logical_edges"]["fn"] == 0
        assert language["persistent_tables"] == 85 and language["upstream_roots"] == 16
        assert language["requests"] == 0
    assert report["sas"]["work_tables"] == 16


def test_live_harness_mock_receives_original_only_and_compares_three_modes(monkeypatch):
    from dataforge.ai_analysis_models import Coverage, ProjectLineageResponse, UnitAttemptResult

    monkeypatch.setenv("DATAFORGE_AI_BENCHMARK_LIVE", "1")
    monkeypatch.setenv("DATAFORGE_OMNIROUTE_API_KEY", "synthetic-test-secret")

    def fake(store, workspace, unit, task, execution):
        assert task == "project_lineage" and "create table" in unit.code.lower()
        assert "expected" not in unit.code and "value_inputs" not in unit.code
        assert all("edges" not in entry and "derivations" not in entry for entry in execution.catalog)
        execution.attempts += 1
        return UnitAttemptResult(unit_id=unit.unit_id, task=task,
            result=ProjectLineageResponse(unit_id=unit.unit_id, coverage=Coverage(status="partial")))

    monkeypatch.setattr("dataforge.llm.invoke_analysis_unit", fake)
    report = evaluate(live=True, case_ids=["constant"])
    assert report["requests"] == 1 and report["input_tokens"] is None
    assert set(report["mode_comparison"]) == {"parser", "ai", "hybrid"}
    assert report["mode_comparison"]["hybrid"]["sql"]["table_edges"]["tp"] == 1
    assert report["languages"]["sql"]["table_edges"]["precision"] is None
    assert "synthetic-test-secret" not in json.dumps(report)


def test_live_harness_two_cases_have_distinct_profile_identities(monkeypatch):
    from dataforge.ai_analysis_models import ProjectLineageResponse, UnitAttemptResult
    monkeypatch.setenv('DATAFORGE_AI_BENCHMARK_LIVE', '1')
    monkeypatch.setenv('DATAFORGE_OMNIROUTE_API_KEY', 'synthetic-test-secret')
    monkeypatch.setattr('dataforge.llm.invoke_analysis_unit', lambda store, workspace, unit, task, execution:
        UnitAttemptResult(unit_id=unit.unit_id, task=task,
                          result=ProjectLineageResponse(unit_id=unit.unit_id)))
    report = evaluate(live=True, case_ids=['constant', 'assignments'])
    assert report['case_coverage']['processed'] == 2
