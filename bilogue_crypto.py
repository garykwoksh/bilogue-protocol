#!/usr/bin/env python3
"""
bilogue_crypto.py — Shared canonical JSON + HMAC signing for Bilogue Protocol
=============================================================================

Single source of truth for envelope signing/verification.
Both the relay server and all clients import from here, eliminating
canonical-JSON drift bugs.

P0-07: 修正前，relay、hello_bilogue、test、bilogue_send 各自實作簽名邏輯，
       且 whitespace 處理不一致（無 separators）。此模組統一所有簽名行為。
"""
import hashlib
import hmac
import json

# Server-side annotations — added by relay AFTER signing.
# Must be excluded from the signed body on both sign and verify sides.
SIG_EXCLUDED_FIELDS = frozenset({"sig", "delivery", "delivery_ts"})


def canonical_json(obj: dict) -> str:
    """Produce canonical JSON for signing or hashing.

    Rules:
    1. Remove sig, delivery, delivery_ts (server annotations)
    2. sort_keys=True (deterministic key order)
    3. ensure_ascii=False (preserve UTF-8)
    4. separators=(",", ":") (compact, no whitespace — prevents
       whitespace-variant forgery and reduces ambiguity)
    """
    body_keys = {k: v for k, v in obj.items()
                 if k not in SIG_EXCLUDED_FIELDS}
    return json.dumps(body_keys, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def sign(envelope: dict, secret: str) -> str:
    """HMAC-SHA256 sign the canonical JSON of the envelope.

    Returns full 64-char hex digest (NOT truncated).
    """
    body_str = canonical_json(envelope)
    return hmac.new(secret.encode(), body_str.encode(),
                    hashlib.sha256).hexdigest()


def verify(envelope: dict, secret: str, signature: str) -> bool:
    """Constant-time HMAC verification.

    Returns True if the signature matches the canonical form of the envelope.
    """
    expected = sign(envelope, secret)
    return hmac.compare_digest(expected, signature)


def envelope_hash(envelope: dict) -> str:
    """SHA-256 hash of the canonical JSON.

    P0-04: Used to bind approval to an immutable envelope hash.
    Returns 64-char hex string.
    """
    body_str = canonical_json(envelope)
    return hashlib.sha256(body_str.encode()).hexdigest()
