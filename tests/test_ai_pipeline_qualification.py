import pytest

from scripts.qualify_ai_context import evaluate


@pytest.mark.parametrize('family', ['sql', 'sas', 'dbt'])
def test_golden_transport_recovers_exact_relationships_with_interruption(family):
    report = evaluate(family=family, files=12)
    assert report['qualification'] == 'deterministic_mock'
    assert report['live_model_accuracy'] == 'pending'
    assert report['processed_coverage'] == 1.
    assert report['parts'] > report['source_files']
    assert report['interrupted_and_resumed']
    assert all(m['precision'] == m['recall'] == 1 for m in report['semantic_metrics'].values())


@pytest.mark.parametrize('family', ['sql', 'sas', 'dbt'])
def test_semantic_oracle_detects_omission_despite_complete_model_json(family):
    report = evaluate(family=family, files=3, omit=True, interrupt=False, oversized=False)
    assert report['processed_coverage'] == 1.
    assert report['semantic_metrics']['table']['missing'] == 1
    assert report['semantic_metrics']['column']['missing'] == 2
    assert report['semantic_metrics']['file']['missing'] >= 1


def test_larger_token_bounded_batches_and_reversed_order_preserve_golden_graph():
    small = evaluate(files=8, context_tokens=70000, output_tokens=1024, interrupt=False, oversized=False)
    large = evaluate(files=8, context_tokens=200000, output_tokens=32000, reverse=True, oversized=False)
    assert small['requests'] > large['requests']
    assert small['semantic_metrics'] == large['semantic_metrics']


def test_saved_result_decoding_scales_linearly_for_whole_files(monkeypatch):
    from dataforge.ai_analysis_models import PartExtraction
    original = PartExtraction.model_validate
    decoded = []
    def counted(cls, value, **kwargs):
        decoded.append(1)
        return original(value, **kwargs)
    monkeypatch.setattr(PartExtraction, 'model_validate', classmethod(counted))
    report = evaluate(files=30, oversized=False, interrupt=False)
    assert report['semantic_metrics']['table']['correct'] == 30
    assert len(decoded) < 30 * 20, 'Whole-file consolidation reread all saved results per file'


@pytest.mark.parametrize('family', ['sql', 'sas'])
def test_golden_duplicate_writes_remain_explicit_boundaries(family):
    result = evaluate(family=family, files=3, oversized=False, interrupt=False, duplicate_writes=True)
    assert result['semantic_metrics']['table']['correct'] == 5
    assert result['duplicate_writer_boundaries'] == 2
