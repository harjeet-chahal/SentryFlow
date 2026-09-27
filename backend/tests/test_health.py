"""Health, readiness and liveness endpoints."""
from redis.exceptions import ConnectionError as RedisConnectionError

from backend import health_check, redis_client
from backend.middlewares import logging_middleware


class DownRedis:
    async def ping(self):
        raise RedisConnectionError("redis is down")


def test_liveness_is_always_ok(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_liveness_stays_ok_when_dependencies_are_down(client):
    """The point of a liveness probe: a Redis blip must not restart the pod."""
    redis_client.set_redis(DownRedis())
    assert client.get("/health/live").status_code == 200


def test_readiness_reports_ready_when_dependencies_are_up(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readiness_fails_when_redis_is_down(client):
    """A failing readiness probe pulls the pod from the Service, no restart."""
    redis_client.set_redis(DownRedis())

    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["redis"]["status"] == "unhealthy"


def test_health_reports_every_component(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert set(body["components"]) == {"database", "redis", "kafka"}
    assert body["response_time_ms"] >= 0


def test_health_includes_per_component_latency(client):
    body = client.get("/health").json()
    assert body["components"]["database"]["latency_ms"] >= 0
    assert body["components"]["redis"]["latency_ms"] >= 0


def test_health_is_degraded_not_unhealthy_without_kafka(client):
    """Kafka is non-critical: the gateway still serves traffic without it."""
    logging_middleware.set_producer(None)

    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["components"]["kafka"]["status"] == "unavailable"
    assert body["components"]["kafka"]["detail"] == "Connecting to Kafka"


def test_health_reports_usage_events_kafka_refused(client, api_key, fake_kafka, published):
    """Connected is not enough: a broker that stops taking events is degraded too."""
    fake_kafka.fail = True
    client.get("/api/v1/hello", headers={"x-api-key": api_key["key"]})
    published()

    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["components"]["kafka"] == {
        "status": "unavailable",
        "detail": "Kafka is not accepting events",
        "queued": 0,
        "dropped": 0,
        "failed": 1,
    }


def test_health_is_503_when_a_critical_component_is_down(client):
    redis_client.set_redis(DownRedis())

    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"


async def test_component_check_surfaces_the_error_message():
    redis_client.set_redis(DownRedis())
    result = await health_check.check_redis()
    assert result["status"] == "unhealthy"
    assert "down" in result["error"]
