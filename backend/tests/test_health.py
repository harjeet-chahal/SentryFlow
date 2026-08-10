import pytest
from fastapi.testclient import TestClient


def test_health_check(test_app):
    """Test the health check endpoint."""
    client = TestClient(test_app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"