# ETL Service Makefile

.PHONY: db-up db-down test lint fmt install clean

db-up:
	docker-compose up -d mysql redis
	@echo "Waiting for MySQL..."
	@sleep 5

db-down:
	docker-compose down

install:
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

test:
	pytest tests/unit/ -v --cov=src --cov-report=term-missing

test-foundation:
	pytest tests/unit/test_foundation/ -v --cov=src/core --cov=src/utils --cov=src/infrastructure

lint:
	flake8 src/ tests/ --max-line-length=100
	mypy src/ --ignore-missing-imports

fmt:
	black src/ tests/ --line-length=100

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache htmlcov .coverage
