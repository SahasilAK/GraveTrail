import pytest

from dataforge.ai_analysis_models import (
    ExtractedDerivation,
    ExtractedUsage,
    FileExtraction,
    OperationRecord,
    ResourceReference,
    SourceReference,
)
from dataforge.ai_analysis_store import load_file_extractions, save_file_extraction, save_run
from dataforge.ai_linking import link_file_extractions, to_publication_results
from dataforge.configuration import ParsingSettings
from dataforge.ingestion import Importer
from dataforge.services import publish_analysis_results
from dataforge.store import Store


def fixture(metadata, case):
    fid, digest = metadata['file_id'], metadata['content_hash']
    ref = SourceReference(file_id=fid, content_hash=digest, start_offset=0, end_offset=10)
    first = OperationRecord(operation_id='create', kind='CREATE', order=0, evidence=[ref], writes=[ResourceReference(name='t')])
    update = OperationRecord(operation_id='update', kind='UPDATE', order=1, evidence=[ref],
        reads=[ResourceReference(name='t')], writes=[ResourceReference(name='t')])
    scope, table, expected = '', 't', 't@create'
    if case == 'explicit':
        first.writes[0].version = '1'
        update.reads[0].version, update.writes[0].version = '1', '2'
        expected = 't@1'
    if case in {'scoped', 'ambiguous'}:
        update.reads = [ResourceReference(name='t', scope=s) for s in ('left', 'right')]
        update.writes = [ResourceReference(name='out')]
        scope = 'left' if case == 'scoped' else ''
        expected = 't\x1fjob\x1fleft' if scope else None
    if case == 'case_sensitive':
        update.reads = [ResourceReference(name=n) for n in ('Sales', 'sales')]
        update.writes = [ResourceReference(name='Sales')]
        table, expected = 'Sales', 'Sales@external-before:update'
    update.usages = [ExtractedUsage(table=table, column='amount', scope=scope, context='value', evidence=[ref])]
    update.derivations = [ExtractedDerivation.model_validate({'fact_id': 'amount', 'target_table': update.writes[0].name, 'target_column': 'amount',
        'inputs': [{'table': table, 'column': 'amount', 'scope': scope, 'role': role} for role in ('value', 'row_filter')],
        'evidence': [ref]})]
    # Validate typed nested fixtures without invoking a model or static parser.
    update = OperationRecord.model_validate(update.model_dump())
    file = FileExtraction(file_id=fid, content_hash=digest, source_kind='sql', part_ids=['p'],
        operations=[first, update], semantic_coverage='model_reported_complete')
    return file, expected


@pytest.mark.parametrize('case', ['implicit', 'explicit', 'scoped', 'case_sensitive', 'ambiguous'])
def test_usage_and_derivation_identity_survive_publication_and_reopen(tmp_path, case):
    store = Store(tmp_path)
    w = store.create_workspace(case)
    Importer(store, w).files([('f.sql', b'0123456789')], {'.sql'})
    metadata = store.files(w)[0]
    file, expected = fixture(metadata, case)
    save_run(store, w, 'saved', mode='ai')
    save_file_extraction(store, w, 'saved', file)
    config = ParsingSettings(case_sensitive=True).model_dump()
    inventory = {file.file_id: {**metadata, 'source_text': '0123456789'}}
    linked = link_file_extractions([file], config)
    published = to_publication_results(linked, inventory)
    update = published[0][1].operations[1]
    usage = update.usages[0]
    if expected:
        assert usage.table_identity == expected
        assert {i['table_identity'] for i in update.derivations[0]['inputs']} == {expected}
    else:
        assert usage.status == 'unresolved'
        assert usage.table_identity not in {s.identity for s in update.sources}
        assert update.derivations[0]['status'] == 'unresolved'
    assert [i['role'] for i in update.derivations[0]['inputs']] == ['value', 'row_filter']
    assert update.derivations[0]['target_identity'] == update.targets[0].identity
    publish_analysis_results(store, w, published, config, {})
    rows = store.rows('SELECT a.canonical_name,u.status FROM column_usages u JOIN assets a USING(asset_id)')
    assert rows == [{'canonical_name': usage.table_identity, 'status': usage.status}]
    deps = store.rows('''SELECT a.canonical_name,d.role FROM column_dependencies d
        JOIN column_references r ON d.source_column_id=r.column_id JOIN assets a USING(asset_id) ORDER BY d.ordinal''')
    assert [r['canonical_name'] for r in deps] == [i['table_identity'] for i in update.derivations[0]['inputs']]
    store.close()
    store = Store(tmp_path)
    rebuilt = to_publication_results(link_file_extractions(load_file_extractions(store, w, 'saved'), config), inventory)
    assert [p.to_dict() for _, p in rebuilt] == [p.to_dict() for _, p in to_publication_results(linked, inventory)]
    store.close()


def test_duplicate_writer_saved_rebuild_and_persisted_ambiguity(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('conflict')
    Importer(store, w).files([('f.sql', b'0123456789')], {'.sql'})
    metadata = store.files(w)[0]
    file, _ = fixture(metadata, 'explicit')
    file.operations[1].writes[0].version = '1'
    save_run(store, w, 'saved', mode='ai')
    save_file_extraction(store, w, 'saved', file)
    inventory = {file.file_id: {**metadata, 'source_text': '0123456789'}}
    config = ParsingSettings().model_dump()
    linked = link_file_extractions([file], config)
    before = to_publication_results(linked, inventory)
    assert before[0][1].operations[1].usages[0].status == 'unresolved'
    assert before[0][1].operations[1].derivations[0]['status'] == 'unresolved'
    snapshot = [p.to_dict() for _, p in before]
    publish_analysis_results(store, w, before, config, {})
    assert {e['status'] for e in store.edges(w)} == {'unresolved'}
    assert {r['status'] for r in store.rows('SELECT status FROM column_derivations')} == {'unresolved'}
    store.close()
    store = Store(tmp_path)
    after = to_publication_results(link_file_extractions(load_file_extractions(store, w, 'saved'), config), inventory)
    assert snapshot == [p.to_dict() for _, p in after]
    store.close()
