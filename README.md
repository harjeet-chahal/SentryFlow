# SentryFlow

<div align="center">

![SentryFlow Logo](docs/logo.svg)

**A comprehensive API monitoring and management system**

</div>

## Overview

SentryFlow is a robust API monitoring and management system designed to help developers track, analyze, and optimize their API usage. It provides real-time metrics, rate limiting, authentication, and comprehensive logging to ensure your APIs are secure, performant, and reliable.

## Features

- **API Key Management**: Create, manage, and revoke API keys with fine-grained permissions
- **Rate Limiting**: Implement sliding window and token bucket rate limiting algorithms
- **Real-time Monitoring**: Track API usage, response times, and error rates in real-time
- **User-specific Analytics**: View metrics and usage patterns for individual users
- **Comprehensive Logging**: Log all API requests with detailed information for auditing and debugging
- **Interactive Dashboard**: Visualize API performance and usage through intuitive charts and graphs
- **Alerts and Notifications**: Get notified when API usage exceeds thresholds or errors occur

## Architecture

SentryFlow consists of three main components:

1. **Backend API Service**: A FastAPI application that handles authentication, rate limiting, and request logging
2. **Analytics Aggregator**: A service that consumes API logs from Kafka and aggregates metrics in ClickHouse
3. **Frontend Dashboard**: A React application that visualizes API metrics and provides management interfaces

### Technology Stack

- **Backend**: FastAPI, SQLAlchemy, Redis, Kafka
- **Analytics**: ClickHouse, Kafka Consumers
- **Frontend**: React, Chart.js, Tailwind CSS
- **Infrastructure**: Docker, GitHub Actions

## Getting Started

### Prerequisites

- Python 3.9+
- Node.js 16+
- PostgreSQL
- Redis
- Kafka
- ClickHouse

### Installation

#### Clone the repository

```bash
git clone https://github.com/yourusername/sentryflow.git
cd sentryflow
```

#### Backend Setup

```bash
# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
cd backend
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your configuration

# Run migrations
alembic upgrade head

# Start the backend server
uvicorn main:app --reload
```

#### Analytics Aggregator Setup

```bash
# In a new terminal
cd aggregator
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your configuration

# Start the aggregator
python batch_consumer.py
```

#### Frontend Setup

```bash
# In a new terminal
cd frontend
npm install

# Start the development server
npm start
```

### Docker Deployment

For production deployment, you can use Docker Compose:

```bash
# Build and start all services
docker-compose up -d
```

## Usage

### Creating an API Key

1. Register a user account or log in to an existing account
2. Navigate to the API Keys section
3. Click "Create New API Key" and provide a name for the key
4. Copy the generated API key (it will only be shown once)

### Implementing Rate Limits

1. Go to the Rate Limit Monitor section
2. Configure rate limits for specific endpoints
3. Choose between sliding window or token bucket algorithms
4. Set appropriate limits and time windows

### Monitoring API Usage

1. Visit the Dashboard to view overall metrics
2. Use the User View to analyze specific user behavior
3. Check the Logs Explorer for detailed request information


## Acknowledgements

- [FastAPI](https://fastapi.tiangolo.com/)
- [React](https://reactjs.org/)
- [Chart.js](https://www.chartjs.org/)
- [Tailwind CSS](https://tailwindcss.com/)
- [Kafka](https://kafka.apache.org/)
- [ClickHouse](https://clickhouse.tech/)
