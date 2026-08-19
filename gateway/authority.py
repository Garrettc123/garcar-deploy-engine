from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class VerdictCode(str, Enum):
    AUTHORIZED = 'AUTHORIZED'
    IDENTITY_UNVERIFIED = 'IDENTITY_UNVERIFIED'
    SCOPE_EXCEEDED = 'SCOPE_EXCEEDED'
    DESTINATION_INVALID = 'DESTINATION_INVALID'
    LOW_CONFIDENCE = 'LOW_CONFIDENCE'
    STALE_WORLD_STATE = 'STALE_WORLD_STATE'


@dataclass(frozen=True)
class TPA:
    action_id: str
    requested_by: str
    originating_event: str
    action_class: str
    destination: str
    confidence: float
    reversibility: str
    scope: dict[str, Any]
    world_state_hash: str


@dataclass(frozen=True)
class Verdict:
    action_id: str
    verdict: str
    code: VerdictCode
    reason: str
    checks: dict[str, str]
    tpa: dict[str, Any]


class SessionRegistry(Protocol):
    def is_event_authenticated(self, event_id: str) -> bool: ...
    def get_customer_for_event(self, event_id: str) -> str | None: ...
    def is_agent_registered(self, agent_id: str, session_id: str) -> bool: ...


class WorldState(Protocol):
    def get(self, customer_id: str) -> dict[str, Any] | None: ...
    def compute_hash(self, customer_id: str) -> str | None: ...


PLAN_SCOPE = {
    'starter': {'max_charge_usd_cents': 10000, 'allowed_envs': ['staging'], 'can_send_contracts': False},
    'pro': {'max_charge_usd_cents': 100000, 'allowed_envs': ['staging', 'production'], 'can_send_contracts': True},
    'enterprise': {'max_charge_usd_cents': 1000000, 'allowed_envs': ['staging', 'production'], 'can_send_contracts': True},
}
CONFIDENCE_FLOOR = {'reversible': 0.80, 'irreversible': 0.95}


class AuthorityGate:
    def __init__(self, world: WorldState, sessions: SessionRegistry):
        self.world = world
        self.sessions = sessions

    def validate(self, tpa: TPA) -> Verdict:
        checks = {k: 'NOT_EVALUATED' for k in ('identity', 'scope', 'destination', 'confidence', 'world_state')}

        def reject(code: VerdictCode, reason: str) -> Verdict:
            return Verdict(tpa.action_id, 'REJECTED', code, reason, dict(checks), tpa.__dict__)

        parts = tpa.requested_by.split('::', 1)
        agent_id = parts[0]
        session_id = parts[1] if len(parts) == 2 else ''

        if not self.sessions.is_event_authenticated(tpa.originating_event):
            checks['identity'] = 'FAIL'
            return reject(VerdictCode.IDENTITY_UNVERIFIED, 'originating event is not authenticated or has expired')
        if not self.sessions.is_agent_registered(agent_id, session_id):
            checks['identity'] = 'FAIL'
            return reject(VerdictCode.IDENTITY_UNVERIFIED, 'agent is not registered in the active session')
        checks['identity'] = 'PASS'

        customer_id = self.sessions.get_customer_for_event(tpa.originating_event)
        record = self.world.get(customer_id) if customer_id else None
        if not customer_id or not record:
            checks['scope'] = 'FAIL'
            return reject(VerdictCode.SCOPE_EXCEEDED, 'customer state is unavailable')
        if record.get('status') != 'active':
            checks['scope'] = 'FAIL'
            return reject(VerdictCode.SCOPE_EXCEEDED, 'customer is not active')

        limits = PLAN_SCOPE.get(record.get('plan', 'starter'), PLAN_SCOPE['starter'])
        if tpa.action_class == 'STRIPE_CHARGE' and tpa.scope.get('amount', 0) > limits['max_charge_usd_cents']:
            checks['scope'] = 'FAIL'
            return reject(VerdictCode.SCOPE_EXCEEDED, 'charge exceeds plan limit')
        if tpa.action_class == 'DEPLOYMENT' and tpa.scope.get('environment') not in limits['allowed_envs']:
            checks['scope'] = 'FAIL'
            return reject(VerdictCode.SCOPE_EXCEEDED, 'environment is not permitted by plan')
        if tpa.action_class == 'CONTRACT_SEND' and not limits['can_send_contracts']:
            checks['scope'] = 'FAIL'
            return reject(VerdictCode.SCOPE_EXCEEDED, 'contracts are not enabled for plan')
        checks['scope'] = 'PASS'

        authorized = {customer_id, record.get('stripe_customer_id'), record.get('contact_email'), record.get('deployment_namespace')}
        if tpa.destination not in {x for x in authorized if x is not None}:
            checks['destination'] = 'FAIL'
            return reject(VerdictCode.DESTINATION_INVALID, 'destination is outside customer authorization')
        checks['destination'] = 'PASS'

        floor = CONFIDENCE_FLOOR.get(tpa.reversibility, 1.0)
        if tpa.confidence < floor:
            checks['confidence'] = 'FAIL'
            return reject(VerdictCode.LOW_CONFIDENCE, 'confidence is below policy floor')
        checks['confidence'] = 'PASS'

        current_hash = self.world.compute_hash(customer_id)
        if current_hash != tpa.world_state_hash:
            checks['world_state'] = 'FAIL'
            return reject(VerdictCode.STALE_WORLD_STATE, 'world state changed after TPA formation')
        checks['world_state'] = 'PASS'

        return Verdict(tpa.action_id, 'AUTHORIZED', VerdictCode.AUTHORIZED, 'all policy checks passed', checks, tpa.__dict__)


class PrivilegedExecutor:
    def __init__(self, provider):
        self.provider = provider

    def execute(self, verdict: Verdict):
        if verdict.verdict != 'AUTHORIZED' or verdict.code is not VerdictCode.AUTHORIZED:
            raise PermissionError('privileged execution requires an AUTHORIZED verdict')
        return self.provider.execute(verdict.tpa)
