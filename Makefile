.PHONY: install demo api web test lint e2e openapi fixture benchmark

install:
	uv sync && pnpm install

demo:            ## migrate, seed, load synthetic fixture, evaluate, verify golden file
	uv run ngsirs demo

api:
	uv run uvicorn ngsirs_api.main:app --port 8000 --reload

web:
	pnpm dev

lint:
	uv run ruff check . && uv run ruff format --check . && uv run mypy

test:
	uv run pytest

e2e:
	pnpm test:e2e

openapi:
	uv run ngsirs export-openapi && pnpm gen:api

fixture:
	uv run python fixtures/ngsirs/generate.py

benchmark:
	uv run python -m scripts.benchmark_engine
