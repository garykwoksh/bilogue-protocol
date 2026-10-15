# Bilogue Protocol — Roadmap

> Living document. Priorities shift based on adoption and feedback.

## Current State (v0.3.1)

- ✅ HTTP relay with HMAC-signed envelopes
- ✅ Three-tier consent policy (L1/L2/L3)
- ✅ Intent state machine enforcement
- ✅ 20 security fixes across two audit rounds
- ✅ 57/57 regression tests passing
- ✅ OpenClaw integration (skill + scripts)
- ✅ Landing page

## Phase 1: Polish & Publish (Month 1)

**Goal**: Clean open-source release on GitHub.

| Task | Priority | Effort |
|------|----------|--------|
| Remove all legacy "Synapse" references | P0 | 1h |
| Replace demo secrets with env-var injection | P0 | done |
| Add LICENSE (MIT) | P0 | done |
| Add .gitignore (exclude tokens, inbox, pyc) | P0 | done |
| Add CODE_OF_CONDUCT.md | P1 | done |
| Add CONTRIBUTING.md | P1 | done |
| GitHub Actions CI (run tests on push) | P1 | 2h |
| Issue templates (bug / feature / security) | P2 | 1h |
| GitHub Pages landing page | P1 | done |

## Phase 2: Hardening (Month 2)

**Goal**: Make it safe enough for a trusted beta.

| Task | Priority | Effort |
|------|----------|--------|
| TLS via reverse proxy (Caddy auto-HTTPS) | P0 | 4h |
| Rate limiting (token bucket at proxy) | P1 | 4h |
| Persistent agent registry (SQLite) | P1 | 1d |
| Persistent grants (survive restart) | P1 | 4h |
| Structured logging (JSON to stdout) | P2 | 4h |
| Prometheus metrics endpoint | P2 | 4h |
| Dockerfile + docker-compose | P1 | 4h |
| Load test (locust, 100 concurrent) | P2 | 1d |

## Phase 3: Interoperability (Month 3)

**Goal**: Position as the "consent layer" on top of A2A / MCP.

| Task | Priority | Effort |
|------|----------|--------|
| A2A protocol adapter (envelope ↔ A2A message) | P0 | 2d |
| MCP tool wrapper (expose relay as MCP tool) | P1 | 1d |
| OpenAPI spec for REST API | P1 | 4h |
| SDK: Python client library | P1 | 1d |
| SDK: TypeScript client library | P2 | 2d |
| Webhook support (notify on pending approval) | P2 | 1d |

## Phase 4: Commercial Path (Month 4-6)

**Goal**: Validate a revenue model without locking down the protocol.

| Task | Priority | Notes |
|------|----------|-------|
| Hosted relay SaaS (managed instance) | P1 | Per-seat or per-message pricing |
| Enterprise on-premise license | P2 | AGPL dual-license strategy |
| Compliance pack (SOC2 audit trail export) | P2 | Enterprise differentiator |
| Dashboard (real-time consent queue UI) | P1 | Web UI for approve/reject |
| Marketplace listing (AI agent directories) | P2 | Visibility |

## Decision Points

### License: MIT vs AGPL

- **MIT**: Maximum adoption, minimum protection. Competitors can fork and close-source.
- **AGPL**: Forces derivatives to open-source. Protects against cloud providers re-selling without contributing. Use a dual-license (AGPL open + commercial license for enterprises) for revenue.
- **Recommendation**: Start MIT for adoption. Switch to AGPL dual-license when commercial SaaS launches.

### Federation

Current architecture is single-relay. Federation (relay-to-relay) would enable:
- Cross-organization agent communication
- Decentralized trust (no single point of failure)
- But: significantly more complex (trust propagation, cross-relay ACL)

**Recommendation**: Defer until there's demonstrated demand from multi-org users.

## Non-Goals (for now)

- Not building an AI model or agent framework
- Not competing with A2A / MCP — complementing them with a consent layer
- Not building a full PKI — MVP shared secrets are sufficient for prototype
- Not building a blockchain / token system
