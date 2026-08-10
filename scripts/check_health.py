#!/usr/bin/env python3
"""
Health check script for SentryFlow project.

This script checks the health of all SentryFlow components:
- Backend API service
- Analytics Aggregator
- Frontend Dashboard
- PostgreSQL database
- Redis cache
- Kafka message broker
- ClickHouse database
"""

import os
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# Project root directory
ROOT_DIR = Path(__file__).parent.parent.absolute()

# Default service URLs
BACKEND_URL = "http://localhost:8000/health"
FRONTEND_URL = "http://localhost:3000"
POSTGRES_HOST = "localhost"
POSTGRES_PORT = 5432
REDIS_HOST = "localhost"
REDIS_PORT = 6379
KAFKA_HOST = "localhost"
KAFKA_PORT = 9092
CLICKHOUSE_HOST = "localhost"
CLICKHOUSE_PORT = 9000


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
        if check:
            return None
        return e.stdout
    except FileNotFoundError:
        if check:
            return None
        return "Command not found"


def check_url(url, timeout=5):
    """Check if a URL is accessible.
    
    Args:
        url: URL to check
        timeout: Timeout in seconds
    
    Returns:
        Tuple of (success, response_data)
    """
    try:
        request = Request(url)
        response = urlopen(request, timeout=timeout)
        response_data = response.read().decode("utf-8")
        return True, response_data
    except HTTPError as e:
        return False, f"HTTP Error: {e.code} {e.reason}"
    except URLError as e:
        return False, f"URL Error: {e.reason}"
    except Exception as e:
        return False, f"Error: {str(e)}"


def check_backend_health(url=BACKEND_URL):
    """Check the health of the backend API service.
    
    Args:
        url: Backend health check URL
    
    Returns:
        Tuple of (success, details)
    """
    print(f"Checking backend health at {url}...")
    success, response_data = check_url(url)
    
    if success:
        try:
            health_data = json.loads(response_data)
            if health_data.get("status") == "healthy":
                components = health_data.get("components", {})
                details = {
                    "status": "healthy",
                    "response_time_ms": health_data.get("response_time_ms"),
                    "components": components,
                }
                return True, details
            else:
                return False, {"status": "unhealthy", "details": health_data}
        except json.JSONDecodeError:
            return False, {"status": "unhealthy", "details": "Invalid JSON response"}
    else:
        return False, {"status": "unreachable", "details": response_data}


def check_frontend_health(url=FRONTEND_URL):
    """Check the health of the frontend dashboard.
    
    Args:
        url: Frontend URL
    
    Returns:
        Tuple of (success, details)
    """
    print(f"Checking frontend health at {url}...")
    success, response_data = check_url(url)
    
    if success:
        return True, {"status": "healthy", "details": "Frontend is accessible"}
    else:
        return False, {"status": "unreachable", "details": response_data}


def check_postgres_health(host=POSTGRES_HOST, port=POSTGRES_PORT):
    """Check the health of the PostgreSQL database.
    
    Args:
        host: PostgreSQL host
        port: PostgreSQL port
    
    Returns:
        Tuple of (success, details)
    """
    print(f"Checking PostgreSQL health at {host}:{port}...")
    
    # Try to connect to PostgreSQL using pg_isready
    output = run_command(["pg_isready", "-h", host, "-p", str(port)], check=False)
    
    if output is None:
        # Try with Docker if pg_isready is not available
        output = run_command(
            ["docker", "run", "--rm", "postgres:13", "pg_isready", "-h", host, "-p", str(port)],
            check=False,
        )
    
    if output is None:
        return False, {"status": "unknown", "details": "Could not check PostgreSQL health"}
    
    if "accepting connections" in output:
        return True, {"status": "healthy", "details": "PostgreSQL is accepting connections"}
    else:
        return False, {"status": "unhealthy", "details": output.strip()}


def check_redis_health(host=REDIS_HOST, port=REDIS_PORT):
    """Check the health of the Redis cache.
    
    Args:
        host: Redis host
        port: Redis port
    
    Returns:
        Tuple of (success, details)
    """
    print(f"Checking Redis health at {host}:{port}...")
    
    # Try to connect to Redis using redis-cli
    output = run_command(["redis-cli", "-h", host, "-p", str(port), "ping"], check=False)
    
    if output is None:
        # Try with Docker if redis-cli is not available
        output = run_command(
            ["docker", "run", "--rm", "redis:6", "redis-cli", "-h", host, "-p", str(port), "ping"],
            check=False,
        )
    
    if output is None:
        return False, {"status": "unknown", "details": "Could not check Redis health"}
    
    if "PONG" in output:
        return True, {"status": "healthy", "details": "Redis is responding to PING"}
    else:
        return False, {"status": "unhealthy", "details": output.strip()}


def check_kafka_health(host=KAFKA_HOST, port=KAFKA_PORT):
    """Check the health of the Kafka message broker.
    
    Args:
        host: Kafka host
        port: Kafka port
    
    Returns:
        Tuple of (success, details)
    """
    print(f"Checking Kafka health at {host}:{port}...")
    
    # Try to list Kafka topics
    output = run_command(
        ["kafka-topics", "--bootstrap-server", f"{host}:{port}", "--list"],
        check=False,
    )
    
    if output is None:
        # Try with Docker if kafka-topics is not available
        output = run_command(
            ["docker", "run", "--rm", "confluentinc/cp-kafka:7.0.0",
             "kafka-topics", "--bootstrap-server", f"{host}:{port}", "--list"],
            check=False,
        )
    
    if output is None:
        return False, {"status": "unknown", "details": "Could not check Kafka health"}
    
    if "Connection to node" in output and "failed" in output:
        return False, {"status": "unhealthy", "details": output.strip()}
    else:
        return True, {"status": "healthy", "details": "Kafka is accessible"}


def check_clickhouse_health(host=CLICKHOUSE_HOST, port=CLICKHOUSE_PORT):
    """Check the health of the ClickHouse database.
    
    Args:
        host: ClickHouse host
        port: ClickHouse port
    
    Returns:
        Tuple of (success, details)
    """
    print(f"Checking ClickHouse health at {host}:{port}...")
    
    # Try to query ClickHouse
    output = run_command(
        ["clickhouse-client", "--host", host, "--port", str(port), "--query", "SELECT 1"],
        check=False,
    )
    
    if output is None:
        # Try with Docker if clickhouse-client is not available
        output = run_command(
            ["docker", "run", "--rm", "clickhouse/clickhouse-client:latest",
             "--host", host, "--port", str(port), "--query", "SELECT 1"],
            check=False,
        )
    
    if output is None:
        return False, {"status": "unknown", "details": "Could not check ClickHouse health"}
    
    if "Connection refused" in output or "Failed" in output:
        return False, {"status": "unhealthy", "details": output.strip()}
    elif "1" in output:
        return True, {"status": "healthy", "details": "ClickHouse is accessible"}
    else:
        return False, {"status": "unhealthy", "details": output.strip()}


def main():
    """Main function to check system health."""
    parser = argparse.ArgumentParser(description="Check health of SentryFlow components")
    parser.add_argument(
        "--backend-url", type=str, default=BACKEND_URL,
        help=f"Backend health check URL (default: {BACKEND_URL})"
    )
    parser.add_argument(
        "--frontend-url", type=str, default=FRONTEND_URL,
        help=f"Frontend URL (default: {FRONTEND_URL})"
    )
    parser.add_argument(
        "--postgres-host", type=str, default=POSTGRES_HOST,
        help=f"PostgreSQL host (default: {POSTGRES_HOST})"
    )
    parser.add_argument(
        "--postgres-port", type=int, default=POSTGRES_PORT,
        help=f"PostgreSQL port (default: {POSTGRES_PORT})"
    )
    parser.add_argument(
        "--redis-host", type=str, default=REDIS_HOST,
        help=f"Redis host (default: {REDIS_HOST})"
    )
    parser.add_argument(
        "--redis-port", type=int, default=REDIS_PORT,
        help=f"Redis port (default: {REDIS_PORT})"
    )
    parser.add_argument(
        "--kafka-host", type=str, default=KAFKA_HOST,
        help=f"Kafka host (default: {KAFKA_HOST})"
    )
    parser.add_argument(
        "--kafka-port", type=int, default=KAFKA_PORT,
        help=f"Kafka port (default: {KAFKA_PORT})"
    )
    parser.add_argument(
        "--clickhouse-host", type=str, default=CLICKHOUSE_HOST,
        help=f"ClickHouse host (default: {CLICKHOUSE_HOST})"
    )
    parser.add_argument(
        "--clickhouse-port", type=int, default=CLICKHOUSE_PORT,
        help=f"ClickHouse port (default: {CLICKHOUSE_PORT})"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output results in JSON format"
    )
    parser.add_argument(
        "--ci", action="store_true",
        help="Run in CI mode (exit with error code on failure)"
    )
    
    args = parser.parse_args()
    
    # Check health of all components
    results = {}
    
    # Backend
    backend_success, backend_details = check_backend_health(args.backend_url)
    results["backend"] = {
        "success": backend_success,
        "details": backend_details,
    }
    
    # Frontend
    frontend_success, frontend_details = check_frontend_health(args.frontend_url)
    results["frontend"] = {
        "success": frontend_success,
        "details": frontend_details,
    }
    
    # PostgreSQL
    postgres_success, postgres_details = check_postgres_health(
        args.postgres_host, args.postgres_port
    )
    results["postgres"] = {
        "success": postgres_success,
        "details": postgres_details,
    }
    
    # Redis
    redis_success, redis_details = check_redis_health(
        args.redis_host, args.redis_port
    )
    results["redis"] = {
        "success": redis_success,
        "details": redis_details,
    }
    
    # Kafka
    kafka_success, kafka_details = check_kafka_health(
        args.kafka_host, args.kafka_port
    )
    results["kafka"] = {
        "success": kafka_success,
        "details": kafka_details,
    }
    
    # ClickHouse
    clickhouse_success, clickhouse_details = check_clickhouse_health(
        args.clickhouse_host, args.clickhouse_port
    )
    results["clickhouse"] = {
        "success": clickhouse_success,
        "details": clickhouse_details,
    }
    
    # Overall health
    overall_success = all([
        backend_success,
        frontend_success,
        postgres_success,
        redis_success,
        kafka_success,
        clickhouse_success,
    ])
    
    # Output results
    if args.json:
        # JSON output
        print(json.dumps({
            "timestamp": time.time(),
            "overall": {
                "success": overall_success,
                "status": "healthy" if overall_success else "unhealthy",
            },
            "components": results,
        }, indent=2))
    else:
        # Human-readable output
        print_header("Health Check Results")
        print(f"Overall: {'HEALTHY' if overall_success else 'UNHEALTHY'}\n")
        
        for component, result in results.items():
            status = "HEALTHY" if result["success"] else "UNHEALTHY"
            print(f"{component.upper()}: {status}")
            print(f"  Details: {result['details']['status']}")
            if "details" in result["details"]:
                print(f"  {result['details']['details']}")
            print()
    
    # Exit with error code if any component is unhealthy in CI mode
    if args.ci and not overall_success:
        sys.exit(1)


if __name__ == "__main__":
    main()