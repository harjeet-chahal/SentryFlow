#!/usr/bin/env python3
"""
Initialization script for SentryFlow project.

This script performs the following tasks:
1. Creates .env files from .env.example files if they don't exist
2. Sets up the PostgreSQL database
3. Sets up the ClickHouse database
4. Creates necessary Kafka topics
5. Installs dependencies for backend, aggregator, and frontend
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

# Project root directory
ROOT_DIR = Path(__file__).parent.parent.absolute()

# Components directories
BACKEND_DIR = ROOT_DIR / "backend"
AGGREGATOR_DIR = ROOT_DIR / "aggregator"
FRONTEND_DIR = ROOT_DIR / "frontend"

# Kafka topics to create
KAFKA_TOPICS = [
    "api-requests",
    "rate-limited-events",
]


def print_header(message):
    """Print a header message."""
    print("\n" + "=" * 80)
    print(f" {message}")
    print("=" * 80)


def run_command(command, cwd=None, env=None, check=True):
    """Run a command and return its output.
    
    Args:
        command: Command to run as a list of strings
        cwd: Working directory for the command
        env: Environment variables for the command
        check: Whether to check the return code
    
    Returns:
        Command output as a string
    """
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=check,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit code {e.returncode}:")
        print(e.stdout)
        if check:
            sys.exit(1)
        return e.stdout


def create_env_files():
    """Create .env files from .env.example files if they don't exist."""
    print_header("Creating .env files")
    
    # Backend .env file
    backend_env = BACKEND_DIR / ".env"
    backend_env_example = BACKEND_DIR / ".env.example"
    if not backend_env.exists() and backend_env_example.exists():
        print(f"Creating {backend_env}...")
        shutil.copy(backend_env_example, backend_env)
        print(f"Created {backend_env}")
    elif not backend_env_example.exists():
        print(f"Warning: {backend_env_example} does not exist")
    else:
        print(f"{backend_env} already exists")
    
    # Aggregator .env file
    aggregator_env = AGGREGATOR_DIR / ".env"
    aggregator_env_example = AGGREGATOR_DIR / ".env.example"
    if not aggregator_env.exists() and aggregator_env_example.exists():
        print(f"Creating {aggregator_env}...")
        shutil.copy(aggregator_env_example, aggregator_env)
        print(f"Created {aggregator_env}")
    elif not aggregator_env_example.exists():
        print(f"Warning: {aggregator_env_example} does not exist")
    else:
        print(f"{aggregator_env} already exists")
    
    # Frontend .env file
    frontend_env = FRONTEND_DIR / ".env"
    frontend_env_example = FRONTEND_DIR / ".env.example"
    if not frontend_env.exists() and frontend_env_example.exists():
        print(f"Creating {frontend_env}...")
        shutil.copy(frontend_env_example, frontend_env)
        print(f"Created {frontend_env}")
    elif not frontend_env_example.exists():
        print(f"Warning: {frontend_env_example} does not exist")
    else:
        print(f"{frontend_env} already exists")


def install_dependencies():
    """Install dependencies for backend, aggregator, and frontend."""
    print_header("Installing dependencies")
    
    # Check if pip is available
    try:
        run_command(["pip", "--version"])
    except FileNotFoundError:
        print("Error: pip is not installed or not in PATH")
        sys.exit(1)
    
    # Check if npm is available
    try:
        run_command(["npm", "--version"])
    except FileNotFoundError:
        print("Error: npm is not installed or not in PATH")
        sys.exit(1)
    
    # Install backend dependencies
    print("Installing backend dependencies...")
    run_command(["pip", "install", "-r", "requirements.txt"], cwd=BACKEND_DIR)
    print("Backend dependencies installed")
    
    # Install aggregator dependencies
    print("Installing aggregator dependencies...")
    run_command(["pip", "install", "-r", "requirements.txt"], cwd=AGGREGATOR_DIR)
    print("Aggregator dependencies installed")
    
    # Install frontend dependencies
    print("Installing frontend dependencies...")
    run_command(["npm", "install"], cwd=FRONTEND_DIR)
    print("Frontend dependencies installed")


def setup_database():
    """Set up the PostgreSQL database."""
    print_header("Setting up PostgreSQL database")
    
    # Check if PostgreSQL is running
    print("Checking if PostgreSQL is running...")
    try:
        # Try to connect to PostgreSQL
        run_command(["docker", "run", "--rm", "postgres:13", "pg_isready", "-h", "host.docker.internal", "-p", "5432"])
        print("PostgreSQL is running")
    except subprocess.CalledProcessError:
        print("Warning: PostgreSQL is not running or not accessible")
        print("You may need to start PostgreSQL manually")
    
    # Run database setup script
    print("Running database setup script...")
    try:
        run_command(["python", "setup_db.py"], cwd=BACKEND_DIR)
        print("Database setup completed")
    except subprocess.CalledProcessError:
        print("Warning: Database setup failed")
        print("You may need to set up the database manually")


def setup_clickhouse():
    """Set up the ClickHouse database."""
    print_header("Setting up ClickHouse database")
    
    # Check if ClickHouse is running
    print("Checking if ClickHouse is running...")
    try:
        # Try to connect to ClickHouse
        run_command(["docker", "run", "--rm", "clickhouse/clickhouse-client:latest", "--host", "host.docker.internal", "--query", "SELECT 1"])
        print("ClickHouse is running")
    except subprocess.CalledProcessError:
        print("Warning: ClickHouse is not running or not accessible")
        print("You may need to start ClickHouse manually")
    
    # Run ClickHouse setup script
    print("Running ClickHouse setup script...")
    try:
        run_command(["python", "setup_clickhouse.py"], cwd=AGGREGATOR_DIR)
        print("ClickHouse setup completed")
    except subprocess.CalledProcessError:
        print("Warning: ClickHouse setup failed")
        print("You may need to set up ClickHouse manually")


def create_kafka_topics():
    """Create necessary Kafka topics."""
    print_header("Creating Kafka topics")
    
    # Check if Kafka is running
    print("Checking if Kafka is running...")
    try:
        # Try to list Kafka topics
        run_command(["docker", "run", "--rm", "confluentinc/cp-kafka:7.0.0", "kafka-topics", "--bootstrap-server", "host.docker.internal:9092", "--list"])
        print("Kafka is running")
    except subprocess.CalledProcessError:
        print("Warning: Kafka is not running or not accessible")
        print("You may need to start Kafka manually")
        return
    
    # Create Kafka topics
    for topic in KAFKA_TOPICS:
        print(f"Creating Kafka topic {topic}...")
        try:
            run_command([
                "docker", "run", "--rm", "confluentinc/cp-kafka:7.0.0",
                "kafka-topics",
                "--bootstrap-server", "host.docker.internal:9092",
                "--create",
                "--if-not-exists",
                "--topic", topic,
                "--partitions", "3",
                "--replication-factor", "1",
            ])
            print(f"Kafka topic {topic} created or already exists")
        except subprocess.CalledProcessError:
            print(f"Warning: Failed to create Kafka topic {topic}")


def main():
    """Main function to initialize the project."""
    print_header("Initializing SentryFlow project")
    
    # Create .env files
    create_env_files()
    
    # Install dependencies
    install_dependencies()
    
    # Set up databases and Kafka topics
    setup_database()
    setup_clickhouse()
    create_kafka_topics()
    
    print_header("Project initialization completed")
    print("You can now start the project using:")
    print("  - For development: python scripts/dev_start.py")
    print("  - With Docker: scripts/docker_start.bat (Windows) or scripts/docker_start.sh (Linux/macOS)")


if __name__ == "__main__":
    main()