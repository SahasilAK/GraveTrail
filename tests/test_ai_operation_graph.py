from dataforge.ai_analysis_models import FileExtraction, OperationRecord, ResourceReference, SourceReference
from dataforge.ai_linking import build_operation_graph, upstream_operations


def file(fid, reads, writes, *, order=0, limitations=()):
    evidence = [SourceReference(file_id=fid, content_hash='h', start_offset=0, end_offset=10)]
    return FileExtraction(file_id=fid, content_hash='h', source_kind='sql', part_ids=[fid], operations=[
        OperationRecord(operation_id=fid, kind='CREATE', evidence=evidence, order=order,
            reads=[ResourceReference(name=n) for n in reads], writes=[ResourceReference(name=n) for n in writes],
            limitations=list(limitations))])


def test_upstream_slice_excludes_independent_component_and_preserves_evidence():
    graph = build_operation_graph([file('a', ['external'], ['first']), file('b', ['first'], ['final']),
                                   file('unrelated', ['other'], ['independent'])])
    target = next(n for n, d in graph.nodes(data=True) if d.get('name') == 'final')
    result = upstream_operations(graph, target)
    assert result.operation_ids == ['a', 'b']
    assert len(result.references) == 2
    assert not result.unresolved
    assert len(result.external_inputs) == 1


def test_duplicate_writers_do_not_fabricate_order_or_upstream_files():
    graph = build_operation_graph([file('a', [], ['same']), file('b', [], ['same']), file('c', ['same'], ['final'])])
    target = next(n for n, d in graph.nodes(data=True) if d.get('name') == 'final')
    result = upstream_operations(graph, target)
    assert result.operation_ids == ['c']
    assert result.unresolved
    assert result.execution_order is None


def test_cycle_is_preserved_without_executable_order():
    graph = build_operation_graph([file('a', ['second'], ['first']), file('b', ['first'], ['second'])])
    target = next(n for n, d in graph.nodes(data=True) if d.get('name') == 'first')
    result = upstream_operations(graph, target)
    assert result.cycles
    assert result.execution_order is None
