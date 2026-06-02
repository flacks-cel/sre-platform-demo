from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_alive():
    response = client.get("/health")
    assert response.json() == {"status": "alive"}


def test_ready_returns_200():
    response = client.get("/ready")
    assert response.status_code == 200


def test_ready_returns_ready():
    response = client.get("/ready")
    assert response.json() == {"status": "ready"}


def test_root_returns_200():
    response = client.get("/")
    assert response.status_code == 200


def test_root_contains_service_name():
    response = client.get("/")
    assert response.json()["service"] == "jobs-api"
