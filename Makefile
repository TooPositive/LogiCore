.PHONY: up up-full up-kafka down logs api-dev web-dev sim-dev sync lint test build ps reset

up:
	docker compose up -d

up-full:
	docker compose --profile kafka --profile simulator up -d

up-kafka:
	docker compose --profile kafka up -d

down:
	docker compose --profile kafka --profile simulator down

logs:
	docker compose logs -f

api-dev:
	uv run uvicorn apps.api.src.main:app --host 0.0.0.0 --port 8080 --reload

web-dev:
	cd apps/web && npm run dev

sim-dev:
	cd apps/simulator && cargo run

sim-build:
	cd apps/simulator && cargo build --release

sync:
	uv sync --all-packages

lint:
	uv run ruff check apps/api/src
	uv run ruff format --check apps/api/src

test:
	uv run pytest tests/ -v

build:
	docker compose build

ps:
	docker compose ps

reset:
	docker compose --profile kafka --profile simulator down -v
	@echo "All volumes removed."
