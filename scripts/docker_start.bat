@echo off
REM Docker startup script for SentryFlow (Windows version)
REM This script starts all services using Docker Compose

SETLOCAL EnableDelayedExpansion

REM Change to project root directory
cd /d "%~dp0.."

REM Check if Docker and Docker Compose are installed
where docker >nul 2>nul
IF %ERRORLEVEL% NEQ 0 (
    echo Error: Docker is not installed. Please install Docker first.
    exit /b 1
)

docker compose version >nul 2>nul
IF %ERRORLEVEL% NEQ 0 (
    echo Error: Docker Compose is not installed. Please install Docker Compose first.
    exit /b 1
)

REM Parse command line arguments
SET BUILD=false
SET DETACH=true
SET SERVICES=

:parse_args
IF "%~1"=="" GOTO end_parse_args

IF "%~1"=="--build" (
    SET BUILD=true
    SHIFT
    GOTO parse_args
)

IF "%~1"=="--foreground" (
    SET DETACH=false
    SHIFT
    GOTO parse_args
)

IF "%~1"=="--help" (
    echo Usage: %0 [options] [services...]
    echo.
    echo Options:
    echo   --build       Build images before starting containers
    echo   --foreground  Run in foreground (don't detach)
    echo   --help        Show this help message
    echo.
    echo Services:
    echo   backend       Backend API service
    echo   frontend      Frontend web application
    echo   aggregator    Analytics aggregator service
    echo   postgres      PostgreSQL database
    echo   redis         Redis cache
    echo   kafka         Kafka message broker
    echo   zookeeper     Zookeeper (required for Kafka)
    echo   clickhouse    ClickHouse database
    echo   kafka-ui      Kafka UI web interface
    echo.
    echo If no services are specified, all services will be started.
    exit /b 0
)

SET SERVICES=!SERVICES! %1
SHIFT
GOTO parse_args

:end_parse_args

REM Check if .env files exist, create from examples if not
IF NOT EXIST "backend\.env" (
    echo Creating backend\.env from example...
    copy backend\.env.example backend\.env >nul
)

IF NOT EXIST "aggregator\.env" (
    echo Creating aggregator\.env from example...
    copy aggregator\.env.example aggregator\.env >nul
)

IF NOT EXIST "frontend\.env" (
    echo Creating frontend\.env from example...
    copy frontend\.env.example frontend\.env >nul
)

REM Build images if requested
IF "%BUILD%"=="true" (
    echo Building Docker images...
    IF "%SERVICES%"=="" (
        docker compose build
    ) ELSE (
        docker compose build %SERVICES%
    )
)

REM Start services
echo Starting services...

IF "%DETACH%"=="true" (
    IF "%SERVICES%"=="" (
        docker compose up -d
    ) ELSE (
        docker compose up -d %SERVICES%
    )
    
    echo Services started in detached mode.
    echo To view logs, run: docker compose logs -f
    echo To stop services, run: docker compose down
    
    REM Wait for services to be ready
    echo Waiting for services to be ready...
    timeout /t 5 /nobreak >nul
    
    REM Check if backend is running
    docker compose ps backend | findstr "Up" >nul
    IF %ERRORLEVEL% EQU 0 (
        echo Backend API is running at http://localhost:8000
        echo API documentation is available at http://localhost:8000/docs
    )
    
    REM Check if frontend is running
    docker compose ps frontend | findstr "Up" >nul
    IF %ERRORLEVEL% EQU 0 (
        echo Frontend is running at http://localhost:3000
    )
    
    REM Check if Kafka UI is running
    docker compose ps kafka-ui | findstr "Up" >nul
    IF %ERRORLEVEL% EQU 0 (
        echo Kafka UI is running at http://localhost:8080
    )
) ELSE (
    IF "%SERVICES%"=="" (
        docker compose up
    ) ELSE (
        docker compose up %SERVICES%
    )
)

ENDLOCAL