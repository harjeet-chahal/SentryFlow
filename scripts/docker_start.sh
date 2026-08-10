#!/bin/bash

# Docker startup script for SentryFlow
# This script starts all services using Docker Compose

set -e

# Change to project root directory
cd "$(dirname "$0")/.." || exit 1

# Check if Docker and Docker Compose are installed
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed. Please install Docker first."
    exit 1
fi

if ! docker compose version &> /dev/null; then
    echo "Error: Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

# Parse command line arguments
BUILD=false
DETACH=true
SERVICES=()

while [[ $# -gt 0 ]]; do
    case $1 in
        --build)
            BUILD=true
            shift
            ;;
        --foreground)
            DETACH=false
            shift
            ;;
        --help)
            echo "Usage: $0 [options] [services...]"
            echo ""
            echo "Options:"
            echo "  --build       Build images before starting containers"
            echo "  --foreground  Run in foreground (don't detach)"
            echo "  --help        Show this help message"
            echo ""
            echo "Services:"
            echo "  backend       Backend API service"
            echo "  frontend      Frontend web application"
            echo "  aggregator    Analytics aggregator service"
            echo "  postgres      PostgreSQL database"
            echo "  redis         Redis cache"
            echo "  kafka         Kafka message broker"
            echo "  zookeeper     Zookeeper (required for Kafka)"
            echo "  clickhouse    ClickHouse database"
            echo "  kafka-ui      Kafka UI web interface"
            echo ""
            echo "If no services are specified, all services will be started."
            exit 0
            ;;
        *)
            SERVICES+=("$1")
            shift
            ;;
    esac
done

# Check if .env files exist, create from examples if not
if [ ! -f "backend/.env" ]; then
    echo "Creating backend/.env from example..."
    cp backend/.env.example backend/.env
fi

if [ ! -f "aggregator/.env" ]; then
    echo "Creating aggregator/.env from example..."
    cp aggregator/.env.example aggregator/.env
fi

if [ ! -f "frontend/.env" ]; then
    echo "Creating frontend/.env from example..."
    cp frontend/.env.example frontend/.env
fi

# Build images if requested
if [ "$BUILD" = true ]; then
    echo "Building Docker images..."
    if [ ${#SERVICES[@]} -eq 0 ]; then
        docker compose build
    else
        docker compose build "${SERVICES[@]}"
    fi
fi

# Start services
echo "Starting services..."

if [ "$DETACH" = true ]; then
    if [ ${#SERVICES[@]} -eq 0 ]; then
        docker compose up -d
    else
        docker compose up -d "${SERVICES[@]}"
    fi
    
    echo "Services started in detached mode."
    echo "To view logs, run: docker compose logs -f"
    echo "To stop services, run: docker compose down"
    
    # Wait for services to be ready
    echo "Waiting for services to be ready..."
    sleep 5
    
    # Check if backend is running
    if docker compose ps backend | grep -q "Up"; then
        echo "Backend API is running at http://localhost:8000"
        echo "API documentation is available at http://localhost:8000/docs"
    fi
    
    # Check if frontend is running
    if docker compose ps frontend | grep -q "Up"; then
        echo "Frontend is running at http://localhost:3000"
    fi
    
    # Check if Kafka UI is running
    if docker compose ps kafka-ui | grep -q "Up"; then
        echo "Kafka UI is running at http://localhost:8080"
    fi
else
    if [ ${#SERVICES[@]} -eq 0 ]; then
        docker compose up
    else
        docker compose up "${SERVICES[@]}"
    fi
fi