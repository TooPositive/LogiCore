FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy workspace root + api project
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml

# Sync dependencies
RUN uv sync --frozen --no-dev

# Copy application code
COPY apps/api/src apps/api/src

EXPOSE 8080

CMD ["uv", "run", "uvicorn", "apps.api.src.main:app", "--host", "0.0.0.0", "--port", "8080"]
