# SentryFlow Deployment Guide

This document provides comprehensive instructions for deploying SentryFlow in various environments, from development to production.

## Deployment Options

SentryFlow can be deployed in several ways depending on your requirements:

1. **Docker Compose**: Simplest option for small to medium deployments
2. **Kubernetes**: Recommended for production deployments with high availability requirements
3. **Manual Deployment**: For custom environments or when containers are not an option

## Prerequisites

Regardless of the deployment method, you'll need:

- PostgreSQL 13+ database
- Redis 6+ instance
- Apache Kafka 2.8+ cluster with Zookeeper
- ClickHouse 21.8+ database
- Network connectivity between all components

## Docker Compose Deployment

The Docker Compose deployment is the simplest way to get SentryFlow up and running.

### Requirements

- Docker Engine 20.10+
- Docker Compose 2.0+
- At least 4GB of RAM
- At least 20GB of disk space

### Steps

1. **Clone the repository**

```bash
git clone https://github.com/yourusername/sentryflow.git
cd sentryflow
```

2. **Configure environment variables**

Create `.env` files for each component based on the provided examples:

```bash
cp backend/.env.example backend/.env
cp aggregator/.env.example aggregator/.env
cp frontend/.env.example frontend/.env
```

Edit the `.env` files to match your environment. At minimum, you should set:

- Database credentials
- JWT secret key
- Admin user credentials

3. **Start the services**

```bash
# Build and start all services
docker-compose up -d

# Or use the provided script
./docker_start.sh
```

On Windows:

```bash
.\docker_start.bat
```

4. **Initialize the databases**

The initialization scripts should run automatically, but you can also run them manually:

```bash
docker-compose exec backend python setup_db.py
docker-compose exec aggregator python setup_clickhouse.py
```

5. **Verify the deployment**

Access the following URLs to verify that all components are running:

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Documentation: http://localhost:8000/docs
- Kafka UI: http://localhost:8080

### Scaling with Docker Compose

For higher load, you can scale the backend and aggregator services:

```bash
docker-compose up -d --scale backend=3 --scale aggregator=2
```

Note that this requires configuring a load balancer in front of the backend services.

## Kubernetes Deployment

For production deployments with high availability requirements, Kubernetes is recommended.

### Requirements

- Kubernetes cluster 1.19+
- Helm 3.0+
- kubectl configured to access your cluster
- Persistent storage for databases

### Steps

1. **Clone the repository**

```bash
git clone https://github.com/yourusername/sentryflow.git
cd sentryflow/kubernetes
```

2. **Configure Helm values**

Edit the `values.yaml` file to match your environment. At minimum, you should set:

- Database connection details
- JWT secret key
- Admin user credentials
- Resource requests and limits
- Persistent volume configurations

3. **Deploy with Helm**

```bash
helm install sentryflow ./chart
```

4. **Wait for all pods to be ready**

```bash
kubectl get pods -w
```

5. **Initialize the databases**

```bash
kubectl exec -it $(kubectl get pods -l app=sentryflow-backend -o jsonpath='{.items[0].metadata.name}') -- python setup_db.py
kubectl exec -it $(kubectl get pods -l app=sentryflow-aggregator -o jsonpath='{.items[0].metadata.name}') -- python setup_clickhouse.py
```

6. **Access the services**

Get the external IP or hostname for the frontend service:

```bash
kubectl get service sentryflow-frontend
```

Access the frontend using the external IP or hostname.

### High Availability Configuration

The Kubernetes deployment is designed for high availability:

- Multiple replicas of backend and aggregator services
- Pod anti-affinity to distribute replicas across nodes
- Readiness and liveness probes for automatic recovery
- Horizontal Pod Autoscaling based on CPU and memory usage

You can adjust the high availability settings in the `values.yaml` file.

## Manual Deployment

For environments where containers are not an option, you can deploy SentryFlow manually.

### Requirements

- Python 3.9+
- Node.js 16+
- PostgreSQL 13+
- Redis 6+
- Apache Kafka 2.8+ with Zookeeper
- ClickHouse 21.8+
- Nginx or another web server

### Steps

1. **Clone the repository**

```bash
git clone https://github.com/yourusername/sentryflow.git
cd sentryflow
```

2. **Set up the backend**

```bash
cd backend

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env with your configuration

# Initialize the database
python setup_db.py

# Start the backend service
uvicorn main:app --host 0.0.0.0 --port 8000
```

3. **Set up the aggregator**

```bash
cd aggregator

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env with your configuration

# Initialize ClickHouse
python setup_clickhouse.py

# Start the aggregator service
python batch_consumer.py
```

4. **Set up the frontend**

```bash
cd frontend

# Install dependencies
npm install

# Configure environment variables
cp .env.example .env
# Edit .env with your configuration

# Build the frontend
npm run build

# Serve the frontend with Nginx or another web server
# Copy the build directory to your web server's document root
```

5. **Configure Nginx**

Create an Nginx configuration file for the frontend and backend:

```nginx
server {
    listen 80;
    server_name your-sentryflow-domain.com;

    # Frontend
    location / {
        root /path/to/sentryflow/frontend/build;
        try_files $uri $uri/ /index.html;
    }

    # Backend API
    location /api/ {
        proxy_pass http://localhost:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Backend health check
    location /health {
        proxy_pass http://localhost:8000/health;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

6. **Set up systemd services**

Create systemd service files for the backend and aggregator:

```ini
# /etc/systemd/system/sentryflow-backend.service
[Unit]
Description=SentryFlow Backend Service
After=network.target

[Service]
User=sentryflow
WorkingDirectory=/path/to/sentryflow/backend
EnvironmentFile=/path/to/sentryflow/backend/.env
ExecStart=/path/to/sentryflow/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/sentryflow-aggregator.service
[Unit]
Description=SentryFlow Aggregator Service
After=network.target

[Service]
User=sentryflow
WorkingDirectory=/path/to/sentryflow/aggregator
EnvironmentFile=/path/to/sentryflow/aggregator/.env
ExecStart=/path/to/sentryflow/aggregator/venv/bin/python batch_consumer.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start the services:

```bash
systemctl enable sentryflow-backend.service
systemctl start sentryflow-backend.service
systemctl enable sentryflow-aggregator.service
systemctl start sentryflow-aggregator.service
```

## Production Considerations

### Security

1. **Use HTTPS**: Always use HTTPS in production. Configure SSL certificates for your web server.

2. **Secure Secrets**: Store sensitive information like database credentials and JWT secrets securely. Consider using a secret management solution like HashiCorp Vault or Kubernetes Secrets.

3. **Network Security**: Use network policies or firewall rules to restrict access between components.

4. **Regular Updates**: Keep all components updated with security patches.

### Performance

1. **Database Optimization**: Tune PostgreSQL and ClickHouse for your workload.

2. **Caching**: Configure Redis caching appropriately for your usage patterns.

3. **Load Balancing**: Use a load balancer in front of multiple backend instances.

4. **Resource Allocation**: Allocate appropriate CPU and memory resources based on expected load.

### Monitoring

1. **Health Checks**: Use the `/health`, `/ready`, and `/live` endpoints to monitor service health.

2. **Metrics**: Set up Prometheus and Grafana for monitoring system metrics.

3. **Logging**: Configure centralized logging with ELK stack or similar.

4. **Alerts**: Set up alerts for critical issues like service unavailability or high error rates.

### Backup and Recovery

1. **Database Backups**: Regularly back up PostgreSQL and ClickHouse databases.

2. **Configuration Backups**: Back up all configuration files and environment variables.

3. **Disaster Recovery Plan**: Develop and test a disaster recovery plan.

## Upgrading

### Docker Compose Upgrade

1. Pull the latest changes:

```bash
git pull
```

2. Rebuild and restart the services:

```bash
docker-compose down
docker-compose build
docker-compose up -d
```

### Kubernetes Upgrade

1. Update the Helm chart:

```bash
git pull
helm upgrade sentryflow ./kubernetes/chart
```

### Manual Upgrade

1. Pull the latest changes:

```bash
git pull
```

2. Update dependencies:

```bash
cd backend
source venv/bin/activate
pip install -r requirements.txt

cd ../aggregator
source venv/bin/activate
pip install -r requirements.txt

cd ../frontend
npm install
npm run build
```

3. Apply database migrations (if any):

```bash
cd backend
python setup_db.py

cd ../aggregator
python setup_clickhouse.py
```

4. Restart the services:

```bash
systemctl restart sentryflow-backend.service
systemctl restart sentryflow-aggregator.service
```

## Troubleshooting

### Common Issues

1. **Database Connection Errors**:
   - Verify database credentials in environment variables
   - Check network connectivity to the database
   - Ensure the database server is running

2. **Kafka Connection Issues**:
   - Verify Kafka broker addresses in environment variables
   - Check network connectivity to Kafka
   - Ensure Kafka topics exist

3. **Frontend Not Loading**:
   - Check Nginx configuration
   - Verify that the frontend build was successful
   - Check browser console for JavaScript errors

4. **Backend API Errors**:
   - Check backend logs for error messages
   - Verify environment variables
   - Check database connectivity

### Diagnostic Tools

1. **Health Check Script**:

Use the provided health check script to verify all components:

```bash
python scripts/check_health.py
```

2. **Log Analysis**:

Check logs for error messages:

```bash
# Docker Compose
docker-compose logs backend
docker-compose logs aggregator

# Kubernetes
kubectl logs -l app=sentryflow-backend
kubectl logs -l app=sentryflow-aggregator

# Manual Deployment
journalctl -u sentryflow-backend.service
journalctl -u sentryflow-aggregator.service
```

3. **Database Verification**:

Verify database schema and connectivity:

```bash
# PostgreSQL
psql -h <host> -U <user> -d sentryflow -c "\dt"

# ClickHouse
clickhouse-client --host <host> --query "SHOW TABLES FROM sentryflow"
```

## Conclusion

This deployment guide covers the most common deployment scenarios for SentryFlow. For specific requirements or custom deployments, please refer to the component-specific documentation or contact the development team.