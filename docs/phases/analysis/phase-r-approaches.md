---
phase: R
date: "2026-03-08"
selected: A
---

# Phase R Implementation Approaches

## Approach A: In-Place Split (Subdirectories)

**Summary**: Create `core/` and `domains/logicore/` as subdirectories inside `apps/api/src/`. Minimal structural change, imports stay within `apps.api.src.*` namespace.

**Structure**:
```
apps/api/src/
├── core/
│   ├── rag/           # from apps/api/src/rag/
│   ├── security/      # from apps/api/src/security/ (core parts)
│   ├── telemetry/     # from apps/api/src/telemetry/
│   ├── infrastructure/ # from apps/api/src/infrastructure/
│   ├── domain/        # core models (document.py, telemetry.py)
│   ├── config/        # from apps/api/src/config/
│   ├── api/           # core endpoints (health, search, ingest, analytics)
│   └── graphs/        # core graph patterns
├── domains/
│   └── logicore/
│       ├── agents/    # reader, auditor
│       ├── tools/     # sql_query, report_generator
│       ├── models/    # audit.py domain models
│       ├── graphs/    # audit_graph node implementations
│       ├── data/      # corpus, golden set
│       └── api/       # audit endpoint
└── main.py            # wires core + selected domain
```

**Import change**: `from apps.api.src.rag.retriever` → `from apps.api.src.core.rag.retriever`

**Pros**:
- Single uv workspace, single pyproject.toml
- Import paths stay in `apps.api.src.*` namespace (smaller diff)
- No Python packaging changes
- Incremental: move one directory at a time, run tests

**Cons**:
- Deep nesting: `apps.api.src.core.rag.retriever` is verbose
- `core/` and `domains/` are peers inside the app, not independent packages
- No enforcement that core doesn't import domain (just convention)

**Effort**: S (2-3 days)
**Risk**: Low — purely additive directory moves

## Approach B: Top-Level Packages

**Summary**: Create `core/` and `domains/` as top-level Python packages alongside `apps/`. Each is an independent importable package.

**Structure**:
```
core/
├── rag/
├── security/
├── telemetry/
├── infrastructure/
├── domain/
├── config/
├── api/
└── graphs/
domains/
└── logicore/
    ├── agents/
    ├── tools/
    ├── models/
    ├── graphs/
    ├── data/
    └── api/
apps/
└── api/
    └── src/
        └── main.py    # wires core + domain, starts FastAPI
```

**Import change**: `from apps.api.src.rag.retriever` → `from core.rag.retriever`

**Pros**:
- Clean, short imports: `from core.rag.retriever import ...`
- Physical separation enforces dependency direction
- Each package could become its own pip-installable library
- Clear for external contributors

**Cons**:
- Requires updating pyproject.toml (uv workspace or editable installs)
- Docker build context changes
- More import paths to update (~200+)
- Bigger blast radius per commit

**Effort**: M (3-5 days)
**Risk**: Medium — Python packaging + Docker changes add complexity

## Approach C: Minimal Extraction (Domain Config Only)

**Summary**: Don't move files. Instead, extract domain-specific DATA (users, prompts, thresholds) into a `domains/logicore/config.py` that core code reads. Code stays in `apps/api/src/`, but all hardcoded LogiCore references become config-driven.

**Structure**:
```
apps/api/src/           # unchanged structure
domains/
└── logicore/
    ├── config.py       # users, prompts, thresholds, table names
    ├── corpus/         # benchmark data
    └── golden_set/     # eval data
```

**Import change**: Minimal — just parameterize existing code to accept config.

**Pros**:
- Smallest diff, lowest risk
- No import path changes
- Tests stay exactly as-is
- Still achieves "swap domain config" goal

**Cons**:
- Code structure doesn't communicate the core/domain split
- Mixed files stay mixed (just parameterized)
- New developer can't see at a glance what's core vs domain
- Doesn't set up for true multi-domain (separate agent implementations)

**Effort**: XS (1-2 days)
**Risk**: Very low — no structural moves

## Recommendation

**Approach A (In-Place Split)** balances clarity with safety:
- Physical directory split makes core/domain boundary visible
- Single workspace avoids packaging headaches
- Incremental moves keep 867 tests green after each step
- Import verbosity is acceptable (`apps.api.src.core.*` is clear)

Approach B is architecturally cleaner but adds packaging complexity that isn't needed yet. Approach C is too minimal — the goal is structural clarity, not just parameterization.

**But the human decides.**
