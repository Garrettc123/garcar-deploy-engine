import hashlib
import json

from gateway.authority import AuthorityGate, TPA, VerdictCode


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
        if self.get(customer_id) is None:
            return None
        raw = json.dumps(self.record, sort_keys=True, separators=(',', ':')).encode()
        return hashlib.sha256(raw).hexdigest()


class Sessions:
    def __init__(self, authenticated=True, registered=True):
        self.authenticated = authenticated
        self.registered = registered

    def is_event_authenticated(self, event_id):
        return self.authenticated

    def get_customer_for_event(self, event_id):
        return 'cust_1'

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


def test_scope_rejected():
    world = World()
    tpa = valid_tpa(world)
    tpa = TPA(**{**tpa.__dict__, 'scope': {'environment': 'production'}})
    world.record['plan'] = 'starter'
    verdict = AuthorityGate(world, Sessions()).validate(tpa)
    assert verdict.code is VerdictCode.SCOPE_EXCEEDED


def test_destination_rejected():
    world = World()
    tpa = valid_tpa(world)
    tpa = TPA(**{**tpa.__dict__, 'destination': 'attacker.example'})
    verdict = AuthorityGate(world, Sessions()).validate(tpa)
    assert verdict.code is VerdictCode.DESTINATION_INVALID


def test_confidence_rejected():
    world = World()
    tpa = valid_tpa(world)
    tpa = TPA(**{**tpa.__dict__, 'confidence': 0.50})
    verdict = AuthorityGate(world, Sessions()).validate(tpa)
    assert verdict.code is VerdictCode.LOW_CONFIDENCE


def test_stale_world_state_rejected():
    world = World()
    tpa = valid_tpa(world)
    world.record['status'] = 'suspended'
    verdict = AuthorityGate(world, Sessions()).validate(tpa)
    assert verdict.code is VerdictCode.STALE_WORLD_STATE
