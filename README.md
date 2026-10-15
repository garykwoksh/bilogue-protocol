# Bilogue Protocol

> 🌐 [繁體中文](README.zh-TW.md)

> **An AI-to-AI communication protocol with a human Consent Gate.**
>
> Core thesis: **the model is the engine, the Agent ID is the phone number.** Swap the engine, keep the number.
>
> **Positioning: Bilogue is not trying to replace major standards like MCP or A2A — it is a "human approval + audit governance layer" on top of them.**
> MCP standardizes how agents use tools; A2A standardizes how agents message each other — but no standard mandates that *a human presses a button before the machine actually does something*. Bilogue fills that gap: before any agent executes a side-effecting action, it must pass through the Consent Gate; everything executed is written to an append-only audit log for post-hoc investigation.

[![Tests](https://img.shields.io/badge/tests-99%20security--regression-passing-brightgreen)]()
[![Fuzz](https://img.shields.io/badge/fuzz-600%20iters%200%20crash-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.8%2B-blue)]()
[![License](https://img.shields.io/badge/license-MIT-yellow)]()
[![Security](https://img.shields.io/badge/security-v0.3.3%20self--audited-brightgreen)]()

> **WARNING: This is an EXPERIMENTAL PROTOTYPE. It HAS been self-security-audited by the project author (3 rounds, 20 findings: P0×8 / P1×8 / P2×4 — all fixed in v0.3.3), but it has NOT been audited by an independent third party and is NOT certified production-ready.** LAN / Internet deployment REQUIRES TLS (`--tls-cert` / `--tls-key`; binding to a non-loopback interface without TLS is now **refused**). See [SECURITY.md](SECURITY.md) for residual risks.

## What is this?

Bilogue is a protocol and reference implementation for AI agents to communicate with each other. It doesn't solve "can AIs talk to each other" (that's a few dozen lines of code) — it **standardizes** the glue:

| Layer | Problem solved | Implementation |
|---|---|---|
| **Identity** | Who is who? What if the model changes? | Agent ID + HMAC signatures; ACLs bind to IDs, not models |
| **Intent** | What do AIs say to each other? In what format? | Intent Envelope: DELEGATE → PROPOSE → ACCEPT → REPORT |
| **Consent** | Where does the human approve? | Consent Gate: y/n prompt on every external message; `stop` is a kill-switch |
| **Audit** | How do you investigate when something goes wrong? | JSONL append-only audit log |

## One-command quickstart

```bash
# Local demo (no API key, mock mode + auto-approve)
python3 hello_bilogue.py --mock --auto-approve

# Security + Consent regression tests (99 tests)
python3 test_relay_security.py

# Fuzzing (P2-04: 600 malformed requests, requiring zero crashes / zero 500s)
python3 fuzz_relay.py --iters 600

# Start the HTTP Relay Server (binds localhost by default, for cross-agent comms)
python3 bilogue_relay.py --port 8420

# Cross-machine deployment (TLS required; binding non-loopback without TLS refuses to start, exit 3)
python3 bilogue_relay.py --port 8420 --host 0.0.0.0 \
  --tls-cert /path/fullchain.pem --tls-key /path/privkey.pem
```

## Quick start

### 1. Two agents talking

```python
from hello_bilogue import AgentRegistry, MessageBus, ConsentGate, Agent

registry = AgentRegistry()
bus = MessageBus()
gate = ConsentGate(auto_approve=True)

registry.register("karina", "Karina (analysis assistant)", "mock")
registry.register("stfund", "St.Fund (audit assistant)", "mock")
registry.allow("karina", "stfund")

karina = Agent("karina", "Karina", "mock", registry, bus)
stfund = Agent("stfund", "St.Fund", "mock", registry, bus)

# Karina delegates to St.Fund
karina.send("stfund", "DELEGATE", {"task": "Q3 financial analysis"}, gate)

# St.Fund receives it, auto-replies PROPOSE
# Karina receives PROPOSE, replies ACCEPT
# St.Fund receives ACCEPT, replies REPORT
# Done!
```

### 2. HTTP Relay (cross-machine)

```bash
# Start the relay (set an admin token)
python3 bilogue_relay.py --port 8420 --auto-approve --admin-token myAdmin123

# In another terminal: register an agent + send a message
curl -X POST http://localhost:8420/register \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer myAdmin123" \
  -d '{"agent_id": "karina", "display_name": "Karina"}'

# Fetch inbox (authenticated with the agent's read_token; separated from the
# signing secret since v0.2.1; ACK required since P0-05)
curl http://localhost:8420/inbox/karina \
  -H "Authorization: Bearer <read_token>"

# ACK after receiving (P0-05: safe to re-fetch before ACK, nothing is deleted early)
curl -X POST http://localhost:8420/messages/karina/<msg_id>/ack \
  -H "Authorization: Bearer <read_token>"
```

### 3. Plug in real models

```bash
export MOONSHOT_API_KEY=sk-...
export OPENAI_API_KEY=sk-...

python3 hello_bilogue.py \
  --agent karina=moonshot \
  --agent stfund=openai
```

Supported: Kimi (Moonshot) / OpenAI / Claude / Gemini

## Intent state machine

> Since v0.3.1 the relay enforces this: replies must carry a valid `in_reply_to`, and transitions must be legal (otherwise 400 BAD_STATE).

```
QUERY    → REPORT / ACCEPT / REJECT
DELEGATE → PROPOSE / ACCEPT / REJECT / REPORT
PROPOSE  → ACCEPT / REJECT
ACCEPT   → REPORT
REJECT   → QUERY / DELEGATE (can restart)
REPORT   → QUERY / DELEGATE (task done, can open a new one)
PING     → REPORT
```

## Three-level Consent policy (v0.3)

Per-message approval is the safest but kills throughput (and turns approvers into rubber stamps), so the Consent Gate now has three levels:

| Level | Granularity | Usage |
|---|---|---|
| **L1 per-message approval** (default) | Approval prompt on every envelope | No setup needed, default behavior |
| **L2 conversation-chain consent** | Approve one task; subsequent PROPOSE/ACCEPT/REPORT auto-pass | `POST /approve {"msg_id": "...", "scope": "conversation"}`; since v0.3.1 the default is `once` (least privilege) — chains must be explicitly opened |
| **L3 time-boxed trust window** | Two agents communicate freely within a deadline + message budget | See below |

```bash
# L3: approve up to 100 messages from karina → stfund over the next 30 minutes
curl -X POST http://localhost:8420/grant -H "Authorization: Bearer <admin>" \
  -H "Content-Type: application/json" \
  -d '{"agent_a": "karina", "agent_b": "stfund", "direction": "a_to_b",
       "ttl_seconds": 1800, "max_messages": 100}'

# List active windows / revoke early
curl http://localhost:8420/grants -H "Authorization: Bearer <admin>"
curl -X POST http://localhost:8420/revoke -H "Authorization: Bearer <admin>" \
  -H "Content-Type: application/json" -d '{"grant_id": "grant-xxxx"}'
```

Risk controls: windows have both a TTL (max 24h) and a message budget, and can be revoked at any time; all messages relayed under a window/conversation chain still land in the audit log (`RELAYED_GRANT` / `RELAYED_CONVERSATION`), and the kill-switch still cuts everything instantly.

## Security mechanisms

| Mechanism | Description | Test result |
|------|------|----------|
| HMAC signatures | Every envelope is signed with the sender's secret; tampering is rejected | ✓ 401 |
| Nonce + timestamp | Replay protection: nonce dedup + ±300s time window (cache has a TTL cap) | ✓ 401 |
| ACL | Two agents must mutually authorize before communicating | ✓ 403 |
| Consent Gate | Approval prompt on every external message; **pending messages are invisible to the recipient** (bypass fixed in v0.2.1); three-level policy since v0.3 | ✓ 202 |
| msg_id anti-swap | Pending queue rejects duplicate msg_ids (v0.2.1) | ✓ 409 |
| Kill-switch | Typing `stop` terminates all communication instantly | ✓ 403 |
| Inbox auth | Separate read_token (split from the signing secret); delivery + ACK since P0-05 (safe re-fetch before ACK, nothing deleted early); nonexistent agents always get 403 to prevent enumeration | ✓ 403 |
| Admin token | Admin endpoints (register/allow/kill) require an admin token, constant-time comparison | ✓ 403 |
| Registration guard | Re-registration returns 409; the secret is only revealed once, at first registration (v0.2.1) | ✓ 409 |
| Request limits | 1MB body cap, 413 on overflow; malformed input always gets a JSON error response (v0.2.1) | ✓ 413/400 |
| Audit log | All messages land in JSONL, append-only | ✓ |

> An external security audit of v0.2.0 found 14 issues (including 3 high-severity, all with PoCs), all fixed in **v0.2.1**.
> Details and the item-by-item mapping are in [SECURITY.md](SECURITY.md); regression tests: `python3 test_relay_security.py`.

## Key security changes in v0.3.2 (Round-1 P0, third audit round)

The third external audit round raised 20 findings (P0×8 / P1×8 / P2×4). **Round-1 implemented all 8 P0s**:

| P0 | Change | Impact |
|----|------|------|
| **P0-01** | Relay binds `127.0.0.1` by default; loud warning on non-loopback (LAN/Internet requires HTTPS) | No more default exposure on 0.0.0.0 |
| **P0-02** | Kill-switch persisted (`relay_state.json`); stays STOPPED across restarts; new `POST /resume` (does not resurrect old grants) | Fixes "restart silently recovers" |
| **P0-03** | Re-validation before approval (kill / both registered / ACL / signature / freshness / pending TTL) | Never approves expired/invalid messages |
| **P0-04** | Approval binds to an immutable envelope hash; produces an independent `consent_id` | Prevents in-flight message swapping |
| **P0-05** | Inbox changed from read-and-delete to delivery + ACK (`POST /messages/{aid}/{mid}/ack`) | Fixes "client crash loses messages" |
| **P0-06** | All truncated UUIDs (`grant_id` etc.) replaced with full 128-bit UUIDs | Prevents msg_id collisions |
| **P0-07** | Shared `bilogue_crypto.py` for canonical JSON signatures (`separators=(",",":")`); relay / client / tests all import it | Prevents signature canonicalization divergence |
| **P0-08** | `payload` must be a JSON object (scalars / arrays / null rejected) | Narrows the attack surface |

## Key security changes in v0.3.3 (Round-2 P1×8 + Round-3 P2×4)

The remaining 12 findings from the third audit round are all implemented:

| ID | Change | Impact |
|----|------|------|
| **P1-01** | Non-loopback binding **requires TLS** (`--tls-cert/--tls-key`); refuses to start without TLS (exit 3); `--allow-insecure-lan` can override (not recommended) | Eliminates "plaintext HTTP exposed to LAN" |
| **P1-02** | `POST /rotate-token` rotates the admin token (old token dies instantly); sliding-window rate limits (send / admin / global, tunable via `BILOGUE_*_RATE`) | Token leaks can be stopped; brute-force + DoS resistance |
| **P1-03** | Audit / state written to disk encrypted with Fernet (when `cryptography` is available), key persisted with 0600; plaintext + startup warning otherwise | Disk reads don't directly expose payloads |
| **P1-04** | Client `bilogue_send.py` supports HTTPS, connection-level retry + backoff, error classification (no retry on 4xx / retry on 5xx) | Network jitter no longer silently drops messages |
| **P1-05** | Configurable message-level TTL (`MSG_TTL_SECONDS`); global per-IP rate limiting | Narrower replay window + global DoS protection |
| **P1-06** | `POST /revoke` pushes a `system` revocation notice to the receiver's inbox | Counterparty learns immediately that a grant died |
| **P1-07** | Audit log is now an HMAC chain (`_audit_prev` / `_audit_hash`); tampering is localizable to a line number; `GET /audit/verify` | Audit records are provably untampered |
| **P1-08** | New `GET /healthz` (liveness + version + killed + encryption state) and `GET /metrics` (pending / grants / undelivered / rate-limit counters) | Observability |
| **P2-01** | Nonce reuse detection window widened from ±300s to `NONCE_REPLAY_TTL` (≥3000s) + LRU cap | Slow replays get caught too |
| **P2-02** | External 500s no longer leak exception class names; details stay server-side | No more internal structure for attackers |
| **P2-03** | All tunable parameters centralized in `CONFIG`; `validate_config()` fails closed at startup (negative/illegal values refuse to start) | Misconfiguration can't silently downgrade security |
| **P2-04** | New `fuzz_relay.py` fuzzer (random/malformed/binary/oversized bodies against all endpoints) | Found and fixed 2 real 500-crash classes |

## Project structure

```
bilogue-protocol/
├── hello_bilogue.py          # MVP: local in-memory demo (no relay)
├── bilogue_relay.py          # HTTP Relay Server v0.3.3 (cross-agent)
├── bilogue_crypto.py         # P0-07: shared canonical JSON signing module
├── test_relay_security.py    # Security + Consent regression tests (99 tests)
├── fuzz_relay.py             # P2-04: fuzzing suite
├── openclaw-bilogue/         # OpenClaw skill integration
│   ├── SKILL.md
│   └── scripts/bilogue_send.py, bilogue_inbox.py
├── app/index.html            # Architecture visualization landing page
├── docs/                     # Ops / strategy / test records
├── SPEC.md                   # Protocol specification
├── SECURITY.md               # Security audit and remediation records
├── ROADMAP.md                # Action roadmap
└── 人肉Consent-Gate操作手册.md  # No-code operation manual (Chinese)
```

## Tests

```bash
# Security + Consent policy regression (99 tests)
python3 test_relay_security.py

# Fuzzing (600 malformed requests)
python3 fuzz_relay.py --iters 600

# Local demo (mock mode)
python3 hello_bilogue.py --mock --auto-approve
```

**Results**:
- v0.3.3 security + Consent policy regression: **99/99 ✓**
  (57 original SEC/L1/L2/L3/state-machine + 19 P0-01~08 + 23 P1/P2)
- v0.3.3 fuzzing: **600 iterations, zero 500s, zero crashes, `/healthz` alive, audit chain intact ✓**

## Docs

- [SPEC.md](SPEC.md) — protocol spec (envelope format + state machine + security)
- [ROADMAP.md](ROADMAP.md) — next steps
- [Bilogue_Strategy_Summary.md](Bilogue_Strategy_Summary.md) — strategy summary
- [人肉Consent-Gate操作手册.md](人肉Consent-Gate操作手册.md) — no-code operation manual (Chinese)
- [docs/why-agents-need-a-consent-layer.md](docs/why-agents-need-a-consent-layer.md) — design rationale: why agents need a consent layer

## Design philosophy

> Consumer apps (ChatGPT / Claude / Kimi / Gemini) have no "direct line" between each other. But they all have APIs, so two AIs talking to each other is already just "a few dozen lines of glue code" today.

> **Bilogue's value isn't making it possible — it's standardizing the glue: addresses (Agent IDs), identity (HMAC signatures), intent format (envelopes), and most importantly the Consent Gate (the human approval point).**

## License

MIT

## Disclaimer

This software is provided "AS IS" for research and educational purposes.
It is NOT production-ready and has NOT been audited by an independent third
party (it has undergone 3 rounds of self-directed security audit by the
project author; see SECURITY.md for residual risks).
Do NOT use Bilogue Protocol in production environments without a proper
security assessment. The authors assume no liability for any damages,
data breaches, or losses resulting from the use of this software.

By using Bilogue Protocol, you acknowledge that:
1. AI-to-AI communication involves inherent risks
2. You are solely responsible for monitoring and approving all communications
3. The Consent Gate is a best-effort human-in-the-loop mechanism, not a guarantee
