#!/usr/bin/env python3
"""
Test runner script for SentryFlow project.

This script runs tests for all components of the SentryFlow project:
- Backend API service
- Analytics Aggregator
- Frontend Dashboard
"""

import os
import sys
import argparse
import subprocess
from pathlib import Path

# Project root directory
ROOT_DIR = Path(__file__).parent.parent.absolute()

# Components directories
BACKEND_DIR = ROOT_DIR / "backend"
AGGREGATOR_DIR = ROOT_DIR / "aggregator"
FRONTEND_DIR = ROOT_DIR / "frontend"


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
            return None
        return e.stdout


def run_backend_tests(coverage=False, verbose=False):
    """Run backend tests.
    
    Args:
        coverage: Whether to generate coverage report
        verbose: Whether to run tests in verbose mode
    
    Returns:
        True if tests passed, False otherwise
    """
    print_header("Running backend tests")
    
    # Build command
    command = ["pytest"]
    
    if coverage:
        command.extend(["--cov=app", "--cov-report=term", "--cov-report=html:coverage_html"])
    
    if verbose:
        command.append("-v")
    
    # Run tests
    output = run_command(command, cwd=BACKEND_DIR, check=False)
    
    if output is None:
        print("Backend tests failed")
        return False
    
    print(output)
    return "failed" not in output.lower()


def run_aggregator_tests(coverage=False, verbose=False):
    """Run aggregator tests.
    
    Args:
        coverage: Whether to generate coverage report
        verbose: Whether to run tests in verbose mode
    
    Returns:
        True if tests passed, False otherwise
    """
    print_header("Running aggregator tests")
    
    # Build command
    command = ["pytest"]
    
    if coverage:
        command.extend(["--cov=app", "--cov-report=term", "--cov-report=html:coverage_html"])
    
    if verbose:
        command.append("-v")
    
    # Run tests
    output = run_command(command, cwd=AGGREGATOR_DIR, check=False)
    
    if output is None:
        print("Aggregator tests failed")
        return False
    
    print(output)
    return "failed" not in output.lower()


def run_frontend_tests(coverage=False, verbose=False):
    """Run frontend tests.
    
    Args:
        coverage: Whether to generate coverage report
        verbose: Whether to run tests in verbose mode
    
    Returns:
        True if tests passed, False otherwise
    """
    print_header("Running frontend tests")
    
    # Build command
    if coverage:
        command = ["npm", "test", "--", "--coverage"]
    else:
        command = ["npm", "test"]
    
    if verbose:
        command.append("--verbose")
    
    # Run tests
    output = run_command(command, cwd=FRONTEND_DIR, check=False)
    
    if output is None:
        print("Frontend tests failed")
        return False
    
    print(output)
    return "failed" not in output.lower()


def run_frontend_lint():
    """Run frontend linting.
    
    Returns:
        True if linting passed, False otherwise
    """
    print_header("Running frontend linting")
    
    # Run linting
    output = run_command(["npm", "run", "lint"], cwd=FRONTEND_DIR, check=False)
    
    if output is None:
        print("Frontend linting failed")
        return False
    
    print(output)
    return "error" not in output.lower()


def run_backend_lint():
    """Run backend linting.
    
    Returns:
        True if linting passed, False otherwise
    """
    print_header("Running backend linting")
    
    # Check if flake8 is installed
    try:
        run_command(["flake8", "--version"])
    except FileNotFoundError:
        print("flake8 is not installed. Installing...")
        run_command(["pip", "install", "flake8"])
    
    # Run linting
    output = run_command(["flake8"], cwd=BACKEND_DIR, check=False)
    
    if output is None:
        print("Backend linting failed")
        return False
    
    if output.strip():
        print(output)
        return False
    
    print("Backend linting passed")
    return True


def run_aggregator_lint():
    """Run aggregator linting.
    
    Returns:
        True if linting passed, False otherwise
    """
    print_header("Running aggregator linting")
    
    # Check if flake8 is installed
    try:
        run_command(["flake8", "--version"])
    except FileNotFoundError:
        print("flake8 is not installed. Installing...")
        run_command(["pip", "install", "flake8"])
    
    # Run linting
    output = run_command(["flake8"], cwd=AGGREGATOR_DIR, check=False)
    
    if output is None:
        print("Aggregator linting failed")
        return False
    
    if output.strip():
        print(output)
        return False
    
    print("Aggregator linting passed")
    return True


def main():
    """Main function to run tests."""
    parser = argparse.ArgumentParser(description="Run tests for SentryFlow project")
    parser.add_argument(
        "--component", "-c", type=str, choices=["backend", "aggregator", "frontend", "all"],
        default="all", help="Component to test (default: all)"
    )
    parser.add_argument(
        "--coverage", action="store_true", help="Generate coverage report"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Run tests in verbose mode"
    )
    parser.add_argument(
        "--lint", "-l", action="store_true", help="Run linting"
    )
    parser.add_argument(
        "--ci", action="store_true", help="Run in CI mode (exit with error code on failure)"
    )
    
    args = parser.parse_args()
    
    # Track test results
    results = {}
    
    # Run tests for selected components
    if args.component in ["backend", "all"]:
        if args.lint:
            results["backend_lint"] = run_backend_lint()
        results["backend_tests"] = run_backend_tests(args.coverage, args.verbose)
    
    if args.component in ["aggregator", "all"]:
        if args.lint:
            results["aggregator_lint"] = run_aggregator_lint()
        results["aggregator_tests"] = run_aggregator_tests(args.coverage, args.verbose)
    
    if args.component in ["frontend", "all"]:
        if args.lint:
            results["frontend_lint"] = run_frontend_lint()
        results["frontend_tests"] = run_frontend_tests(args.coverage, args.verbose)
    
    # Print summary
    print_header("Test Summary")
    for test, passed in results.items():
        print(f"{test}: {'PASSED' if passed else 'FAILED'}")
    
    # Exit with error code if any test failed in CI mode
    if args.ci and not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()