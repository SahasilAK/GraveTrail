"""Accepted declarations and schema citations share real statement identities."""
import json
from contextlib import closing

import pytest

from dataforge.ai_analysis_models import (
    AssetCandidate,
    EvidenceCitation,
    ProjectLineageResponse,
    UnitAttemptResult,
)
from dataforge.ai_reconciliation import reconcile_candidates
from dataforge.ai_validation import validate_project_response
from dataforge.ingestion import Importer
from dataforge.parsers.sql import parse_sql
from dataforge.services import analyze
from dataforge.store import Store
from tests.test_ai_analysis_validation import context, response


def test_selected_run_preserves_inherited_declaration_dependencies(tmp_path, monkeypatch):
    from dataforge.ai_analysis_store import load_accepted_file_results
    from dataforge.analysis_service import run_analysis
    from dataforge.llm import Profile
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('Inherited context')
        Importer(store, w).files([('ddl.sql', b'CREATE TABLE raw.a (id INT);'),
            ('q.sql', b'CREATE TABLE b AS SELECT id FROM raw.a;'),
            ('other.sql', b'CREATE TABLE c AS SELECT id FROM raw.c;')], {'.sql'})
        profile = Profile(provider='Ollama', base_url='http://localhost:11434', model='test', context_chars=100000)
        store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'test', profile.model_dump_json()])
        store.set_setting(w, 'default_profile', 'p')
        store.set_setting(w, 'max_context_chars', 100000)
        monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', lambda s, w, u, t, e:
            UnitAttemptResult(unit_id=u.unit_id, task=t, result=ProjectLineageResponse(unit_id=u.unit_id)))
        assert run_analysis(store, w, {'mode': 'hybrid'}).status == 'committed'
        ids = {f['relative_path']: f['file_id'] for f in store.files(w)}
        assert run_analysis(store, w, {'mode': 'hybrid', 'file_ids': [ids['other.sql']]}).status == 'committed'
        assert ids['q.sql'] in load_accepted_file_results(store, w)
        Importer(store, w).files([('ddl.sql', b'CREATE TABLE raw.a (id VARCHAR);')], {'.sql'})
        assert ids['q.sql'] not in load_accepted_file_results(store, w)


def test_hybrid_keeps_declaration_only_operation_and_ai_requires_validated_declaration():
    ctx = context("CREATE TABLE raw.a (id INT);")
    parsed = parse_sql(ctx['source_text'])
    empty = validate_project_response(response(ctx), ctx)
    hybrid = reconcile_candidates(parsed, empty, 'hybrid', context=ctx)
    assert len(hybrid.operations) == 1 and hybrid.operations[0].evidence_key
    assert not reconcile_candidates(parsed, empty, 'ai', context=ctx).operations
    accepted = validate_project_response(response(ctx, assets=[{'name': 'raw.a', 'role': 'declaration'}]), ctx)
    ai = reconcile_candidates(parsed, accepted, 'ai', context=ctx)
    assert len(ai.operations) == 1 and ai.operations[0].table_pairs == []
    assert ai.operations[0].targets[0].name == 'raw.a'


def test_ai_omitted_earlier_operation_does_not_misbind_later_declaration(tmp_path, monkeypatch):
    from dataforge.analysis_service import run_analysis
    from dataforge.llm import Profile
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('Sparse declaration')
        Importer(store, workspace).files([('q.sql', b'CREATE TABLE ignored AS SELECT id FROM raw.z; '
            b'CREATE TABLE raw.a (id INT);')], {'.sql'})
        profile = Profile(provider='Ollama', base_url='http://localhost:11434', model='test', context_chars=100000)
        store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', workspace, 'test', profile.model_dump_json()])
        store.set_setting(workspace, 'default_profile', 'p')
        store.set_setting(workspace, 'max_context_chars', 100000)

        def fake(store, workspace, unit, task, execution):
            claims = [] if 'ignored' in unit.code else [AssetCandidate(name='raw.a', role='declaration',
                evidence=EvidenceCitation.from_unit(unit))]
            return UnitAttemptResult(unit_id=unit.unit_id, task=task,
                result=ProjectLineageResponse(unit_id=unit.unit_id, assets=claims))
        monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', fake)
        assert run_analysis(store, workspace, {'mode': 'ai'}).status == 'committed'
        assets = {a['name']: a for a in store.assets(workspace)}
        assert 'ignored' not in assets
        schema = json.loads(assets['raw.a']['metadata'])
        assert schema['schema_status'] == 'declared'
        assert store.rows('SELECT 1 FROM statements WHERE statement_id=?', [schema['schema_evidence'][0]['statement_id']])


@pytest.mark.parametrize('mode', ['hybrid', 'ai'])
@pytest.mark.parametrize('refresh', ['initial', 'selected', 'rebuild'])
def test_schema_evidence_resolves_after_project_publication_and_refresh(tmp_path, monkeypatch, mode, refresh):
    from dataforge.analysis_service import run_analysis
    from dataforge.llm import Profile

    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('Schema evidence')
        Importer(store, workspace).files([
            ('q.sql', b'CREATE TABLE raw.a (id INT); CREATE TABLE b AS SELECT id FROM raw.a;'),
            ('other.sql', b'CREATE TABLE raw.c (code INT);')], {'.sql'})
        profile = Profile(provider='Ollama', base_url='http://localhost:11434', model='test', context_chars=100000)
        store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', workspace, 'test', profile.model_dump_json()])
        store.set_setting(workspace, 'default_profile', 'p')
        store.set_setting(workspace, 'max_context_chars', 100000)

        def fake(store, workspace, unit, task, execution):
            claims = [AssetCandidate(name=ref.name, role='declaration', evidence=EvidenceCitation.from_unit(unit))
                      for op in parse_sql(unit.code).operations for ref in op.targets]
            return UnitAttemptResult(unit_id=unit.unit_id, task=task,
                result=ProjectLineageResponse(unit_id=unit.unit_id, assets=claims))

        monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', fake)
        assert run_analysis(store, workspace, {'mode': mode}).status == 'committed'
        if refresh == 'selected':
            file_id = next(f['file_id'] for f in store.files(workspace) if f['relative_path'] == 'q.sql')
            assert run_analysis(store, workspace, {'mode': mode, 'file_ids': [file_id]}).status == 'committed'
        elif refresh == 'rebuild':
            analyze(store, workspace)
        seen = 0
        for asset in store.assets(workspace):
            for evidence in json.loads(asset['metadata']).get('schema_evidence', []):
                rows = store.rows('SELECT code FROM statements WHERE statement_id=?', [evidence['statement_id']])
                assert rows and rows[0]['code'].startswith('CREATE TABLE')
                assert asset['name'] in rows[0]['code']
                seen += 1
        assert seen >= 3
