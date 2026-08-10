# SentryFlow Analytics Guide

This document provides a comprehensive guide to SentryFlow's analytics capabilities, including available metrics, visualization options, and how to leverage analytics data for API optimization.

## Overview

SentryFlow's analytics system collects, processes, and visualizes API usage data to provide insights into your API's performance, usage patterns, and potential issues. The analytics pipeline consists of:

1. **Data Collection**: API request data is captured by the backend service
2. **Data Processing**: The analytics aggregator processes and stores data in ClickHouse
3. **Data Visualization**: The frontend dashboard presents the data in an intuitive interface

## Available Metrics

SentryFlow collects and analyzes the following metrics:

### Request Metrics

- **Request Volume**: Total number of API requests over time
- **Request Distribution**: Breakdown of requests by endpoint, method, and status code
- **Response Time**: Average, median, 95th percentile, and maximum response times
- **Error Rate**: Percentage of requests resulting in error responses (4xx and 5xx status codes)
- **Success Rate**: Percentage of requests resulting in successful responses (2xx status codes)

### User Metrics

- **Active Users**: Number of unique users/API keys making requests
- **Top Users**: Users with the highest request volumes
- **User Growth**: Change in the number of active users over time
- **User Retention**: Percentage of users who continue to use the API over time

### Rate Limiting Metrics

- **Rate Limit Events**: Occurrences of rate limit violations
- **Rate Limit Distribution**: Breakdown of rate limit events by user, endpoint, and limit type
- **Rate Limit Utilization**: How close users are to hitting their rate limits

### Performance Metrics

- **Endpoint Performance**: Response times and error rates by endpoint
- **System Load**: Server resource utilization correlated with API traffic
- **Cache Efficiency**: Cache hit rates and impact on response times

## Analytics Dashboard

The SentryFlow dashboard provides a visual interface for exploring analytics data. The dashboard is organized into several sections:

### Overview

The overview section provides a high-level summary of API usage, including:

- Total requests over selected time period
- Success rate and error rate
- Average response time
- Active users
- Recent rate limit events

### Request Analysis

The request analysis section allows you to drill down into request data:

- Request volume over time (with customizable time intervals)
- Request distribution by endpoint, method, and status code
- Top endpoints by volume, error rate, and response time
- Request volume patterns (daily, weekly, monthly)

### User Analysis

The user analysis section focuses on user behavior:

- Active users over time
- Top users by request volume
- User growth and retention metrics
- User activity heatmap (by time of day and day of week)

### Rate Limit Analysis

The rate limit analysis section provides insights into rate limiting:

- Rate limit events over time
- Top users hitting rate limits
- Top endpoints triggering rate limits
- Rate limit utilization by user and endpoint

### Performance Analysis

The performance analysis section focuses on API performance:

- Response time distribution
- Response time by endpoint
- Error rate by endpoint
- System load correlation with traffic

## Data Aggregation

SentryFlow aggregates data at multiple time granularities to balance detail and performance:

- **Raw Data**: Individual request data (retained for a configurable period, default: 7 days)
- **Minute Aggregation**: Data aggregated by minute (retained for 30 days)
- **Hourly Aggregation**: Data aggregated by hour (retained for 90 days)
- **Daily Aggregation**: Data aggregated by day (retained for 1 year)
- **Monthly Aggregation**: Data aggregated by month (retained indefinitely)

Aggregation is performed by the analytics aggregator service, which processes data from Kafka and stores it in ClickHouse tables optimized for analytical queries.

## Custom Analytics

### Custom Dashboards

SentryFlow allows you to create custom dashboards with the metrics and visualizations most relevant to your needs:

1. Navigate to **Analytics** > **Custom Dashboards**
2. Click **Create Dashboard**
3. Add and configure widgets from the available metrics
4. Arrange widgets as desired
5. Save the dashboard with a descriptive name

### Custom Metrics

You can define custom metrics based on request attributes:

1. Navigate to **Analytics** > **Custom Metrics**
2. Click **Create Metric**
3. Define the metric using the metric builder or SQL query
4. Configure aggregation and visualization options
5. Save the metric with a descriptive name

Example custom metrics:

- Requests per user segment
- Error rate for specific error codes
- Response time for requests with specific parameters
- Success rate for authenticated vs. unauthenticated requests

## Analytics API

SentryFlow provides an API for programmatic access to analytics data:

### Get API Usage Metrics

```
GET /api/v1/analytics/usage
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

### Get User Metrics

```
GET /api/v1/analytics/users
```

**Query Parameters:**

- `start_date`: Start date in ISO format (required)
- `end_date`: End date in ISO format (required)
- `interval`: Aggregation interval (day, week, month)
- `top_n`: Number of top users to include (default: 10)

**Response:**

```json
{
  "total_users": 250,
  "active_users": 120,
  "new_users": 15,
  "top_users": [
    {
      "user_id": "user_uuid",
      "username": "example_user",
      "request_count": 1500,
      "average_response_time": 110
    },
    // More users...
  ],
  "data_points": [
    {
      "timestamp": "2023-01-01T00:00:00Z",
      "active_users": 100,
      "new_users": 5
    },
    // More data points...
  ]
}
```

### Get Endpoint Metrics

```
GET /api/v1/analytics/endpoints
```

**Query Parameters:**

- `start_date`: Start date in ISO format (required)
- `end_date`: End date in ISO format (required)
- `interval`: Aggregation interval (hour, day, week, month)
- `top_n`: Number of top endpoints to include (default: 10)

**Response:**

```json
{
  "total_endpoints": 25,
  "top_endpoints": [
    {
      "endpoint": "/api/v1/data",
      "request_count": 5000,
      "average_response_time": 130,
      "error_rate": 1.2
    },
    // More endpoints...
  ],
  "data_points": [
    {
      "timestamp": "2023-01-01T00:00:00Z",
      "endpoint": "/api/v1/data",
      "request_count": 200,
      "average_response_time": 125,
      "error_count": 2
    },
    // More data points...
  ]
}
```

## Data Export

SentryFlow allows you to export analytics data for further analysis or integration with other systems:

### Export Formats

- **CSV**: Comma-separated values for spreadsheet applications
- **JSON**: Structured data for programmatic processing
- **Excel**: Formatted spreadsheets with multiple tabs

### Export Methods

- **Manual Export**: Download data directly from the dashboard
- **Scheduled Export**: Configure regular exports to be delivered via email or stored in a specified location
- **API Export**: Use the analytics API with the `format` parameter set to the desired export format

## Alerts and Notifications

SentryFlow can alert you when certain metrics exceed defined thresholds:

### Alert Types

- **Threshold Alerts**: Triggered when a metric exceeds a specified value
- **Anomaly Alerts**: Triggered when a metric deviates significantly from historical patterns
- **Trend Alerts**: Triggered when a metric shows a consistent trend over time

### Alert Channels

- **Email**: Receive alerts via email
- **Webhook**: Send alerts to a specified webhook endpoint
- **Slack**: Receive alerts in a Slack channel
- **PagerDuty**: Integrate with PagerDuty for incident management

### Alert Configuration

1. Navigate to **Analytics** > **Alerts**
2. Click **Create Alert**
3. Select the metric and alert type
4. Configure the threshold or anomaly detection parameters
5. Select the alert channels
6. Set the alert frequency and quiet periods
7. Save the alert with a descriptive name

## Using Analytics for API Optimization

SentryFlow analytics can help you optimize your API in several ways:

### Performance Optimization

1. **Identify Slow Endpoints**: Use response time metrics to identify endpoints that need optimization
2. **Analyze Response Time Patterns**: Look for patterns in response time variations (e.g., slow during peak hours)
3. **Correlate with System Metrics**: Determine if slow response times are related to system load
4. **Implement Caching**: Use cache efficiency metrics to identify opportunities for caching

### Rate Limit Optimization

1. **Analyze Rate Limit Events**: Identify users and endpoints frequently hitting rate limits
2. **Adjust Rate Limits**: Fine-tune rate limits based on actual usage patterns
3. **Implement Tiered Rate Limiting**: Create different rate limit tiers for different user groups
4. **Educate Users**: Reach out to users frequently hitting rate limits to help them optimize their usage

### Error Reduction

1. **Identify Error Hotspots**: Use error rate metrics to identify endpoints with high error rates
2. **Analyze Error Patterns**: Look for patterns in error occurrences (e.g., specific users, times, or request parameters)
3. **Implement Error Handling**: Improve error handling for common error scenarios
4. **Monitor Error Trends**: Track error rates over time to ensure improvements are effective

### User Experience Improvement

1. **Analyze User Behavior**: Use user metrics to understand how users interact with your API
2. **Identify Popular Endpoints**: Focus optimization efforts on the most frequently used endpoints
3. **Track User Retention**: Monitor user retention metrics to identify potential issues
4. **Gather Feedback**: Correlate analytics data with user feedback to identify improvement opportunities

## Best Practices

### Data Collection

1. **Collect Comprehensive Data**: Ensure you're collecting all relevant request attributes
2. **Balance Detail and Volume**: Find the right balance between data detail and storage requirements
3. **Implement Sampling**: For high-volume APIs, consider sampling requests to reduce data volume
4. **Ensure Data Privacy**: Be mindful of privacy considerations when collecting and storing data

### Data Analysis

1. **Use Appropriate Time Ranges**: Select time ranges that provide meaningful insights for your analysis
2. **Compare Similar Periods**: Compare metrics across similar time periods (e.g., week-over-week, month-over-month)
3. **Consider Seasonality**: Account for daily, weekly, and seasonal patterns in your analysis
4. **Look for Correlations**: Analyze relationships between different metrics

### Dashboard Usage

1. **Create Role-Specific Dashboards**: Create different dashboards for different roles (e.g., developers, operations, management)
2. **Focus on Actionable Metrics**: Prioritize metrics that can drive decisions and actions
3. **Use Appropriate Visualizations**: Choose the right visualization type for each metric
4. **Include Context**: Provide context and explanations for complex metrics

## Conclusion

SentryFlow's analytics capabilities provide valuable insights into your API's performance, usage patterns, and potential issues. By leveraging these insights, you can optimize your API, improve user experience, and make data-driven decisions about your API strategy.