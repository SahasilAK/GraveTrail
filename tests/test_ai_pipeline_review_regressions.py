import httpx
import pytest

from dataforge.connections import RuntimeConnections, connection_scope
from dataforge.llm import Adapter, Profile


def test_revoked_credential_is_not_sent_after_admission_wait():
    manager = RuntimeConnections()
    manager.register('DATAFORGE_REVOKED_KEY', 'synthetic-secret')
    profile = Profile(provider='OpenAI compatible', base_url='http://localhost:1234', model='m',
                      key_env='DATAFORGE_REVOKED_KEY', retries=0)
    sent = []
    def revoke(_):
        manager.clear('DATAFORGE_REVOKED_KEY')
        return 1
    def provider(r):
        sent.append(r)
        return httpx.Response(200, json={'choices': [{'message': {'content': '{}'}}]})
    with connection_scope(manager), Adapter(profile, httpx.MockTransport(provider), before_attempt=revoke) as adapter:
        with pytest.raises(ValueError, match='Credential'):
            adapter.complete('instructions', 'source')
    assert not sent
