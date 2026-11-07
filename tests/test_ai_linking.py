from dataforge.ai_analysis_models import DerivationInput, EvidenceCitation, NormalizedFact


def fact(unit, table, column, inputs, identity=''):
    return NormalizedFact(kind='derivation', unit_id=unit, evidence_key=unit, table=table, column=column,
        expression=column, inputs=[DerivationInput(table=t, column=c) for t, c in inputs],
        evidence=EvidenceCitation(unit_id=unit, file_id=unit, content_hash='h', start_line=1, end_line=1,
                                  start_offset=0, end_offset=1, quote='x'),
        detail={'operation': {'sources': [], 'targets': [{'name': table, 'identity': identity}]}})


def test_stored_column_facts_link_without_guessing_multiple_writers():
    from dataforge.ai_linking import link_stored_facts
    facts = [fact('a', 'stage.b', 'x', [('raw.a', 'x')]), fact('b', 'mart.c', 'y', [('stage.b', 'x')])]
    linked = link_stored_facts(facts)
    assert linked['column_links'] == [{'producer': 'a', 'consumer': 'b', 'table': 'stage.b', 'column': 'x', 'role': 'value'}]
    linked = link_stored_facts([*facts, fact('other-writer', 'stage.b', 'x', [])])
    assert not linked['column_links']
    assert linked['unresolved'][0]['reason'] == 'multiple_writers_without_execution_order'


def test_dbt_identity_and_contextual_roles_are_preserved():
    from dataforge.ai_linking import link_stored_facts
    producer = fact('a', 'model', 'x', [], identity='dbt:project-one:model')
    consumer = fact('b', 'target', 'y', [('model', 'x')])
    consumer.detail['operation']['sources'] = [{'name': 'model', 'identity': 'dbt:project-two:model'}]
    assert not link_stored_facts([producer, consumer])['column_links']
