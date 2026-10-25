"""The reported first_test selection must not carry an entire unrelated estate."""
import json
from pathlib import Path
from zipfile import ZipFile

import httpx

from dataforge.assistance_queue import preview_review, request_review
from dataforge.ingestion import Importer
from dataforge.llm import Profile, prepare_assistance
from dataforge.model_capabilities import ModelCapabilities, bind_capabilities
from dataforge.services import analyze
from dataforge.store import Store

ARCHIVE = Path('tests/sample_data/banking_legacy_sql_2114_lineage_stress_test.zip')
REPORTED_FILE = '09_vendor_dialects/mysql/mysql_004_treasury_treasury_positions.sql'


def test_reported_mysql_range_with_full_banking_estate(tmp_path):
    store = Store(tmp_path)
    try:
        w = store.create_workspace('first_test replay')
        with ZipFile(ARCHIVE) as archive:
            Importer(store, w).files(((name, archive.read(name)) for name in archive.namelist()
                                     if name.endswith(('.sql', '.csv'))), {'.sql', '.csv'})
        analyze(store, w)
        source = next(f for f in store.files(w) if f['relative_path'] == REPORTED_FILE)
        profile = Profile(provider='LM Studio', base_url='http://localhost:1234/v1', model='qwen3.5-4b',
                          output_mode='automatic', source_limit_policy='token_capacity')
        profile.model_capabilities = bind_capabilities(ModelCapabilities(context_tokens=107520, source='manual'), profile)
        store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['reported', w, 'reported', profile.model_dump_json()])
        store.set_setting(w, 'task_models', {'sql_lineage': 'reported'})
        item = store.rows('SELECT diagnostic_id FROM diagnostics WHERE workspace_id=? AND file_id=? AND severity IN (?,?)',
                          [w, source['file_id'], 'warning', 'error'])[0]
        result = preview_review(store, w, item['diagnostic_id'], 1, 13)
        budget = result['budget']
        assert budget['input_allowance'] == 71501 and budget['reserved_output'] == 30643
        assert budget['fits'], budget
        assert budget['estimated_input_tokens'] < 10000
        assert budget['context_scope']['policy'] == 'selected_source_references'
        assert budget['context_scope']['available_assets'] > 1000
        assert budget['context_scope']['prompt_assets'] == 1
        prepared = prepare_assistance(store, w, profile, source['file_id'], 1, 13, 'sql_lineage',
                                      profile_id='reported')
        original = '\n'.join(store.file(source['file_id'])['raw_content'].splitlines())
        assert len(original) == 974 and original == result['code']
        context = json.loads(prepared['user'].split('\n', 1)[-1])
        assert context['source'] == original
        assert context['known_assets'] == ['core.treasury_treasury_positions_current']
        # The default parser has not established this MySQL target. Budgeting
        # keeps catalog context distinct from source-backed resource proposals.
        assert 'vendor_mysql.treasury_treasury_positions_004' not in prepared['known']
        assert 'core.treasury_funding_deals_current' in prepared['known']
        assert len(prepared['known']) > 1000  # Full identity context remains local.
        seen = []

        def provider(request):
            body = json.loads(request.content)
            seen.append(body)
            assert len(json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()) + 256 == budget['estimated_input_tokens']
            return httpx.Response(200, json={'choices': [{'message': {'content': '{"claims": []}'}}]})

        sent = request_review(store, w, item['diagnostic_id'], source['content_hash'], 1, 13,
                              transport=httpx.MockTransport(provider))
        assert len(seen) == 1 and sent['outcome'] == 'validated' and sent['budget'] == budget
    finally:
        store.close()
