import networkx as nx
import pytest

from dataforge.ai_analysis_models import (
    FileExtraction,
    OperationRecord,
    ResourceReference,
    SourceReference,
)
from dataforge.ai_linking import (
    build_operation_graph,
    link_file_extractions,
    to_publication_results,
    upstream_operations,
)


def op(name, reads=(), writes=(), order=None):
    return OperationRecord(operation_id=name, kind='UPDATE', order=order,
        evidence=[SourceReference(file_id='f', content_hash='h', start_offset=0, end_offset=10)],
        reads=[ResourceReference(name=n) for n in reads], writes=[ResourceReference(name=n) for n in writes])

def extracted(operations):
    return FileExtraction(file_id='f', content_hash='h', source_kind='sql', part_ids=['p'], operations=operations)

def test_case_sensitive_graph_and_publication_share_identity():
    files = [extracted([op('upper', writes=['Sales']), op('lower', ['sales'], ['out'])])]
    linked = link_file_extractions(files, {'case_sensitive': True})
    assert upstream_operations(linked.graph, 'out').operation_ids == ['lower']
    published = to_publication_results(linked, {'f': {'source_text': '0123456789'}})
    assert published[0][1].operations[0].targets[0].identity == 'Sales'
    assert published[0][1].operations[1].sources[0].identity == 'sales'
    assert upstream_operations(link_file_extractions(files, {}).graph, 'out').operation_ids == ['lower', 'upper']

def test_standalone_in_place_update_has_unresolved_before_version_without_cycle():
    graph = build_operation_graph([extracted([op('update', ['t'], ['t'])])])
    result = upstream_operations(graph, 't')
    assert not result.cycles
    assert result.unresolved and result.execution_order is None
    assert len(result.resource_ids) == 2
    assert not nx.has_path(graph, 'operation:update', result.external_inputs[0])

def test_successive_unversioned_writes_use_established_previous_producer():
    graph = build_operation_graph([extracted([op('create', writes=['t'], order=0),
        op('update1', ['t'], ['t'], 1), op('update2', ['t'], ['t'], 2)])])
    result = upstream_operations(graph, 't@update2')
    assert not result.cycles and not result.unresolved
    assert result.execution_order == ['create', 'update1', 'update2']

def test_source_order_constraints_are_enforced_without_identifier_tiebreaks():
    operations = [op('z_first', writes=['x'], order=0), op('a_second', writes=['y'], order=1),
                  op('final', ['x', 'y'], ['out'], 2), op('unrelated', writes=['elsewhere'], order=3)]
    for records in (operations, list(reversed(operations))):
        result = upstream_operations(build_operation_graph([extracted(records)]), 'out')
        assert result.execution_order == ['z_first', 'a_second', 'final']
        assert 'unrelated' not in result.operation_ids

def test_conflicting_dependency_and_source_order_is_not_executable():
    early, late = op('early', writes=['out'], order=0), op('late', order=1)
    early.reads = [ResourceReference(name='x', version='1')]
    late.writes = [ResourceReference(name='x', version='1')]
    graph = build_operation_graph([extracted([early, late])])
    result = upstream_operations(graph, 'out')
    assert result.execution_order is None
    assert result.cycles

@pytest.mark.parametrize('name', ['"Sales"', '`Sales`', '[Sales]'])
def test_quoted_identity_survives_both_case_policies(name):
    files = [extracted([op('quoted', writes=[name])])]
    for sensitive in (True, False):
        assert name in link_file_extractions(files, {'case_sensitive': sensitive}).graph

def test_explicit_and_job_scoped_identities_survive_case_policy():
    operation = op('scoped')
    operation.writes = [ResourceReference(name='Sales', identity='catalog:Exact'),
                        ResourceReference(name='WORK.Sales', temporary=True),
                        ResourceReference(name='Sales', scope='namespace')]
    for sensitive in (True, False):
        graph = link_file_extractions([extracted([operation])], {'case_sensitive': sensitive}).graph
        assert 'catalog:Exact' in graph
        assert any(d.get('identity', '').endswith('\x1fjob\x1ff') for _, d in graph.nodes(data=True))
        assert any(d.get('identity', '').endswith('\x1fjob\x1fnamespace') for _, d in graph.nodes(data=True))
