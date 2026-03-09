---
phase: 9
date: "2026-03-09"
selected: A
---

# Phase 9 Implementation Approaches

## Approach A: Full Kafka Streaming (Production-Faithful)

**Summary**: Real Kafka consumers with aiokafka, full topic architecture (gps-pings, temperature, alerts), live consumer group management, and real-time dashboard with WebSocket updates.

**Pros**:
- Most realistic — demonstrates actual Kafka consumer patterns (offsets, consumer groups, rebalancing)
- Tests run against real Kafka (Docker) — proves the streaming pipeline end-to-end
- Consumer lag monitoring, backpressure handling, dead-letter queues all testable
- Dashboard with live WebSocket feed shows real-time capability

**Cons**:
- Slowest to build — Kafka consumer lifecycle, error handling, graceful shutdown are complex
- Integration tests require Kafka Docker (slower CI)
- WebSocket dashboard adds frontend complexity
- Risk of over-engineering consumer infrastructure for a 50-truck demo

**Effort**: L (5-7 days)
**Risk**: Scope creep on Kafka consumer edge cases (rebalancing, exactly-once semantics)

## Approach B: Event-Driven Core + Kafka Adapter (Architect's Choice)

**Summary**: Build the anomaly detection, agent memory, and fleet response graph as pure async Python with a clean event interface. Kafka is an adapter layer — the core logic works with any event source. Tests run fast against the event interface (no Kafka needed for unit tests). Integration tests verify the Kafka adapter. No frontend dashboard (API-only).

**Pros**:
- Domain-agnostic core: `EventConsumer` protocol works with Kafka, Redis Streams, or even in-memory queues
- Fast unit tests — anomaly detector, memory store, fleet graph all testable without Kafka
- Integration tests prove Kafka adapter separately
- Clean separation: business logic never imports `aiokafka`
- Matches Phase R's core/domain split perfectly
- API endpoints serve fleet data; dashboard is deferred (Phase 12 scope)

**Cons**:
- Less "wow factor" without a live dashboard
- Kafka adapter is thin — less Kafka-specific depth to showcase
- Slightly more abstraction upfront

**Effort**: M-L (4-6 days)
**Risk**: Abstraction might feel over-engineered for a single adapter, but pays off for testability

## Approach C: Simulation-First (No Real Kafka)

**Summary**: Use an in-memory event bus to simulate Kafka topics. Focus entirely on the anomaly detection algorithms, agent memory, and LangGraph fleet response. Kafka is mocked everywhere.

**Pros**:
- Fastest to build — no Kafka infrastructure complexity
- All tests run without Docker
- Focus on the architect story: two-tier processing, agent memory ROI, cost analysis

**Cons**:
- Doesn't prove Kafka integration works at all
- "Fleet Guardian" without actual streaming feels incomplete
- Can't demonstrate consumer lag, backpressure, or real throughput metrics
- Missing a key architect differentiator: proving the system works under real streaming load

**Effort**: S-M (2-3 days)
**Risk**: Feels like a toy demo — undermines the "production-ready" architect narrative

## Recommendation

**Approach B** — it's the architect's choice. The core insight of Phase 9 is the two-tier processing pattern, agent memory ROI, and cost analysis — not Kafka consumer group management. Building a clean event interface proves domain-agnostic thinking (a healthcare telemetry system could swap the Kafka adapter for MQTT). Integration tests against real Kafka prove it's not just theory. Skipping the dashboard keeps scope focused — the API endpoints provide all fleet data, and Phase 12 builds the full-stack demo.

The analysis identified 10 critical gaps. Approach B addresses them cleanly:
- Rate-of-change detection → anomaly detector unit tests
- Consumer health monitoring → Kafka adapter health checks
- Alert deduplication → dedup window in event processor
- Backpressure → configurable batch size + circuit breaker
- Agent memory → Redis + PostgreSQL with fast unit tests

## Selected: Approach A — Full Kafka Streaming (Production-Faithful)

**User choice**: "Quality is top priority!" — going with the most realistic, production-faithful implementation. Real Kafka consumers, full topic architecture, consumer group management, WebSocket dashboard, and real-time fleet monitoring. No shortcuts.
