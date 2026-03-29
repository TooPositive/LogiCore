# ADR-012: Protocol (Structural Subtyping) over ABC for Provider Abstraction

## Status
Accepted

## Context
Phase 6's air-gapped deployment requires swapping LLM providers (Azure ↔ Ollama) via configuration. Both providers wrap third-party LangChain classes (`AzureChatOpenAI`, `ChatOllama`) that we don't control. The provider contract defines three methods: `generate()`, `generate_structured()`, and `model_name`.

## Decision
**Python `Protocol` with `@runtime_checkable`** for the `LLMProvider` contract. Any class with the right methods automatically satisfies the contract — no inheritance required.

## Rationale

| Criteria | Protocol (chosen) | ABC | Plain Duck Typing |
|----------|-------------------|-----|------------------|
| Third-party wrapping | No inheritance needed | Requires explicit `class Foo(LLMProvider)` | No type safety |
| Type checking | Static (mypy) + runtime (`isinstance`) | Static + runtime | Neither |
| Shared implementation | Not supported | Template methods, shared helpers | N/A |
| `isinstance()` performance | Slower (checks all methods at runtime) | Fast (nominal check) | N/A |

## Consequences
- `isinstance(provider, LLMProvider)` works via `@runtime_checkable` — used in tests to verify both providers satisfy the contract
- The `isinstance` check is slower than ABC's nominal check, but irrelevant — the factory is called once at startup
- If providers need shared implementation (e.g., common retry logic), switch to ABC — Protocol only defines interface, not implementation
- Factory function (`get_llm_provider`) uses lazy imports inside `match/case` branches — avoids importing `langchain_ollama` in cloud-only deployments where it's not installed
- Adding a new provider: implement 3 methods, add to factory. ~50 lines, no inheritance ceremony
