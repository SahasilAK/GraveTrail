
import pytest

from dataforge.agent.contracts import AccessPolicy, AgentError


def test_independent_permissions_and_scoped_admin() -> None:
    """Verify that independent permissions and scoped admin."""
    policy = AccessPolicy(allow_write=True)
    for operation in ('config', 'network', 'application', 'admin'):
        with pytest.raises(AgentError):
            policy.require(operation)
    scoped = AccessPolicy(allow_write=True, allow_config_write=True, allow_admin=True, workspaces=('one',))
    with pytest.raises(AgentError):
        scoped.require('admin')
