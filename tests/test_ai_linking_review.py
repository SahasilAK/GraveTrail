import networkx as nx

from dataforge.ai_analysis_models import (
    FileExtraction,
    OperationRecord,
    ResourceReference,
    SourceReference,
)
from dataforge.ai_linking import (
    build_operation_graph,
    upstream_operations,
)


def op(name, reads=(), writes=(), order=None):
    return OperationRecord(operation_id=name, kind='UPDATE', order=order,
        evidence=[SourceReference(file_id='f', content_hash='h', start_offset=0, end_offset=10)],
        reads=[ResourceReference(name=n) for n in reads], writes=[ResourceReference(name=n) for n in writes])

def extracted(operations):
    return FileExtraction(file_id='f', content_hash='h', source_kind='sql', part_ids=['p'], operations=operations)


def test_standalone_in_place_update_has_unresolved_before_version_without_cycle():
    graph = build_operation_graph([extracted([op('update', ['t'], ['t'])])])
    result = upstream_operations(graph, 't')
    assert not result.cycles
    assert result.unresolved and result.execution_order is None
    assert len(result.resource_ids) == 2
    assert not nx.has_path(graph, 'operation:update', result.external_inputs[0])


def test_conflicting_dependency_and_source_order_is_not_executable():
    early, late = op('early', writes=['out'], order=0), op('late', order=1)
    early.reads = [ResourceReference(name='x', version='1')]
    late.writes = [ResourceReference(name='x', version='1')]
    graph = build_operation_graph([extracted([early, late])])
    result = upstream_operations(graph, 'out')
    assert result.execution_order is None
    assert result.cycles
