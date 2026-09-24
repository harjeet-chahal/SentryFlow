# SentryFlow

.PHONY: help setup test test-backend test-aggregator test-integration test-frontend \
        lint clean dev-backend dev-frontend dev-aggregator \
        docker-build docker-up docker-down docker-logs docker-ps \
        db-setup clickhouse-setup helm-lint helm-template k8s-validate

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Install dependencies and create .env files
	@if [ ! -f "backend/.env" ]; then cp backend/.env.example backend/.env; fi
	@if [ ! -f "aggregator/.env" ]; then cp aggregator/.env.example aggregator/.env; fi
	@if [ ! -f "frontend/.env" ]; then cp frontend/.env.example frontend/.env; fi
	cd backend && pip install -r requirements.txt
	cd aggregator && pip install -r requirements.txt
	cd frontend && npm install
	@echo "Setup complete."

# --- Development ------------------------------------------------------------

dev-backend: ## Run the gateway with reload
	uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend: ## Run the dashboard dev server
	cd frontend && npm start

dev-aggregator: ## Run the Kafka -> ClickHouse aggregator
	python -m aggregator.batch_consumer

# --- Tests ------------------------------------------------------------------

test: test-backend test-aggregator test-frontend ## Run all unit test suites

test-backend: ## Run backend tests with coverage (fails under 90%)
	cd backend && pytest

test-aggregator: ## Run aggregator tests with coverage (fails under 90%)
	cd aggregator && pytest

# Needs a ClickHouse, e.g. the compose one: make docker-up first.
test-integration: ## Run the analytics SQL against a real ClickHouse
	cd backend && CLICKHOUSE_TEST_HOST=$${CLICKHOUSE_TEST_HOST:-localhost} \
		CLICKHOUSE_TEST_USER=$${CLICKHOUSE_TEST_USER:-sentryflow} \
		CLICKHOUSE_TEST_PASSWORD=$${CLICKHOUSE_TEST_PASSWORD:-sentryflow} \
		pytest tests/integration --no-cov

test-frontend: ## Run frontend tests
	cd frontend && npm test -- --watchAll=false --passWithNoTests

coverage: ## Open the backend HTML coverage report
	cd backend && pytest && open coverage_html/index.html

lint: ## Lint backend and frontend
	cd backend && flake8 --max-line-length 100 --exclude __pycache__,coverage_html
	cd frontend && npx eslint src --ext .js

# --- Docker -----------------------------------------------------------------

docker-build: ## Build all images
	docker compose build

docker-up: ## Build and start the full stack
	docker compose up -d --build

docker-down: ## Stop the stack
	docker compose down

docker-logs: ## Tail logs from all services
	docker compose logs -f

docker-ps: ## List running containers
	docker compose ps

# --- Data stores ------------------------------------------------------------

db-setup: ## Create tables and seed the admin user (idempotent)
	python -m backend.setup_db

clickhouse-setup: ## Create the ClickHouse table (the aggregator also does this)
	python -m aggregator.setup_clickhouse

# --- Kubernetes -------------------------------------------------------------

helm-lint: ## Lint the Helm chart
	helm lint kubernetes/chart --set secrets.postgresPassword=placeholder

helm-template: ## Render the chart to stdout
	@helm template sentryflow kubernetes/chart \
		--set secrets.postgresPassword=placeholder --set ingress.enabled=true

k8s-validate: ## Validate rendered manifests against Kubernetes schemas
	@$(MAKE) --no-print-directory helm-template \
		| kubeconform -kubernetes-version 1.29.0 -strict -summary

# --- Housekeeping -----------------------------------------------------------

clean: ## Remove build and test artefacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	rm -rf backend/coverage_html backend/.coverage frontend/build

.DEFAULT_GOAL := help
