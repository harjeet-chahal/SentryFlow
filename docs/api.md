# SentryFlow API Documentation

This document provides a comprehensive guide to the SentryFlow API endpoints, authentication methods, and usage examples.

## Base URL

All API endpoints are relative to the base URL:

```
http://your-sentryflow-instance/api/v1
```

## Authentication

SentryFlow uses API key authentication. Include your API key in the request header:

```
X-API-Key: your_api_key_here
```

Alternatively, you can use Bearer token authentication:

```
Authorization: Bearer your_jwt_token_here
```

## Rate Limiting

All API endpoints are subject to rate limiting. The default rate limits are:

- 100 requests per minute per API key
- 1000 requests per hour per API key

When a rate limit is exceeded, the API will return a `429 Too Many Requests` response with a `Retry-After` header indicating when you can retry the request.

## API Endpoints

### Authentication

#### Register a new user

```
POST /auth/register
```

**Request Body:**

```json
{
  "username": "example_user",
  "email": "user@example.com",
  "password": "secure_password",
  "full_name": "Example User"
}
```

**Response:**

```json
{
  "id": "user_uuid",
  "username": "example_user",
  "email": "user@example.com",
  "full_name": "Example User",
  "created_at": "2023-01-01T00:00:00Z"
}
```

#### Login

```
POST /auth/login
```

**Request Body:**

```json
{
  "username": "example_user",
  "password": "secure_password"
}
```

**Response:**

```json
{
  "access_token": "jwt_token_here",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "id": "user_uuid",
    "username": "example_user",
    "email": "user@example.com"
  }
}
```

### API Keys

#### Create API Key

```
POST /api-keys
```

**Request Body:**

```json
{
  "name": "My Application",
  "expires_at": "2024-01-01T00:00:00Z",  // Optional
  "permissions": ["read", "write"]      // Optional
}
```

**Response:**

```json
{
  "id": "api_key_uuid",
  "key": "sk_live_xxxxxxxxxxxxxxxxxxxx",  // Only shown once
  "name": "My Application",
  "created_at": "2023-01-01T00:00:00Z",
  "expires_at": "2024-01-01T00:00:00Z",
  "permissions": ["read", "write"],
  "last_used_at": null
}
```

#### List API Keys

```
GET /api-keys
```

**Response:**

```json
{
  "items": [
    {
      "id": "api_key_uuid",
      "name": "My Application",
      "created_at": "2023-01-01T00:00:00Z",
      "expires_at": "2024-01-01T00:00:00Z",
      "permissions": ["read", "write"],
      "last_used_at": "2023-01-02T00:00:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "size": 10
}
```

#### Revoke API Key

```
DELETE /api-keys/{api_key_id}
```

**Response:**

```json
{
  "success": true,
  "message": "API key revoked successfully"
}
```

### Rate Limits

#### Get Rate Limit Configuration

```
GET /rate-limits
```

**Response:**

```json
{
  "global": {
    "requests_per_minute": 100,
    "requests_per_hour": 1000
  },
  "endpoints": {
    "/api/v1/data": {
      "requests_per_minute": 50,
      "requests_per_hour": 500
    }
  }
}
```

#### Update Rate Limit Configuration

```
PUT /rate-limits
```

**Request Body:**

```json
{
  "global": {
    "requests_per_minute": 200,
    "requests_per_hour": 2000
  },
  "endpoints": {
    "/api/v1/data": {
      "requests_per_minute": 100,
      "requests_per_hour": 1000
    }
  }
}
```

**Response:**

```json
{
  "success": true,
  "message": "Rate limit configuration updated successfully"
}
```

### Analytics

#### Get API Usage Metrics

```
GET /analytics/usage
```

**Query Parameters:**

- `start_date`: Start date in ISO format (required)
- `end_date`: End date in ISO format (required)
- `interval`: Aggregation interval (minute, hour, day, week, month)
- `endpoint`: Filter by specific endpoint
- `user_id`: Filter by specific user

**Response:**

```json
{
  "total_requests": 12500,
  "success_rate": 98.5,
  "average_response_time": 120,
  "data_points": [
    {
      "timestamp": "2023-01-01T00:00:00Z",
      "requests": 500,
      "success_count": 490,
      "error_count": 10,
      "average_response_time": 115
    },
    // More data points...
  ]
}
```

#### Get Rate Limit Events

```
GET /analytics/rate-limits
```

**Query Parameters:**

- `start_date`: Start date in ISO format (required)
- `end_date`: End date in ISO format (required)
- `user_id`: Filter by specific user
- `api_key_id`: Filter by specific API key

**Response:**

```json
{
  "total_events": 250,
  "events": [
    {
      "timestamp": "2023-01-01T12:30:45Z",
      "user_id": "user_uuid",
      "api_key_id": "api_key_uuid",
      "endpoint": "/api/v1/data",
      "limit_type": "requests_per_minute",
      "limit_value": 100,
      "current_usage": 101
    },
    // More events...
  ]
}
```

## Error Handling

SentryFlow API uses standard HTTP status codes to indicate the success or failure of an API request.

### Common Status Codes

- `200 OK`: The request was successful
- `201 Created`: The resource was successfully created
- `400 Bad Request`: The request was invalid or cannot be served
- `401 Unauthorized`: Authentication failed or user doesn't have permissions
- `403 Forbidden`: The request is valid but the user doesn't have permissions
- `404 Not Found`: The requested resource could not be found
- `429 Too Many Requests`: Rate limit exceeded
- `500 Internal Server Error`: An error occurred on the server

### Error Response Format

```json
{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "You have exceeded the rate limit for this endpoint",
    "details": {
      "limit": 100,
      "current": 101,
      "reset_at": "2023-01-01T12:31:45Z"
    }
  }
}
```

## Webhooks

SentryFlow can send webhook notifications for various events:

### Configure Webhooks

```
POST /webhooks
```

**Request Body:**

```json
{
  "url": "https://your-server.com/webhook",
  "secret": "your_webhook_secret",
  "events": ["rate_limit.exceeded", "api_key.created", "api_key.revoked"]
}
```

**Response:**

```json
{
  "id": "webhook_uuid",
  "url": "https://your-server.com/webhook",
  "events": ["rate_limit.exceeded", "api_key.created", "api_key.revoked"],
  "created_at": "2023-01-01T00:00:00Z",
  "active": true
}
```

### Webhook Payload Example

```json
{
  "event": "rate_limit.exceeded",
  "created_at": "2023-01-01T12:30:45Z",
  "data": {
    "user_id": "user_uuid",
    "api_key_id": "api_key_uuid",
    "endpoint": "/api/v1/data",
    "limit_type": "requests_per_minute",
    "limit_value": 100,
    "current_usage": 101
  }
}
```

## SDKs and Client Libraries

SentryFlow provides official client libraries for various programming languages:

- [Python SDK](https://github.com/yourusername/sentryflow-python)
- [JavaScript SDK](https://github.com/yourusername/sentryflow-js)
- [Go SDK](https://github.com/yourusername/sentryflow-go)
- [Java SDK](https://github.com/yourusername/sentryflow-java)

## Rate Limiting Algorithms

SentryFlow supports two rate limiting algorithms:

### Sliding Window

The sliding window algorithm tracks requests over a rolling time window. This provides more accurate rate limiting but requires more memory.

### Token Bucket

The token bucket algorithm uses a bucket of tokens that refills at a constant rate. Each request consumes a token, and requests are rejected when the bucket is empty. This is more memory-efficient but less precise.

## Best Practices

1. **Store API keys securely**: Never expose API keys in client-side code or public repositories.

2. **Implement retry logic**: When receiving a 429 response, implement exponential backoff with jitter.

3. **Use webhooks for monitoring**: Set up webhooks to be notified of rate limit events and other important occurrences.

4. **Implement proper error handling**: Always check for error responses and handle them appropriately.

5. **Monitor your usage**: Regularly check your API usage metrics to optimize your implementation.