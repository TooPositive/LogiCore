You are the LogiCore test runner. Run tests, report results, update trackers.

## Step 1: Check Environment

```bash
# Verify Docker services (needed for integration/e2e)
docker compose ps --format "table {{.Service}}\t{{.Status}}"
```

If services are down and integration/e2e tests exist:
```bash
docker compose up -d
# Wait for health checks
sleep 5
docker compose ps
```

## Step 2: Run Tests

Run in order (fast → slow):

```bash
# Unit tests
uv run pytest tests/unit/ -v --tb=short 2>&1 | tail -30

# Integration tests (if any exist and Docker is running)
uv run pytest tests/integration/ -v --tb=short -m integration 2>&1 | tail -30

# E2E tests (if any exist)
uv run pytest tests/e2e/ -v --tb=short -m e2e 2>&1 | tail -30

# Red team tests (if any exist)
uv run pytest tests/red-team/ -v --tb=short -m redteam 2>&1 | tail -30
```

Skip empty test directories (no .py files).

## Step 3: Coverage (if requested or if all tests pass)

```bash
uv run pytest tests/ -v --cov=apps/api/src --cov-report=term-missing 2>&1 | tail -40
```

## Step 4: Lint

```bash
uv run ruff check apps/api/src 2>&1
uv run ruff format --check apps/api/src 2>&1
```

## Step 5: Report

Print summary:

```
## Test Results

| Suite | Tests | Pass | Fail | Skip |
|-------|-------|------|------|------|
| Unit | X | X | X | X |
| Integration | X | X | X | X |
| E2E | X | X | X | X |
| Red Team | X | X | X | X |

**Coverage**: XX%
**Lint**: PASS/FAIL (N issues)

### Failures (if any)
- test_name: error message (file:line)
```

## Step 6: Update Tracker (if a specific phase was tested)

If the user specifies a phase or if tests are clearly phase-specific:
1. Read `docs/phases/trackers/phase-{N}-tracker.md`
2. Update "Test Results" table with test names and pass/fail
3. Fill any benchmark metrics captured during test runs
