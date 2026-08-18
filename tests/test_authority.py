import hashlib
import json

import pytest

from gateway.authority import AuthorityGate, PrivilegedExecutor, TPA, Verdict, VerdictCode


class World:
    def __init__(self):
        self.record = {
            'plan': 'pro',
            'status': 'active',
            'stripe_customer_id': 'cus_123',
            'contact_email': 'ops@example.com',
            'deployment_namespace': 'cust-123',
        }

    def get(self, customer_id):
        return self.record if customer_id == 'cust_1' else None

    def compute_hash(self, customer_id):
        record = self.get(customer_id)
        if record is None:
            return None
        raw = json.dumps(record, sort_keys=True, separators=(',', ':')).encode()
        return hashlib.sha256(raw).hexdigest()


class Sessions:
    def __init__(self, authenticated=True, registered=True, customer='cust_1'):
        self.authenticated = authenticated
        self.registered = registered
        self.customer = customer

    def is_event_authenticated(self, event_id):
        return self.authenticated

    def get_customer_for_event(self, event_id):
        return self.customer

    def is_agent_registered(self, agent_id, session_id):
        return self.registered


def valid_tpa(world):
    return TPA(
        action_id='act_1',
        requested_by='agent_1::sess_1',
        originating_event='evt_1',
        action_class='DEPLOYMENT',
        destination='cust-123',
        confidence=0.99,
        reversibility='reversible',
        scope={'environment': 'production'},
        world_state_hash=world.compute_hash('cust_1'),
    )


def test_authorized():
    world = World()
    verdict = AuthorityGate(world, Sessions()).validate(valid_tpa(world))
    assert verdict.verdict == 'AUTHORIZED'
    assert verdict.code is VerdictCode.AUTHORIZED
    assert all(v == 'PASS' for v in verdict.checks.values())


def test_unknown_event_rejected():
    world = World()
    verdict = AuthorityGate(world, Sessions(authenticated=False)).validate(valid_tpa(world))
    assert verdict.code is VerdictCode.IDENTITY_UNVERIFIED


def test_unregistered_agent_rejected():
    world = World()
    verdict = AuthorityGate(world, Sessions(registered=False)).validate(valid_tpa(world))
    assert verdict.code is VerdictCode.IDENTITY_UNVERIFIED


def test_inactive_customer_rejected():
    world = World()
    tpa = valid_tpa(world)
    world.record['status'] = 'suspended'
    verdict = AuthorityGate(world, Sessions()).validate(tpa)
    assert verdict.code is VerdictCode.SCOPE_EXCEEDED


def test_starter_production_scope_rejected():
    world = World()
    world.record['plan'] = 'starter'
    tpa = TPA(**{**valid_tpa(world).__dict__, 'world_state_hash': world.compute_hash('cust_1')})
    verdict = AuthorityGate(world, Sessions()).validate(tpa)
    assert verdict.code is VerdictCode.SCOPE_EXCEEDED


def test_destination_rejected():
    world = World()
    tpa = TPA(**{**valid_tpa(world).__dict__, 'destination': 'attacker.example'})
    verdict = AuthorityGate(world, Sessions()).validate(tpa)
    assert verdict.code is VerdictCode.DESTINATION_INVALID


def test_confidence_rejected():
    world = World()
    tpa = TPA(**{**valid_tpa(world).__dict__, 'confidence': 0.50})
    verdict = AuthorityGate(world, Sessions()).validate(tpa)
    assert verdict.code is VerdictCode.LOW_CONFIDENCE


def test_stale_world_state_rejected():
    world = World()
    tpa = valid_tpa(world)
    world.record['contact_email'] = 'changed@example.com'
    verdict = AuthorityGate(world, Sessions()).validate(tpa)
    assert verdict.code is VerdictCode.STALE_WORLD_STATE


def test_unknown_customer_rejected():
    world = World()
    verdict = AuthorityGate(world, Sessions(customer='missing')).validate(valid_tpa(world))
    assert verdict.code is VerdictCode.SCOPE_EXCEEDED


def test_privileged_executor_rejects_rejected_verdict():
    class Provider:
        def __init__(self):
            self.called = False

        def execute(self, tpa):
            self.called = True

    provider = Provider()
    executor = PrivilegedExecutor(provider)
    verdict = Verdict('act_1', 'REJECTED', VerdictCode.DESTINATION_INVALID, 'blocked', {}, {})

    with pytest.raises(PermissionError):
        executor.execute(verdict)

    assert provider.called is False


def test_privileged_executor_allows_authorized_verdict():
    class Provider:
        def execute(self, tpa):
            return {'executed': True, 'action_id': tpa['action_id']}

    executor = PrivilegedExecutor(Provider())
    verdict = Verdict('act_1', 'AUTHORIZED', VerdictCode.AUTHORIZED, 'all checks passed', {}, {'action_id': 'act_1'})
    assert executor.execute(verdict) == {'executed': True, 'action_id': 'act_1'}
