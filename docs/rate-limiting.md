# SentryFlow Rate Limiting Documentation

This document provides a comprehensive guide to SentryFlow's rate limiting capabilities, including configuration options, algorithms, and best practices.

## Overview

Rate limiting is a critical component of API management that helps protect your services from abuse, ensures fair usage, and maintains system stability. SentryFlow offers flexible and powerful rate limiting features that can be tailored to your specific needs.

## Rate Limiting Algorithms

SentryFlow supports two primary rate limiting algorithms:

### 1. Sliding Window

The sliding window algorithm tracks requests over a rolling time window, providing more accurate rate limiting but requiring more memory.

**How it works:**
- Maintains a timestamp for each request within the window
- As time progresses, older timestamps outside the window are discarded
- New requests are counted against the total within the current window

**Best for:**
- More precise control over request rates
- Applications where accuracy is more important than memory usage
- APIs with moderate traffic volumes

### 2. Token Bucket

The token bucket algorithm uses a bucket of tokens that refills at a constant rate. Each request consumes a token, and requests are rejected when the bucket is empty.

**How it works:**
- A bucket holds a maximum number of tokens
- Tokens are added to the bucket at a fixed rate
- Each request consumes one token
- If the bucket is empty, requests are rejected

**Best for:**
- Memory-efficient rate limiting
- Handling traffic spikes (allows bursts up to bucket capacity)
- High-volume APIs

## Configuration Options

### Global Rate Limits

Global rate limits apply to all endpoints and can be configured in the SentryFlow dashboard or via the API.

```json
{
  "global": {
    "requests_per_minute": 100,
    "requests_per_hour": 1000,
    "algorithm": "sliding_window"
  }
}
```

### Endpoint-Specific Rate Limits

You can set different rate limits for specific endpoints based on their sensitivity or resource requirements.

```json
{
  "endpoints": {
    "/api/v1/data": {
      "requests_per_minute": 50,
      "requests_per_hour": 500,
      "algorithm": "token_bucket"
    },
    "/api/v1/search": {
      "requests_per_minute": 20,
      "requests_per_hour": 200,
      "algorithm": "sliding_window"
    }
  }
}
```

### User-Based Rate Limits

Different users or API keys can have different rate limits based on their tier or requirements.

```json
{
  "user_tiers": {
    "free": {
      "requests_per_minute": 10,
      "requests_per_hour": 100,
      "algorithm": "sliding_window"
    },
    "premium": {
      "requests_per_minute": 100,
      "requests_per_hour": 1000,
      "algorithm": "token_bucket"
    },
    "enterprise": {
      "requests_per_minute": 1000,
      "requests_per_hour": 10000,
      "algorithm": "token_bucket"
    }
  }
}
```

## Rate Limit Response

When a rate limit is exceeded, SentryFlow returns a standard `429 Too Many Requests` response with additional headers to help clients handle the situation:

```
HTTP/1.1 429 Too Many Requests
Content-Type: application/json
Retry-After: 30
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1609459200

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

### Response Headers

- `Retry-After`: Seconds until the client can retry the request
- `X-RateLimit-Limit`: The rate limit ceiling for the given endpoint
- `X-RateLimit-Remaining`: The number of requests left for the time window
- `X-RateLimit-Reset`: The time at which the rate limit resets, in Unix time

## Configuring Rate Limits

### Via Dashboard

1. Log in to the SentryFlow dashboard
2. Navigate to **Settings** > **Rate Limits**
3. Configure global, endpoint-specific, or user-based rate limits
4. Click **Save Changes**

### Via API

Rate limits can also be configured programmatically via the API:

```
PUT /api/v1/rate-limits
Content-Type: application/json
Authorization: Bearer your_jwt_token_here

{
  "global": {
    "requests_per_minute": 200,
    "requests_per_hour": 2000,
    "algorithm": "sliding_window"
  },
  "endpoints": {
    "/api/v1/data": {
      "requests_per_minute": 100,
      "requests_per_hour": 1000,
      "algorithm": "token_bucket"
    }
  }
}
```

## Monitoring Rate Limits

SentryFlow provides several ways to monitor rate limit usage and violations:

### Dashboard Analytics

The SentryFlow dashboard includes visualizations of:

- Rate limit usage over time
- Rate limit violations by endpoint
- Rate limit violations by user/API key

### Alerts and Notifications

You can configure alerts to be notified when:

- Rate limit usage exceeds a certain percentage (e.g., 80%)
- Rate limit violations occur more than a specified threshold
- Specific users or endpoints experience frequent rate limit violations

### Webhooks

SentryFlow can send webhook notifications when rate limits are exceeded:

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

## Best Practices

### For API Providers

1. **Start with conservative limits**: Begin with lower limits and increase them as needed based on usage patterns.

2. **Use different limits for different endpoints**: Resource-intensive endpoints should have lower limits than lightweight ones.

3. **Implement tiered rate limiting**: Offer different rate limits for different user tiers or subscription levels.

4. **Monitor and analyze**: Regularly review rate limit violations to identify potential abuse or legitimate needs for higher limits.

5. **Communicate clearly**: Ensure your rate limit policies are clearly documented for API consumers.

### For API Consumers

1. **Implement retry logic**: When receiving a 429 response, implement exponential backoff with jitter:

```python
import time
import random

def make_request_with_retry(url, max_retries=5):
    retries = 0
    while retries < max_retries:
        response = requests.get(url)
        if response.status_code != 429:  # Not rate limited
            return response
        
        # Parse retry time from headers, default to exponential backoff
        retry_after = int(response.headers.get('Retry-After', 2 ** retries))
        # Add jitter to prevent thundering herd problem
        sleep_time = retry_after + (random.randint(0, 1000) / 1000.0)
        time.sleep(sleep_time)
        retries += 1
    
    # Max retries exceeded
    return response
```

2. **Cache responses**: Reduce the number of API calls by caching responses when appropriate.

3. **Batch requests**: Combine multiple operations into a single API call when possible.

4. **Monitor your usage**: Keep track of your API usage to avoid hitting rate limits.

5. **Distribute traffic**: If possible, distribute requests evenly over time rather than sending them in bursts.

## Advanced Configuration

### Custom Rate Limit Keys

SentryFlow allows you to define custom keys for rate limiting beyond the default user/API key and endpoint combinations:

```json
{
  "custom_keys": {
    "ip_address": {
      "requests_per_minute": 50,
      "requests_per_hour": 500
    },
    "user_agent": {
      "requests_per_minute": 200,
      "requests_per_hour": 2000
    }
  }
}
```

### Rate Limit Groups

You can create groups of endpoints that share the same rate limit bucket:

```json
{
  "endpoint_groups": {
    "read_operations": {
      "endpoints": ["/api/v1/data/get", "/api/v1/search"],
      "requests_per_minute": 100,
      "requests_per_hour": 1000
    },
    "write_operations": {
      "endpoints": ["/api/v1/data/create", "/api/v1/data/update"],
      "requests_per_minute": 50,
      "requests_per_hour": 500
    }
  }
}
```

### Dynamic Rate Limiting

SentryFlow supports dynamic rate limiting based on server load or other metrics:

```json
{
  "dynamic_limits": {
    "enabled": true,
    "scaling_factor": 0.5,  // Reduce limits by 50% when triggered
    "triggers": {
      "server_load": {
        "threshold": 0.8,  // 80% CPU usage
        "window": 60  // Measured over 60 seconds
      },
      "error_rate": {
        "threshold": 0.05,  // 5% error rate
        "window": 300  // Measured over 5 minutes
      }
    }
  }
}
```

## Conclusion

Effective rate limiting is essential for maintaining the stability, security, and fairness of your API. SentryFlow provides flexible and powerful rate limiting capabilities that can be tailored to your specific needs. By following the best practices outlined in this document, you can implement rate limiting that protects your services while providing a good experience for your API consumers.