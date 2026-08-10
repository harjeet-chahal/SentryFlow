# SentryFlow Makefile

.PHONY: help setup dev-backend dev-frontend dev-aggregator test lint clean docker-build docker-up docker-down

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Setup the project (install dependencies, create .env files)
	@echo "Setting up SentryFlow project..."
	@if [ ! -f "backend/.env" ]; then cp backend/.env.example backend/.env; fi
	@if [ ! -f "aggregator/.env" ]; then cp aggregator/.env.example aggregator/.env; fi
	@if [ ! -f "frontend/.env" ]; then cp frontend/.env.example frontend/.env; fi
	@echo "Installing backend dependencies..."
	cd backend && pip install -r requirements.txt
	@echo "Installing aggregator dependencies..."
	cd aggregator && pip install -r requirements.txt
	@echo "Installing frontend dependencies..."
	cd frontend && npm install
	@echo "Setup complete!"

dev-backend: ## Run backend in development mode
	cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 8000

dev-frontend: ## Run frontend in development mode
	cd frontend && npm start

dev-aggregator: ## Run aggregator in development mode
	cd aggregator && python batch_consumer.py

test: ## Run all tests
	@echo "Running backend tests..."
	cd backend && pytest
	@echo "Running aggregator tests..."
	cd aggregator && pytest
	@echo "Running frontend tests..."
	cd frontend && npm test

test-backend: ## Run backend tests
	cd backend && pytest

test-aggregator: ## Run aggregator tests
	cd aggregator && pytest

test-frontend: ## Run frontend tests
	cd frontend && npm test

lint: ## Run linters
	@echo "Linting backend code..."
	cd backend && flake8
	@echo "Linting aggregator code..."
	cd aggregator && flake8
	@echo "Linting frontend code..."
	cd frontend && npm run lint

clean: ## Clean up temporary files
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .coverage -exec rm -rf {} +
	find . -type d -name node_modules -exec rm -rf {} +
	find . -type d -name build -exec rm -rf {} +

# Docker commands
docker-build: ## Build all Docker images
	docker-compose build

docker-up: ## Start all services with Docker Compose
	docker-compose up -d

docker-down: ## Stop all services with Docker Compose
	docker-compose down

docker-logs: ## View logs from all services
	docker-compose logs -f

docker-ps: ## List running containers
	docker-compose ps

# Database commands
db-setup: ## Setup the database (create tables, initial data)
	cd backend && python setup_db.py

clickhouse-setup: ## Setup ClickHouse database (create tables)
	cd aggregator && python setup_clickhouse.py

# Default target
.DEFAULT_GOAL := help