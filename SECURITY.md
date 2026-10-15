# Security Policy

## Report a Vulnerability

**DO NOT open a public GitHub issue for security vulnerabilities.**

Email: [your-security-email@example.com] with subject `Bilogue Security Report`

You will receive a response within 48 hours. If the vulnerability is confirmed,
we will publish a patch within 7 days and credit you in the advisory
(unless you prefer to remain anonymous).

## Supported Versions

| Version | Status       |
|---------|--------------|
| 0.3.3   | Active       |
| 0.3.2   | **Vulnerable** — upgrade to 0.3.3 (see P1-01 ~ P1-08 / P2-01 ~ P2-04 below) |
| 0.3.1   | **Vulnerable** — upgrade to 0.3.3 (see P0-01 ~ P0-08 below) |
| 0.3.0   | **Vulnerable** — upgrade to 0.3.3 |
| 0.2.1   | Supported (security fixes only) |
| 0.2.0   | **Vulnerable** — upgrade to 0.2.1+ (see SEC-01 ~ SEC-14 below) |
| < 0.2   | Unsupported  |

## v0.3: Tiered Consent (L1/L2/L3)

v0.3 turns the Consent Gate into a three-tier policy engine:

- **L1 per-message approval** (default, unchanged from v0.2.x)
- **L2 conversation consent** — approving a message with `scope: "conversation"`
  (the default) lets its reply chain (`in_reply_to`, same agent pair) flow without
  further approvals, capped at 50 messages per chain. `scope: "once"` disables this.
- **L3 time-boxed trust window** — `POST /grant` lets an agent pair communicate
  freely within a TTL (max 24h) and a message budget; `POST /revoke` terminates
  early; `GET /grants` lists active windows.

Security notes for operators:
- A trust window widens the blast radius to its remaining TTL x budget. Keep TTLs
  short and budgets small; revoke on any suspicion.
- Grant/revoke/approve events and all window/chain deliveries
  (`RELAYED_GRANT`, `RELAYED_CONVERSATION`) are written to the audit log.
- Kill-switch still halts everything, including active grants.

## Fixed in v0.2.1 (external security audit)

All items below were confirmed with working proof-of-concepts against v0.2.0
and are covered by the regression suite `test_relay_security.py` (99 tests).

| ID | Severity | Issue | Fix |
|----|----------|-------|-----|
| SEC-01 | High | Re-registering an existing agent returned its current secret | `/register` now returns 409 for existing agents; secrets are only returned once at creation |
| SEC-02 | High | Pending Consent Gate messages could be swapped by reusing the same `msg_id` | Duplicate `msg_id` in the pending queue is rejected (409) |
| SEC-03 | Medium | No request body size limit → memory-exhaustion DoS; unguarded `Content-Length` parsing crashed handlers | 1 MB body cap (413); safe header parsing (400) |
| SEC-04 | Medium | Malformed `?since=` query crashed the request handler (dropped connection) | `parse_qs`-based parsing, invalid values return 400 |
| SEC-05 | Low | `/acl` and `/health` publicly leaked agent roster, ACL graph and pending count | `/acl` is admin-only; `/health` returns status only |
| SEC-06 | Medium | Admin token compared with `!=` (timing side channel) | `hmac.compare_digest` everywhere |
| SEC-07 | Medium | `seen_nonces` and `pending_approvals` grew unbounded | Nonce cache has TTL + capacity cap; pending queue has TTL (10 min) + cap (1000) + 429 backpressure |
| SEC-08 | Medium | Single-threaded `HTTPServer`: one slow client blocked the whole relay; no locking for shared state | `ThreadingHTTPServer` + locks on registry and pending queue |
| SEC-09 | Low | Same secret used as HMAC signing key AND inbox bearer token | Separate `read_token` per agent; signing secret no longer grants inbox access |
| SEC-10 | Low | Inbox was never cleared (`clear_queue` unused) → "unread" semantics broken, memory growth | Inbox is now delivery + explicit ACK (P0-05): messages are marked delivered but survive until the receiver ACKs them |
| SEC-11 | Low | Admin token printed in plaintext at startup | Masked on stdout; auto-generated tokens written to `relay_admin_token.txt` (chmod 600) |
| SEC-12 | Info | `/inbox/{aid}` 404 vs 403 allowed agent-ID enumeration | Uniform 403 for unknown agents and bad tokens |
| SEC-13 | Medium | Uncaught exceptions in handlers dropped connections without a response | Global try/except returns JSON 500 |
| SEC-14 | High | **Consent Gate bypass**: pending/rejected envelopes were also written into the recipient's live inbox queue, so receivers could read unapproved messages | Audit-only records (`PENDING_APPROVAL`, `REJECTED:*`, `ACL_DENIED`, …) no longer enter inbox queues; only `RELAYED` / `APPROVED_RELAYED` are delivered |

## Fixed in v0.3.1 (second audit round)

| ID | Severity | Issue | Fix |
|----|----------|-------|-----|
| SEC-15 | Medium | `conversations` (L2 chains) grew unbounded and every `/send` iterated all of them (memory + CPU amplification) | TTL (1h, `BILOGUE_CONV_TTL`) + cap (1000 active chains) with lazy eviction |
| SEC-16 | Medium | Unbounded threads + no read timeout → slow-loris thread exhaustion | Per-connection request timeout (30s) + bounded worker slots (64), 503 beyond that |
| SEC-17 | Low | `approve` defaulted to `scope=conversation`, silently widening consent to a 50-message chain | Default changed to `scope=once` (least privilege); chain consent is now explicit opt-in |
| SEC-18 | Low | No cap on total L3 grants | Cap 1000, 429 beyond that |
| SEC-19 | Low | Audit log grew unbounded on disk | Size-based rotation (10 MB x 3 backups, `BILOGUE_MAX_LOG_BYTES`) |
| SEC-20 | Info | Intent state machine documented but not enforced (e.g. REPORT could open a conversation) | Enforced at relay: replies need a delivered `in_reply_to` parent, same agent pair, and a legal transition per SPEC (400 BAD_STATE otherwise) |

## Fixed in v0.3.2 (third audit round — Round-1 P0)

Third-round external audit produced 20 findings (P0×8 / P1×8 / P2×4). **Round-1 ships
all 8 P0 fixes.** Each is covered by the regression suite `test_relay_security.py` (99 tests).

| ID | Severity | Issue | Fix |
|----|----------|-------|-----|
| P0-01 | High | Relay default-bound `0.0.0.0`, exposing it to the whole local network | Default bind is now `127.0.0.1`; `--host` is required for LAN; non-loopback binding prints a strong TLS warning |
| P0-02 | High | Kill-switch was in-memory — a restart silently cleared it and resumed normal operation | Kill state persisted to `relay_state.json`; restart stays STOPPED; `POST /resume` (admin-only) restores the gateway without reviving revoked grants |
| P0-03 | High | Messages approved after sitting in the pending queue were never re-validated (could approve stale/expired/now-unauthorized messages) | `handle_approve` re-checks kill state, both agents' registration, ACL, signature, freshness and pending TTL; any failure → 409 |
| P0-04 | High | Approval was not bound to the immutable envelope — a pending message's payload could in theory be swapped before approval | Pending entries store an `envelope_hash`; approval recomputes and compares it, and emits a separate `consent_id` |
| P0-05 | High | Inbox was read-and-delete — a receiver crash between GET and processing lost the message permanently | Inbox is now delivery + explicit ACK (`POST /messages/{aid}/{mid}/ack`); unacked messages survive crashes and are safely re-fetchable |
| P0-06 | Medium | Several IDs used truncated UUIDs (`uuid.uuid4().hex[:8]`, ~32-bit) | All IDs (`msg_id`, `grant_id`, `consent_id`, …) now use full 128-bit UUIDs |
| P0-07 | Medium | Signing/verification used different canonical-JSON implementations with inconsistent whitespace handling | Single shared module `bilogue_crypto.py` (`separators=(",",":")`); relay, clients and tests all import it |
| P0-08 | Medium | `payload` accepted scalars / arrays / null | `handle_send` requires `payload` to be a JSON object, else 400 |

## Fixed in v0.3.3 (third audit round — Round-2 P1×8 + Round-3 P2×4)

Round-2 and Round-3 close **all remaining 12 findings**. The regression suite is now
99 tests, plus a fuzz suite (`fuzz_relay.py`) that must complete with zero crashes.

| ID | Severity | Issue | Fix |
|----|----------|-------|-----|
| P1-01 | High | No TLS; plain HTTP exposure leaked secrets, tokens and payloads | `--tls-cert` / `--tls-key` enable TLS. Binding to a **non-loopback interface without TLS is refused** (exit 3). `--allow-insecure-lan` is the only override and is strongly discouraged |
| P1-02 | High | Admin token never rotatable; no rate limiting anywhere | `POST /rotate-token` (admin) issues a new token and invalidates the old one immediately. Sliding-window rate limiters on `/send`, admin endpoints and globally per IP (`BILOGUE_SEND_RATE`, `BILOGUE_ADMIN_RATE`, `BILOGUE_GLOBAL_RATE`); excess → 429 |
| P1-03 | Medium | Audit log and kill-switch state written to disk in cleartext | Fernet (AES) encryption at rest when `cryptography` is available; key persisted with mode 0600. Missing dependency degrades to plaintext **with a loud startup warning** |
| P1-04 | Medium | Client assumed JSON responses and never retried — network blips silently dropped messages, and non-JSON errors leaked raw bytes | `bilogue_send.py` supports HTTPS, classifies errors (4xx = do not retry, 5xx/connection = retry with backoff), and parses non-JSON bodies safely |
| P1-05 | Medium | Fixed ±300s timestamp window; no global request-flood protection | Per-message TTL is configurable (`CONFIG["MSG_TTL_SECONDS"]`); global per-IP sliding-window limiter added |
| P1-06 | Low | `POST /revoke` silently revoked a trust window — the receiving agent kept believing it was trusted | Revocation now pushes a `system` notification into the receiver's inbox; the response reports `notified: true` |
| P1-07 | Medium | JSONL audit log could be edited without detection | Append-only HMAC chain: each entry carries `_audit_prev` and `_audit_hash`; `GET /audit/verify` reports `integrity` and the first tampered line number |
| P1-08 | Low | No liveness or metrics endpoint | `GET /healthz` (status, version, killed, encryption on/off) and `GET /metrics` (pending, grants, undelivered, rate-limited totals) |
| P2-01 | Low | Nonce replay cache evicted entries after ~300s, so slow replays could succeed | Replay window extended to `CONFIG["NONCE_REPLAY_TTL"]` (≥3000s) with an LRU cap |
| P2-02 | Low | 500 responses echoed the exception class name (internal structure leak) | Responses are now generic `{"error": "internal server error"}` |
| P2-03 | Low | Tunables scattered as module constants with no validation | All tunables consolidated into `CONFIG`; `validate_config()` runs at startup and **fails closed** (invalid → refuse to start) |
| P2-04 | Low | No adversarial input testing | `fuzz_relay.py` hammers every endpoint with random/malformed/binary/oversized bodies. It found and led to fixes for two real 500-crash classes: non-UTF-8 bodies (`UnicodeDecodeError`) and non-string fields causing `TypeError` in dict lookups |

## Security Mechanisms (v0.3.3)

| Mechanism | Status |
|-----------|--------|
| HMAC-SHA256 envelope signing (shared `bilogue_crypto.py`, canonical JSON) | Active |
| ACL (agent-to-agent allowlist) | Active |
| Consent Gate (human approval) | Active — pending messages are invisible to recipients until approved |
| Kill-switch (persisted to `relay_state.json`) | Active |
| Inbox Bearer token auth (dedicated `read_token`) + ACK | Active (P0-05) |
| Admin token for management endpoints | Active |
| Nonce-based replay protection (TTL-bound cache) | Active (in-memory; see limitation) |
| Timestamp window validation (+/-300s) | Active |
| Request body size limit (1 MB) | Active |
| Pending queue dedup + TTL + backpressure | Active |
| Conversation chain TTL + cap | Active |
| Request timeout + worker slot limit | Active |
| Audit log rotation | Active |
| Intent state machine enforcement | Active |
| Constant-time token comparison | Active |
| Approved-message revalidation | Active (P0-03) |
| Immutable envelope-hash consent binding | Active (P0-04) |
| TLS (with mandatory-TLS check for non-loopback binds) | Active (P1-01) |
| Admin token rotation + per-IP rate limiting | Active (P1-02) |
| Encryption at rest (Fernet, graceful degradation) | Active when `cryptography` installed (P1-03) |
| Tamper-evident audit log (HMAC chain) | Active (P1-07) |
| Health / metrics endpoints | Active (P1-08) |
| Centralized config with fail-closed validation | Active (P2-03) |
| Fuzz regression suite | Active (P2-04) |

## Known Limitations (residual risk — v0.3.3)

All 20 third-round findings are fixed, but the following **inherent limitations remain**.
Read these before any production deployment.

- **Not independently audited / not certified.** The audit was self-directed.
  No third-party penetration test or formal verification has been done.
- **Single-relay architecture** — no federation, clustering or HA. The relay is a
  single point of failure and a single point of trust.
- **Symmetric secrets only** — HMAC-SHA256 with shared secrets. There is no
  public-key identity, no PKI and no per-agent key rotation API (agent `secret`
  rotation still requires re-registration).
- **In-memory agent registry, grants (L2/L3), nonce cache and conversations** —
  a restart clears all of them. This is fail-closed (everything falls back to L1
  per-message approval), but you must re-register agents and re-issue grants after
  a restart. Nonce history also resets, so a replay of a message captured before
  the restart may succeed within the freshness window.
- **Rate limiting is per-process and in-memory** — a distributed attacker or
  multiple relays defeat it. Use infrastructure-level limiting for real deployments.
- **`--auto-approve` disables the Consent Gate entirely** — test/demo only.
  Never use it in a shared deployment.
- **Encryption at rest degrades silently to plaintext** when `cryptography` is not
  installed (startup prints a warning). Install it explicitly if you rely on it.
- **Payload depth/length are only bounded by the 1 MB request body cap** — deeply
  nested payloads are not rejected on structure alone.
- **No SSRF controls on the relay side** — the relay never makes outbound requests,
  but any client-side integration that fetches URLs from payloads must add its own
  allowlist.

## Disclosure Timeline

1. You report privately
2. We confirm within 48 hours
3. We develop a fix (target: 7 days)
4. We publish the fix + advisory
5. We credit you (unless you prefer anonymity)
