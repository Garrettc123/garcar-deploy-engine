from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Header, HTTPException, Request
from supabase import create_client

from gateway.security import StripeSignatureError, verify_stripe_signature

app = FastAPI(title='Garcar Authority Gateway', version='1.0.0')


def db_client():
    return create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])


def world_state_hash(record: dict) -> str:
    import hashlib
    canonical = json.dumps(record, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(canonical).hexdigest()


def open_session(db, event_id: str, customer_id: str, state_hash: str) -> dict:
    session_id = f'sess_{uuid.uuid4().hex}'
    expires = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    result = db.rpc('open_pipeline_session', {
        'p_event_id': event_id,
        'p_event_type': 'stripe_webhook',
        'p_customer_id': customer_id,
        'p_session_id': session_id,
        'p_agent_ids': ['billing-agent', 'onboarding-agent', 'deployment-agent'],
        'p_world_state_hash': state_hash,
        'p_expires_at': expires,
    }).execute()
    if not result.data:
        raise RuntimeError('session creation failed')
    return result.data[0] if isinstance(result.data, list) else result.data


@app.get('/health')
async def health():
    return {'status': 'ok', 'service': 'garcar-authority-gateway'}


@app.post('/webhooks/stripe')
async def stripe_webhook(request: Request, stripe_signature: str | None = Header(default=None, alias='Stripe-Signature')):
    payload = await request.body()
    try:
        verify_stripe_signature(payload, stripe_signature or '', os.environ['STRIPE_WEBHOOK_SECRET'])
    except StripeSignatureError as exc:
        raise HTTPException(status_code=401, detail='invalid webhook signature') from exc

    try:
        event = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail='invalid JSON') from exc

    event_id = event.get('id')
    event_type = event.get('type')
    if not event_id or not event_type:
        raise HTTPException(status_code=400, detail='malformed Stripe event')

    if event_type != 'checkout.session.completed':
        return {'accepted': True, 'processed': False, 'event_id': event_id}

    stripe_customer_id = event.get('data', {}).get('object', {}).get('customer')
    if not stripe_customer_id:
        raise HTTPException(status_code=422, detail='checkout session has no customer')

    db = db_client()
    customer_result = (db.table('customer_state').select('*')
                        .eq('stripe_customer_id', stripe_customer_id)
                        .maybe_single().execute())
    customer = customer_result.data
    if not customer:
        raise HTTPException(status_code=422, detail='unknown customer')

    projection = {k: customer.get(k) for k in (
        'plan', 'status', 'stripe_customer_id', 'contact_email', 'deployment_namespace'
    )}
    state_hash = world_state_hash(projection)
    session = open_session(db, event_id, customer['customer_id'], state_hash)

    return {
        'accepted': True,
        'processed': True,
        'event_id': event_id,
        'customer_id': customer['customer_id'],
        'session_id': session['session_id'],
    }
