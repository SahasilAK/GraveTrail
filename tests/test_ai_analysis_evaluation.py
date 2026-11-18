"""The evaluator counts errors and abstentions; it cannot certify mocks as live quality."""
import json

import pytest

from scripts.benchmark_ai_analysis import evaluate


def test_offline_default_never_loads_provider_and_reports_insufficient_live_evidence(monkeypatch):
    monkeypatch.setattr("dataforge.llm.Adapter.complete", lambda *a, **k: pytest.fail("offline called provider"))
    report = evaluate()
    assert report["source"] == "parser_baseline" and report["requests"] == 0
    assert report["languages"]["sql"]["table_edges"]["tp"] > 0
    assert report["languages"]["sql"]["value_dependencies"]["fn"] == 0
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


def test_live_requires_boolean_environment_before_credentials_or_network(monkeypatch):
    monkeypatch.delenv("DATAFORGE_AI_BENCHMARK_LIVE", raising=False)
    with pytest.raises(ValueError, match="DATAFORGE_AI_BENCHMARK_LIVE"):
        evaluate(live=True)


def install_mock_benchmark(monkeypatch, *, truncated=False):
    import httpx

    from dataforge.llm import Adapter
    monkeypatch.setenv('DATAFORGE_AI_BENCHMARK_LIVE', '1')
    monkeypatch.setenv('DATAFORGE_AI_BENCHMARK_CONTEXT_TOKENS', '70000')
    monkeypatch.setenv('DATAFORGE_OMNIROUTE_API_KEY', 'synthetic-test-secret')
    seen = []
    original = Adapter.__init__
    def provider(request):
        context = json.loads(json.loads(request.content)['messages'][-1]['content'])
        assert 'expected' not in context and 'gold' not in context
        for item in context['items']:
            assert 'value_inputs' not in item['source']
            seen.append(item['part']['part_id'])
        result = {'items': [{'part_id': item['part']['part_id'], 'coverage': 'partial'} for item in context['items']]}
        content = json.dumps(result)
        if truncated:
            # Quarantine requires an actually incomplete item: a parseable
            # length-flagged item is independently valid under partial recovery.
            content = content[:content.index('"coverage"')]
        return httpx.Response(200, json={'choices': [{'message': {'content': content},
            'finish_reason': 'length' if truncated else 'stop'}], 'usage': {'prompt_tokens': 11, 'completion_tokens': 23}})
    def initialize(self, profile, *args, **kwargs):
        kwargs['transport'] = httpx.MockTransport(provider)
        original(self, profile, *args, **kwargs)
    monkeypatch.setattr(Adapter, '__init__', initialize)
    return seen


def test_live_harness_uses_current_independent_pipeline_without_gold_disclosure(monkeypatch):
    seen = install_mock_benchmark(monkeypatch)
    report = evaluate(live=True, case_ids=['constant'])
    assert report['requests'] == 1 and len(seen) == 1
    assert set(report['mode_comparison']) == {'parser', 'ai'}
    assert report['languages']['sql']['table_edges']['precision'] is None
    assert 'synthetic-test-secret' not in json.dumps(report)
