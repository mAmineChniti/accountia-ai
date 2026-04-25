.PHONY: help install dev lint format test test-cov clean ci build check

help:
	@echo "Available commands:"
	@echo "  make install    - Install production dependencies"
	@echo "  make dev        - Install development dependencies"
	@echo "  make lint       - Run ruff linter"
	@echo "  make format     - Format code with ruff"
	@echo "  make check      - Run lint + format check (CI mode)"
	@echo "  make test       - Run tests"
	@echo "  make test-cov   - Run tests with coverage"
	@echo "  make ci         - Run full CI pipeline (lint + test)"
	@echo "  make clean      - Clean cache and temp files"
	@echo "  make build      - Verify app builds correctly"

install:
	pip install -r requirements.txt

dev:
	pip install -r requirements.txt
	pip install ruff pytest-asyncio httpx

lint:
	ruff check app/

format:
	ruff format app/

check:
	ruff check --select E,W,F,I app/
	ruff format --check app/

test:
	pytest tests/ -v

test-cov:
	pytest tests/ -v --cov=app --cov-report=term-missing --cov-report=html

ci: check test

build:
	python -c "from app.main import app; print('✓ App builds successfully')"

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true
