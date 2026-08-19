from __future__ import annotations

import hashlib
import hmac
import time


class StripeSignatureError(ValueError):
    pass


def verify_stripe_signature(
    payload: bytes,
    signature_header: str,
    secret: str,
    tolerance_seconds: int = 300,
) -> None:
    if not signature_header:
        raise StripeSignatureError('missing Stripe-Signature header')

    timestamp: int | None = None
    signatures: list[str] = []
    for component in signature_header.split(','):
        if '=' not in component:
            continue
        key, value = component.strip().split('=', 1)
        if key == 't':
            try:
                timestamp = int(value)
            except ValueError as exc:
                raise StripeSignatureError('invalid timestamp') from exc
        elif key == 'v1':
            signatures.append(value)

    if timestamp is None or not signatures:
        raise StripeSignatureError('missing timestamp or v1 signature')

    if abs(int(time.time()) - timestamp) > tolerance_seconds:
        raise StripeSignatureError('signature outside tolerance')

    signed = str(timestamp).encode() + b'.' + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise StripeSignatureError('invalid signature')
