# CityRoute task runner. Cross-platform commands for local dev, tests, and Docker.
.PHONY: help install test lint fmt run docker-up docker-down

help:
	@echo "make install     - install dev dependencies (requirements.txt)"
	@echo "make test        - run the full pytest suite"
	@echo "make lint        - run ruff lint checks"
	@echo "make fmt         - auto-fix lint + format with ruff"
	@echo "make run         - run the API locally with reload on :8000"
	@echo "make docker-up   - build and start API + Redis via docker compose"
	@echo "make docker-down - stop the docker compose stack"

install:
	python -m pip install --upgrade pip
	pip install -r requirements.txt

test:
	python -m pytest -q

lint:
	ruff check .

fmt:
	ruff check . --fix
	ruff format .

run:
	uvicorn app.main:app --reload --port 8000

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down
