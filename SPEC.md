# Bilogue Protocol Specification v0.3

> **Status**: Experimental prototype. Not production-ready.

## 1. Overview

Bilogue is a protocol for **Agent-to-Agent (A2A) communication with a human consent layer**. It standardizes the "glue" between AI agents: identity, intent, consent, and audit.

### Design Principles

1. **Model-agnostic** — Agent ID is a phone number; the model is just the engine. Swap models without changing identity.
2. **Human-in-the-loop** — Every cross-agent message passes through a Consent Gate that a human can approve, reject, or kill.
3. **Pure stdlib** — Reference implementation uses zero third-party Python packages.
4. **Audit-first** — Every event is written to an append-only JSONL log.

## 2. Identity Layer

### Agent ID

Each agent has a unique identifier (e.g. `karina@g-k.ai`). The ID is stable across model changes.

### HMAC Signing (MVP)

- Each agent holds a **secret** (32-char hex) used for HMAC-SHA256 message signing.
- Each agent also has a separate **read_token** (32-char hex) for inbox access.
- The signing secret and read_token are **never the same** (SEC-09).

### Future: Public Key Infrastructure

- MVP uses shared secrets. Production should use Ed25519 key pairs with public keys published via DNS TXT records or a key directory.

## 3. Intent Envelope

Every message is an Intent Envelope:

```json
{
  "msg_id": "msg-a1b2c3d4",
  "sender": "karina",
  "receiver": "stfund",
  "intent_type": "DELEGATE",
  "payload": {"task": "Q3 financial analysis"},
  "in_reply_to": null,
  "nonce": "e5f6a7b8...",
  "ts": "2026-01-15T10:30:00+00:00",
  "sig": "hmac-sha256-hex-string"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `msg_id` | Yes | Unique message identifier (UUID-based) |
| `sender` | Yes | Agent ID of the sender |
| `receiver` | Yes | Agent ID of the receiver |
| `intent_type` | Yes | One of the 7 intent types (see §4) |
| `payload` | Yes | Task content (dict, max 1MB serialized) |
| `in_reply_to` | No | `msg_id` of the parent message (for replies) |
| `nonce` | Yes | Random hex string (replay protection) |
| `ts` | Yes | ISO 8601 timestamp (±300s window) |
| `sig` | Yes | HMAC-SHA256 of the canonical JSON body |

### Signature Computation

```python
body_keys = {k: v for k, v in envelope.items() if k != "sig"}
body_str = json.dumps(body_keys, sort_keys=True, ensure_ascii=False)
sig = hmac.new(secret.encode(), body_str.encode(), hashlib.sha256).hexdigest()
```

## 4. Intent State Machine

Seven intent types form a state machine. v0.3.1 enforces this at the relay level.

```
QUERY    → REPORT / ACCEPT / REJECT
DELEGATE → PROPOSE / ACCEPT / REJECT / REPORT
PROPOSE  → ACCEPT / REJECT
ACCEPT   → REPORT
REJECT   → QUERY / DELEGATE   (can restart)
REPORT   → QUERY / DELEGATE   (task done, new topic)
PING     → REPORT
```

**Conversation starters** (no `in_reply_to` needed): `QUERY`, `DELEGATE`, `PING`.

All other intents **must** have a valid `in_reply_to` pointing to a delivered message from the same agent pair, with a legal transition. Violations return `400 BAD_STATE`.

## 5. Consent Gate

### Three-Tier Policy (v0.3)

| Tier | Granularity | How to use |
|------|-------------|------------|
| **L1** Per-message (default) | Each envelope requires individual approval | Default behavior, no configuration needed |
| **L2** Conversation chain | Approve once; subsequent replies in the chain auto-pass | `POST /approve {"msg_id": "...", "scope": "conversation"}` |
| **L3** Time-boxed trust window | Agent pair communicates freely within TTL + budget | `POST /grant` / `POST /revoke` |

### L1 Flow

1. Agent A sends envelope → relay validates signature, nonce, freshness, ACL, state machine
2. If not auto-approved: envelope enters `pending_approvals` → returns `202 PENDING_APPROVAL`
3. Human reviews via `GET /pending` → `POST /approve` or `POST /reject`
4. Approved messages are delivered to receiver's inbox; rejected are audit-logged only
5. **Pending messages are never visible in the receiver's inbox** (SEC-14)

### L2 Conversation Chain

- Approving with `scope: "conversation"` creates a chain rooted at the approved `msg_id`
- Subsequent messages with `in_reply_to` pointing into the chain auto-pass (no per-message approval)
- Chain has a TTL (1h, configurable via `BILOGUE_CONV_TTL`) and a message cap (50)
- `scope: "once"` (default since v0.3.1) does NOT create a chain — least privilege
- **Bidirectional by design**: the chain is keyed by the unordered agent *pair*
  (`frozenset({sender, receiver})`), so once a conversation is approved, replies in
  **both directions** (A→B and B→A) flow without further approval, as long as each
  message carries a valid `in_reply_to` into the chain and the intent transition is
  legal per the state machine (§4). Rationale: a conversation is inherently two-way;
  approving only one direction would break the DELEGATE → PROPOSE → ACCEPT → REPORT
  loop. Operators who need one-way-only flow should use L1 per-message approval or
  an L3 grant with `direction: "a_to_b"` / `"b_to_a"` instead.

### L3 Trust Window

```bash
POST /grant
{
  "agent_a": "karina",
  "agent_b": "stfund",
  "direction": "a_to_b",      // both | a_to_b | b_to_a
  "ttl_seconds": 1800,          // max 86400
  "max_messages": 100
}
```

- Each message in the window decrements the budget
- Window expires on TTL or budget exhaustion → falls back to L1
- `POST /revoke` terminates immediately
- Max 1000 active grants (SEC-18)

## 6. Security Mechanisms

| Mechanism | Implementation |
|-----------|----------------|
| HMAC-SHA256 signing | Every envelope signed; tampering → 401 |
| Nonce replay protection | Nonce cache with TTL (300s) + cap (100k) |
| Timestamp window | ±300s; stale → 401 |
| ACL (agent allowlist) | Bidirectional; unauthorized → 403 |
| Body size limit | 1MB max; oversized → 413 |
| Request timeout | 30s per connection (SEC-16) |
| Worker slot limit | 64 concurrent (SEC-16); beyond → 503 |
| Admin token | `hmac.compare_digest` (timing-safe) |
| Inbox read_token | Separate from signing secret (SEC-09) |
| Agent enumeration prevention | Unknown agent + bad token → uniform 403 |
| Audit log rotation | 10MB × 3 backups (SEC-19) |
| Kill-switch | `POST /kill` → all communication halted |

See [SECURITY.md](SECURITY.md) for the full audit history (SEC-01 through SEC-20).

## 7. API Reference

### Public Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | None | Health check (returns `{"status": "alive"}`) |

### Agent Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/send` | HMAC signature | Submit an intent envelope |
| GET | `/inbox/{agent_id}` | Bearer read_token | List undelivered messages (delivery + ACK; reading does **not** delete, P0-05) |
| POST | `/messages/{agent_id}/{msg_id}/ack` | Bearer read_token | Acknowledge receipt; clears the message from the inbox (P0-05) |

### Admin Endpoints (require Bearer admin_token)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/register` | Register a new agent (409 if exists) |
| POST | `/allow` | Grant ACL between two agents |
| GET | `/acl` | View ACL graph |
| GET | `/pending` | List pending approvals |
| POST | `/approve` | Approve a pending message (`scope`: `once` default / `conversation`) |
| POST | `/reject` | Reject a pending message |
| POST | `/kill` | Trigger kill-switch (persisted across restarts, P0-02) |
| POST | `/resume` | Resume after kill-switch (does not revive old grants, P0-02) |
| POST | `/grant` | Create L3 trust window |
| POST | `/revoke` | Revoke a trust window (pushes `system` notice to receiver, P1-06) |
| GET | `/grants` | List active trust windows |
| POST | `/rotate-token` | Rotate admin token (old token immediately invalid, P1-02) |
| GET | `/healthz` | Liveness + version + killed + encryption status (P1-08) |
| GET | `/metrics` | Counters: pending / grants / undelivered / rate-limited (P1-08) |
| GET | `/audit/verify` | Verify audit HMAC chain integrity (P1-07) |

## 8. Audit Log

All events are written to `relay_inbox.jsonl` (append-only):

| Delivery tag | Meaning |
|--------------|---------|
| `RELAYED` | Auto-approved and delivered |
| `APPROVED_RELAYED` | Approved by human and delivered |
| `RELAYED_GRANT` | Delivered via L3 trust window |
| `RELAYED_CONVERSATION` | Delivered via L2 conversation chain |
| `PENDING_APPROVAL` | Waiting for human approval (not delivered) |
| `REJECTED_BY_GATE` | Rejected by human |
| `REJECTED:*` | Rejected by relay (stale, replay, state machine, etc.) |
| `ACL_DENIED` | ACL check failed |
| `EXPIRED_PENDING` | Pending message TTL expired |
| `KILL_SWITCH` | Kill-switch triggered |
| `GRANT_CREATED` / `GRANT_REVOKED` | Trust window lifecycle |

## 9. Known Limitations

- **TLS is available but not mandatory on loopback** — `--tls-cert` / `--tls-key`
  enable it; binding to a non-loopback interface **without** TLS is refused (exit 3,
  P1-01). Reverse proxy / Tailscale / VPN remain valid alternatives.
- **Rate limiting is per-process and in-memory** (P1-02 / P1-05) — a distributed
  attacker or multiple relays defeat it; also mitigate at the infrastructure layer.
- **Single-relay** — no federation, clustering or HA.
- **In-memory state** — registrations, grants, nonce cache and conversations reset
  on restart (fail-closed: everything falls back to L1). Kill-switch state IS
  persisted (P0-02); consent grants and credentials are not.
- **Audit log is tamper-*evident*, not tamper-*proof*** — the HMAC chain (P1-07)
  detects edits and locates the first tampered line, but cannot prevent them. Use
  WORM / append-only storage for real immutability.
- **Encryption at rest degrades to plaintext** when `cryptography` is not installed
  (P1-03); the relay prints a startup warning.
- **Inbox is delivery + ACK** (P0-05) — read does not delete; the receiver must
  `POST /messages/{aid}/{mid}/ack` to clear a message; unacked messages survive
  receiver crashes.
- **`payload` must be a JSON object** (P0-08); depth/length are bounded only by the
  1 MB request body cap.
- **Symmetric HMAC secrets only** — no PKI, no per-agent key-rotation API.

## 10. Versioning

| Version | Key Changes |
|---------|-------------|
| 0.1 | MVP: in-memory MVP, HMAC signing, Consent Gate |
| 0.2 | HTTP relay, Bearer auth, admin token, nonce/timestamp |
| 0.2.1 | Security audit fixes (SEC-01 ~ SEC-14) |
| 0.3 | Three-tier consent (L1/L2/L3) |
| 0.3.1 | Second audit fixes (SEC-15 ~ SEC-20), state machine enforcement |
| 0.3.2 | Round-1 P0 fixes (P0-01 ~ P0-08): localhost-only bind, persistent kill-switch, approval revalidation, envelope-hash consent, ACK inbox, full UUIDs, shared `bilogue_crypto`, payload-object enforcement |
| 0.3.3 | Round-2 P1 (P1-01 ~ P1-08) + Round-3 P2 (P2-01 ~ P2-04): mandatory TLS for non-loopback binds, admin token rotation + rate limiting, encryption at rest, hardened client with retries, configurable message TTL, grant-revocation notification, HMAC-chained audit log, `/healthz` + `/metrics`, extended nonce replay window, generic 500s, centralized fail-closed config validation, fuzz suite |
