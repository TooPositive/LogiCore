You are writing a technical learning recap for a completed LogiCore phase. This is NOT marketing content. This is a personal technical reference that teaches the builder HOW and WHY everything works.

## Purpose

After each phase, the builder needs a document that:
1. Explains every major component built, with real code walkthroughs
2. Teaches the architectural PATTERNS used (not just "what" but "why this pattern")
3. Documents every major decision with alternatives considered and reasoning
4. Serves as interview prep / technical discussion reference
5. Links to every file so you can jump into the code

## Input

Phase number from args (e.g. `/phase-recap 2`). If not given, use most recent completed phase from `docs/PROGRESS.md`.

## Step 1: Gather Everything

Read ALL of these:
1. `docs/phases/trackers/phase-{N}-tracker.md` — what was built, decisions, deviations
2. `docs/phases/phase-{N}-*.md` — spec and business context
3. `docs/phases/reviews/phase-{N}-review.md` — what the review caught
4. All ADRs referenced in the tracker (`docs/adr/`)
5. ALL implementation files listed in tracker's "Code Artifacts"
6. ALL test files listed in tracker
7. Benchmark scripts if any

Read the ACTUAL code, not just the descriptions. The recap must reference real code.

## Step 2: Write the Recap

Save to: `docs/phases/recaps/phase-{N}-recap.md`

### Structure

```markdown
# Phase {N} Technical Recap: {Name}

## What This Phase Does (Business Context)
2-3 sentences. What real problem does this solve? Why does a logistics company need this?

## Architecture Overview
ASCII diagram of the components built and how they connect.
Show data flow: what comes in, what happens, what comes out.

## Components Built

### {Component 1}: {file path}

**What it does**: 1-2 sentences.

**The pattern**: Name the design pattern (ABC + Factory, Circuit Breaker, Strategy Pattern, etc.) and explain WHY this pattern was chosen over alternatives.

**Key code walkthrough**:
```python
# Actual code from the file, with inline comments explaining the WHY
```

**Why it matters**: What would break or be worse without this pattern?

**Alternatives considered**: What else could you have done? Why didn't you?

### {Component 2}: {file path}
[same structure]

## Key Decisions Explained

### Decision 1: {title}
- **The choice**: What was decided
- **The alternatives**: What else was on the table
- **The reasoning**: WHY (with data if available)
- **The trade-off**: What you gave up
- **When to revisit**: Under what conditions would you change this decision?
- **Interview version**: 2-3 sentence explanation you'd give in a technical interview

### Decision 2: {title}
[same structure]

## Patterns & Principles Used

For each pattern, explain:
1. What the pattern is (1 sentence)
2. Where it's used in THIS phase (specific file + line)
3. WHY it fits here (what problem it solves)
4. When you WOULDN'T use it

Examples of patterns to look for:
- Abstract Base Class (ABC) + Factory
- Strategy Pattern
- Circuit Breaker
- Graceful Degradation
- Dependency Injection (via callable)
- Config-driven behavior
- Composable wrappers
- Deterministic test doubles

## Benchmark Results & What They Mean

For each benchmark:
- What was tested and why
- The key numbers (from tracker)
- What the numbers MEAN for architecture decisions
- The boundary found (where does this approach break?)

## Test Strategy

- How the tests are organized (unit/integration/e2e/evaluation)
- What the tests PROVE (not just "48 tests pass" but "these tests prove that...")
- Key test patterns used (mocking strategy, deterministic doubles, etc.)
- What ISN'T tested and why (mapped to future phases)

## File Map

| File | Purpose | Key patterns | Lines |
|------|---------|-------------|-------|
| `path/to/file.py` | What it does | Patterns used | ~N |

## Interview Talking Points

5-8 bullet points you could bring up in a technical interview:
- Each point is a specific technical decision + reasoning
- Format: "We chose X over Y because Z. The trade-off is W. We'd revisit if Q."
- These should demonstrate ARCHITECT thinking, not just implementation

## What I'd Explain Differently Next Time

After building this, what's the clearest way to explain these concepts?
What was confusing at first but obvious in hindsight?
```

## Rules

1. **Real code only.** Every code block must reference actual file + line range.
2. **WHY > WHAT.** For every component, the explanation of WHY matters more than WHAT it does.
3. **Patterns are the point.** The specific logistics domain is secondary. The patterns (ABC, factory, circuit breaker, etc.) are transferable knowledge.
4. **Interview-ready.** Every decision should have a 2-3 sentence version you could say in an interview.
5. **Honest about gaps.** What isn't tested? What's deferred? Why?
6. **No marketing language.** This is a technical learning document, not a LinkedIn post.
7. **Link everything.** Every file mentioned should have its full path.
