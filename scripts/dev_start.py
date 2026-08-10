#!/usr/bin/env python3
"""
Development startup script for SentryFlow.

This script starts all the necessary services for local development:
- PostgreSQL database
- Redis cache
- Kafka and Zookeeper
- ClickHouse database
- Backend API service
- Analytics Aggregator
- Frontend development server
"""

import os
import sys
import time
import signal
import subprocess
import argparse
from typing import List, Dict, Any

# Define service commands
SERVICES = {
    "postgres": {
        "name": "PostgreSQL",
        "command": ["docker", "run", "--rm", "-p", "5432:5432", 
                   "-e", "POSTGRES_USER=postgres", 
                   "-e", "POSTGRES_PASSWORD=postgres", 
                   "-e", "POSTGRES_DB=sentryflow", 
                   "--name", "sentryflow-postgres", 
                   "postgres:13"],
        "ready_message": "database system is ready to accept connections",
        "required": True,
    },
    "redis": {
        "name": "Redis",
        "command": ["docker", "run", "--rm", "-p", "6379:6379", 
                   "--name", "sentryflow-redis", 
                   "redis:6"],
        "ready_message": "Ready to accept connections",
        "required": True,
    },
    "zookeeper": {
        "name": "Zookeeper",
        "command": ["docker", "run", "--rm", "-p", "2181:2181", 
                   "--name", "sentryflow-zookeeper", 
                   "zookeeper:3.7"],
        "ready_message": "binding to port",
        "required": True,
    },
    "kafka": {
        "name": "Kafka",
        "command": ["docker", "run", "--rm", "-p", "9092:9092", 
                   "-e", "KAFKA_ZOOKEEPER_CONNECT=host.docker.internal:2181", 
                   "-e", "KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://localhost:9092", 
                   "-e", "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1", 
                   "--name", "sentryflow-kafka", 
                   "confluentinc/cp-kafka:7.0.0"],
        "ready_message": "started (kafka.server.KafkaServer)",
        "required": True,
        "depends_on": ["zookeeper"],
    },
    "clickhouse": {
        "name": "ClickHouse",
        "command": ["docker", "run", "--rm", "-p", "8123:8123", "-p", "9000:9000", 
                   "--name", "sentryflow-clickhouse", 
                   "clickhouse/clickhouse-server:22"],
        "ready_message": "Ready for connections",
        "required": True,
    },
    "backend": {
        "name": "Backend API",
        "command": ["uvicorn", "main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"],
        "cwd": "backend",
        "ready_message": "Application startup complete",
        "required": True,
        "depends_on": ["postgres", "redis", "kafka"],
    },
    "aggregator": {
        "name": "Analytics Aggregator",
        "command": ["python", "batch_consumer.py"],
        "cwd": "aggregator",
        "ready_message": "Batch consumer started successfully",
        "required": True,
        "depends_on": ["kafka", "clickhouse"],
    },
    "frontend": {
        "name": "Frontend",
        "command": ["npm", "start"],
        "cwd": "frontend",
        "ready_message": "Compiled successfully",
        "required": True,
    },
}

# Global variables
processes = {}
shutdown_requested = False


def signal_handler(sig, frame):
    """Handle Ctrl+C and other termination signals."""
    global shutdown_requested
    print("\nShutdown requested. Stopping services...")
    shutdown_requested = True
    stop_all_services()
    sys.exit(0)


def start_service(service_id: str, service_config: Dict[str, Any]):
    """Start a service and return its process.
    
    Args:
        service_id: Service identifier
        service_config: Service configuration
    
    Returns:
        The started process or None if failed
    """
    print(f"Starting {service_config['name']}...")
    
    # Check if service has dependencies
    if "depends_on" in service_config:
        for dependency in service_config["depends_on"]:
            if dependency not in processes or processes[dependency] is None:
                print(f"  Dependency {dependency} not running. Skipping.")
                return None
    
    # Prepare command and environment
    command = service_config["command"]
    cwd = service_config.get("cwd", None)
    env = os.environ.copy()
    
    # Start the process
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            env=env,
        )
        
        # Wait for ready message or timeout
        ready_message = service_config.get("ready_message")
        if ready_message:
            print(f"  Waiting for {service_config['name']} to be ready...")
            start_time = time.time()
            timeout = 60  # 60 seconds timeout
            
            while time.time() - start_time < timeout:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    print(f"  {service_config['name']} failed to start.")
                    return None
                
                if ready_message in line:
                    print(f"  {service_config['name']} is ready!")
                    break
                
                # Check if process is still running
                if process.poll() is not None:
                    print(f"  {service_config['name']} exited with code {process.returncode}.")
                    return None
                
                # Sleep a bit to avoid high CPU usage
                time.sleep(0.1)
            else:
                print(f"  Timeout waiting for {service_config['name']} to be ready.")
        
        return process
    except Exception as e:
        print(f"  Error starting {service_config['name']}: {str(e)}")
        return None


def stop_service(service_id: str, process):
    """Stop a service.
    
    Args:
        service_id: Service identifier
        process: Process to stop
    """
    if process is None or process.poll() is not None:
        return
    
    print(f"Stopping {SERVICES[service_id]['name']}...")
    
    try:
        # Try to terminate gracefully first
        process.terminate()
        
        # Wait for process to terminate
        for _ in range(10):  # Wait up to 5 seconds
            if process.poll() is not None:
                break
            time.sleep(0.5)
        
        # If still running, kill it
        if process.poll() is None:
            print(f"  Forcefully killing {SERVICES[service_id]['name']}...")
            process.kill()
    except Exception as e:
        print(f"  Error stopping {SERVICES[service_id]['name']}: {str(e)}")


def stop_all_services():
    """Stop all running services in reverse order."""
    # Get service IDs in reverse order to stop dependent services first
    service_ids = list(processes.keys())
    service_ids.reverse()
    
    for service_id in service_ids:
        if service_id in processes and processes[service_id] is not None:
            stop_service(service_id, processes[service_id])
            processes[service_id] = None


def main():
    """Main function to parse arguments and start services."""
    parser = argparse.ArgumentParser(description="Start SentryFlow development services")
    parser.add_argument(
        "--services", type=str, nargs="*",
        help="Specific services to start (default: all)"
    )
    parser.add_argument(
        "--skip", type=str, nargs="*",
        help="Services to skip"
    )
    
    args = parser.parse_args()
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Determine which services to start
    services_to_start = list(SERVICES.keys())
    
    if args.services:
        # Start only specified services
        services_to_start = [s for s in args.services if s in SERVICES]
        
        # Add required dependencies
        for service_id in list(services_to_start):  # Use a copy to avoid modifying during iteration
            service_config = SERVICES[service_id]
            if "depends_on" in service_config:
                for dependency in service_config["depends_on"]:
                    if dependency not in services_to_start:
                        services_to_start.append(dependency)
    
    if args.skip:
        # Skip specified services
        services_to_start = [s for s in services_to_start if s not in args.skip]
    
    # Start services
    for service_id in services_to_start:
        service_config = SERVICES[service_id]
        process = start_service(service_id, service_config)
        processes[service_id] = process
        
        if process is None and service_config.get("required", False):
            print(f"Failed to start required service {service_config['name']}. Aborting.")
            stop_all_services()
            sys.exit(1)
    
    print("\nAll services started successfully!")
    print("Press Ctrl+C to stop all services.")
    
    # Keep the script running until interrupted
    try:
        while not shutdown_requested:
            time.sleep(1)
            
            # Check if any required service has stopped unexpectedly
            for service_id, process in processes.items():
                if process is not None and process.poll() is not None:
                    service_config = SERVICES[service_id]
                    print(f"{service_config['name']} stopped unexpectedly with code {process.returncode}.")
                    
                    if service_config.get("required", False) and not shutdown_requested:
                        print("A required service stopped unexpectedly. Shutting down all services.")
                        stop_all_services()
                        sys.exit(1)
    except KeyboardInterrupt:
        print("\nShutdown requested. Stopping services...")
        stop_all_services()


if __name__ == "__main__":
    main()