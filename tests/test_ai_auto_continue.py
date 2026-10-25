from scripts.qualify_ai_context import evaluate


def test_one_start_processes_many_files_without_execution_rollover():
    report = evaluate(files=25, oversized=False, interrupt=False)
    assert report['source_files'] == report['parts'] == 25
    assert report['semantic_metrics']['table']['correct'] == 25
    assert report['semantic_metrics']['file']['correct'] == 24
    assert report['processed_coverage'] == 1.
