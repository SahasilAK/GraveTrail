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


def test_successive_explicit_versions_preserve_upstream_order():
    ref = SourceReference(file_id='f', content_hash='h', start_offset=0, end_offset=10)
    operations = [
        OperationRecord(operation_id='first', kind='CREATE', evidence=[ref], order=0,
            writes=[ResourceReference(name='t', version='1')]),
        OperationRecord(operation_id='second', kind='UPDATE', evidence=[ref], order=1,
            reads=[ResourceReference(name='t', version='1')], writes=[ResourceReference(name='t', version='2')]),
        OperationRecord(operation_id='final', kind='CREATE', evidence=[ref], order=2,
            reads=[ResourceReference(name='t', version='2')], writes=[ResourceReference(name='out')])]
    graph = build_operation_graph([FileExtraction(file_id='f', content_hash='h', source_kind='sql', part_ids=['p'], operations=operations)])
    result = upstream_operations(graph, 'out')
    assert result.execution_order == ['first', 'second', 'final']
    assert not result.cycles


def test_sas_stateful_source_and_limitations_survive_graph_and_publication():
    from dataforge.ai_linking import link_file_extractions, to_publication_results
    code = 'data work.final; set raw.a; by id; retain total; total+amount; if last.id then output; run;'
    ref = SourceReference(file_id='f', content_hash='h', start_offset=0, end_offset=len(code))
    operation = OperationRecord(operation_id='stateful', kind='SAS_DATA', evidence=[ref],
        reads=[ResourceReference(name='raw.a')], writes=[ResourceReference(name='work.final', scope='job', temporary=True)],
        limitations=['RETAIN/BY/conditional OUTPUT is stateful; execution equivalence is unproven'])
    files = [FileExtraction(file_id='f', content_hash='h', source_kind='sas', part_ids=['p'], operations=[operation])]
    linked = link_file_extractions(files, {})
    target = next(n for n, data in linked.graph.nodes(data=True) if data.get('name') == 'work.final')
    result = upstream_operations(linked.graph, target)
    assert result.execution_order is None and result.unresolved
    published = to_publication_results(linked, {'f': {'source_text': code}})[0][1].operations[0]
    assert published.kind == 'SAS_DATA' and published.code == code
    assert published.warnings == operation.limitations
