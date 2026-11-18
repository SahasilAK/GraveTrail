
from scripts.qualify_ai_context import evaluate


def test_semantic_oracle_detects_omission_despite_complete_model_json():
    report = evaluate(files=3, omit=True, interrupt=False, oversized=False)
    assert report['processed_coverage'] == 1.
    assert report['semantic_metrics']['table']['missing'] == 1
    assert report['semantic_metrics']['column']['missing'] == 2
    assert report['semantic_metrics']['file']['missing'] >= 1
